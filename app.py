import os
import json
import datetime
import re
import io
import smtplib
from datetime import datetime
from functools import wraps
from flask import (
    Flask, request, jsonify, render_template, session,
    redirect, url_for, make_response, send_file
)
from werkzeug.utils import secure_filename
from openai import OpenAI
from email.mime.text import MIMEText
from utils import allowed_file, extract_text_from_file
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Optional: enable CORS in development to allow fetch from another origin
try:
    from flask_cors import CORS
    HAVE_FLASK_CORS = True
except Exception:
    HAVE_FLASK_CORS = False

# --- Load environment variables ---
load_dotenv()

# --- Flask setup ---
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "super-secret-key")  # change in production

# Enable CORS for dev if available
if HAVE_FLASK_CORS:
    CORS(app, supports_credentials=True)

# Limit upload size (default 16MB, configurable via env)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv("MAX_UPLOAD_BYTES", 16 * 1024 * 1024))

# --- OpenAI client (check API key) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable missing. Add it to .env before running.")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Upload folder ---
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- In-memory stores (dev only) ---
users = [
    {
        "id": 1,
        "name": "John Doe",
        "email": "john@example.com",
        "password": generate_password_hash("password"),  # hashed dev password
        "quizzes": []
    }
]
leaderboard = []

# --- Dev convenience: auto-login (toggle with AUTO_LOGIN env) ---
@app.before_request
def auto_login():
    if os.getenv("AUTO_LOGIN", "true").lower() == "true":
        if "user_id" not in session:
            session["user_id"] = 1

# --- Email sending helper ---
def send_welcome_email(user_email):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_from = os.getenv("EMAIL_FROM")
    if not (smtp_server and smtp_port and smtp_user and smtp_pass and email_from):
        print("SMTP not configured; skipping welcome email.")
        return
    msg = MIMEText("Welcome to Notes2Quiz! 🎉\n\nYour account is ready. Start uploading your notes and learning smarter!")
    msg['Subject'] = "Welcome to Notes2Quiz!"
    msg['From'] = email_from
    msg['To'] = user_email
    try:
        with smtplib.SMTP(smtp_server, int(smtp_port), timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        print("Error sending welcome email:", e)

# --- Utility: clean AI summary output ---
def clean_summary(text):
    text = re.sub(r"[*#]+", "", text)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

# --- Quiz generation using OpenAI (robust parsing) ---
def generate_quiz_from_text(text, difficulty="Easy"):
    prompt = (
        f"Create 10 multiple-choice questions from the following study notes. "
        f"Return ONLY valid JSON in this exact format: "
        f'[{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "answer": "B"}}]. '
        f"No explanations, no extra text, only JSON.\n\n"
        f"Difficulty: {difficulty}.\n\nNotes:\n{text}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert teacher creating multiple-choice quizzes."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1200,
            temperature=0.3
        )
    except Exception as e:
        raise RuntimeError(f"OpenAI request failed: {e}")

    quiz_text = resp.choices[0].message.content.strip()
    cleaned_text = re.sub(r"```(?:json)?|```", "", quiz_text).strip()
    try:
        return {"questions": json.loads(cleaned_text)}
    except json.JSONDecodeError:
        json_match = re.search(r"\[.*\]", cleaned_text, re.DOTALL)
        if json_match:
            try:
                return {"questions": json.loads(json_match.group(0))}
            except json.JSONDecodeError:
                pass
        return parse_quiz_text_fallback(cleaned_text)

def parse_quiz_text_fallback(quiz_text):
    questions = []
    lines = [l.strip() for l in quiz_text.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lower().startswith('q') and '.' in line:
            q_text = line.split('.', 1)[1].strip()
            opts = {}
            i += 1
            for _ in range(4):
                if i >= len(lines):
                    break
                part = lines[i]
                if len(part) >= 2 and part[0] in ['A', 'B', 'C', 'D']:
                    opts[part[0]] = part[2:].strip() if len(part) > 2 else ""
                    i += 1
                else:
                    break
            answer = None
            if i < len(lines) and lines[i].lower().startswith('answer'):
                if ':' in lines[i]:
                    answer = lines[i].split(':', 1)[1].strip().split()[0]
                i += 1
            questions.append({"question": q_text, "options": opts, "answer": answer or ''})
        else:
            i += 1
    return {"questions": questions}

# --- Helper: require login decorator ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

# =====================
# ROUTES
# =====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route("/quiz.html")
def quiz_page():
    return render_template("quiz.html")

@app.route('/signup_page')
def signup_page():
    return render_template('signup.html')

@app.route('/login_page')
def login_page():
    return render_template('login.html')

@app.route('/flashcards_page')
def flashcards_page():
    return render_template('flashcards.html')

# ---- AUTH ----
@app.route('/signup', methods=['POST'])
def signup():
    # support JSON fetch and form POST
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    email = (data.get("email") or "").strip()
    name = (data.get("name") or data.get("username") or "New User").strip()
    password = data.get("password") or data.get("pwd") or ""

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password required"}), 400

    if any(u['email'].lower() == email.lower() for u in users):
        return jsonify({"success": False, "message": "Email already registered"}), 400

    new_user = {
        "id": max((u['id'] for u in users), default=0) + 1,
        "name": name,
        "email": email,
        "password": generate_password_hash(password),
        "quizzes": []
    }
    users.append(new_user)

    session["user_id"] = new_user["id"]
    session["user_name"] = new_user["name"]

    try:
        send_welcome_email(email)
    except Exception as e:
        print("Failed to send welcome email:", e)

    return jsonify({
        "success": True,
        "message": "Signup successful. Welcome email sent.",
        "user": {"id": new_user['id'], "name": name, "email": email}
    }), 200

@app.route('/login', methods=['POST'])
def login():
    # support JSON fetch and form POST
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password required"}), 400

    user = next((u for u in users if u["email"].lower() == email.lower()), None)
    if not user or not check_password_hash(user.get("password", ""), password):
        return jsonify({"success": False, "message": "Invalid email or password"}), 401

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]

    return jsonify({
        "success": True,
        "message": "Login successful",
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]}
    }), 200

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out"}), 200

@app.route('/me', methods=['GET'])
def me():
    user = next((u for u in users if u["id"] == session.get("user_id")), None)
    if not user:
        return jsonify({"user": None})
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"]}})
















@app.route("/api/quiz")
def api_quiz():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    
    user = next((u for u in users if u["id"] == user_id), None)
    if not user or not user.get("quizzes"):
        return jsonify({"questions": []})  # no quiz yet
    
    # Get the latest quiz for the user
    latest_quiz = user["quizzes"][-1]
    return jsonify({"questions": latest_quiz["questions"]})





# ---- Dashboard (protected) ----
@app.route('/dashboard', methods=['GET'])
@login_required
def dashboard():
    # If API client requests JSON, return quizzes, else render HTML
    user = next((u for u in users if u["id"] == session.get("user_id")), None)
    if not user:
        return redirect(url_for('login_page'))

    if 'application/json' in request.headers.get('Accept', '') or request.args.get('format') == 'json':
        return jsonify({"quizzes": user.get("quizzes", [])})
    return render_template('dashboard.html', user={"id": user["id"], "name": user["name"], "email": user["email"]})

# ---- Quiz endpoints ----
@app.route('/generate_quiz', methods=['POST'])
def generate_quiz():
    data = request.get_json() or {}
    summary = data.get("summary")
    difficulty = data.get("difficulty", "Easy")
    if not summary:
        return jsonify({"error": "Summary required"}), 400
    try:
        quiz = generate_quiz_from_text(summary, difficulty)
    except Exception as e:
        return jsonify({"error": f"Failed to generate quiz: {e}"}), 500
    return jsonify({"quiz": quiz})

@app.route('/save_quiz', methods=['POST'])
def save_quiz():
    user = next((u for u in users if u["id"] == session.get("user_id")), None)
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    data = request.get_json() or {}
    score = data.get("score")
    total = data.get("total")
    questions = data.get("questions")

    try:
        score = int(score)
        total = int(total)
    except Exception:
        return jsonify({"error": "Invalid score or total"}), 400

    quiz_record = {
        "id": datetime.now().timestamp(),
        "score": score,
        "total": total,
        "questions": questions,
        "date": datetime.now().isoformat()
    }
    user["quizzes"].append(quiz_record)
    leaderboard.append({
        "name": user["name"],
        "score": score,
        "total": total,
        "date": quiz_record["date"]
    })
    return jsonify({"message": "Quiz saved successfully", "quiz": quiz_record}), 200

@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    sorted_board = sorted(leaderboard, key=lambda x: (x["score"], x["date"]), reverse=True)
    return jsonify({"leaderboard": sorted_board[:20]})

# ---- Explanations / batch explanations ----
@app.route('/explain_answer', methods=['POST'])
def explain_answer():
    data = request.get_json() or {}
    question = data.get("question")
    correct = data.get("correct")
    chosen = data.get("chosen")
    explanation = f"The correct answer is {correct} because this concept is fundamental to the question: {question}"
    return jsonify({"explanation": explanation})

@app.route('/batch_explanations', methods=['POST'])
def batch_explanations():
    data = request.get_json() or {}
    wrong_answers = data.get("wrongAnswers", [])
    explanations = []
    for item in wrong_answers:
        question = item.get("question")
        correct = item.get("correct")
        chosen = item.get("chosen")
        explanations.append({
            "question": question,
            "correct": correct,
            "chosen": chosen,
            "explanation": f"The correct answer is {correct} because this concept is fundamental to the question: {question}"
        })
    return jsonify({"explanations": explanations})

# ---- Save attempt (generic) ----
@app.route('/save_attempt', methods=['POST'])
def save_attempt():
    data = request.get_json() or {}
    print("📌 Quiz attempt saved:", data)
    return jsonify({"status": "success", "message": "Attempt saved successfully"})

# ---- Upload & summary ----
@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Only PDF, DOCX, and TXT are allowed."}), 400

    filename = secure_filename(file.filename)
    timestamp = int(datetime.now().timestamp())
    saved_filename = f"{timestamp}_{filename}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
    try:
        file.save(path)
    except Exception as e:
        return jsonify({"error": f"Failed to save file: {e}"}), 500

    try:
        content = extract_text_from_file(path, saved_filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Step 1: Generate summary
    summary_prompt = (
        "Summarize the following notes as clear, concise bullet points. "
        "Use plain hyphens (-) for bullets, keep each point short (max 20 words), "
        "and do not include headings, numbering, or extra text:\n\n"
        f"{content}:"
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant who summarizes text clearly."},
                {"role": "user", "content": summary_prompt}
            ],
            max_tokens=800,
            temperature=0.5
        )
        summary = clean_summary(resp.choices[0].message.content.strip())
    except Exception as e:
        return jsonify({"error": f"OpenAI summary request failed: {e}"}), 500

    # Step 2: Generate quiz from summary
    try:
        quiz_data = generate_quiz_from_text(summary)
    except Exception as e:
        return jsonify({"error": f"Failed to generate quiz: {e}"}), 500

    # Step 3: Save quiz to current user
    user_id = session.get("user_id")
    user = next((u for u in users if u["id"] == user_id), None)
    if user:
        quiz_record = {
            "id": datetime.now().timestamp(),
            "summary": summary,
            "questions": quiz_data["questions"],
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        user["quizzes"].append(quiz_record)

    # Step 4: Redirect to quiz page
    return redirect(url_for("quiz_page"))


# Example storage (replace with DB later)
user_quizzes = {
    # user_id: [ { "quiz_id": 1, "summary": "AI summary here...", "questions": [...], "score": 8, "total": 10, "date": "2025-08-10" } ]
}

@app.route("/download_summary/<quiz_id>")
def download_summary(quiz_id):
    user_id = session.get("user_id")
    if not user_id or user_id not in user_quizzes:
        return "Unauthorized", 401

    quiz = next((q for q in user_quizzes[user_id] if str(q["quiz_id"]) == quiz_id), None)
    if not quiz:
        return "Quiz not found", 404

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, "Notes Summary")
    p.setFont("Helvetica", 12)
    p.drawString(100, 720, quiz["summary"])
    p.showPage()
    p.save()

    buffer.seek(0)
    filename = f"summary_quiz_{quiz_id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

@app.route("/download_quiz/<quiz_id>")
def download_quiz(quiz_id):
    user_id = session.get("user_id")
    if not user_id or user_id not in user_quizzes:
        return "Unauthorized", 401

    quiz = next((q for q in user_quizzes[user_id] if str(q["quiz_id"]) == quiz_id), None)
    if not quiz:
        return "Quiz not found", 404

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, f"Quiz Review - {quiz['date']}")
    p.setFont("Helvetica", 12)

    y = 720
    for i, q in enumerate(quiz["questions"], 1):
        p.drawString(100, y, f"Q{i}: {q['question']}")
        y -= 20
        p.drawString(120, y, f"Your answer: {q.get('user_answer', 'N/A')}")
        y -= 20
        p.drawString(120, y, f"Correct answer: {q['correct_answer']}")
        y -= 30
        if y < 50:  # New page if space is low
            p.showPage()
            y = 750

    p.showPage()
    p.save()

    buffer.seek(0)
    filename = f"quiz_review_{quiz_id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


# ---- Flashcards generation ----
@app.route('/generate_flashcards', methods=['POST'])
def generate_flashcards():
    data = request.get_json() or {}
    summary = data.get("summary", "")
    if not summary:
        return jsonify({"error": "No summary provided"}), 400

    prompt = f"""
    Create concise flashcards from the following text.
    Respond in JSON array format where each item has:
    - question (string)
    - answer (string)

    Text:
    {summary}
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        content = resp.choices[0].message.content.strip()
        cleaned = re.sub(r"```(?:json)?|```", "", content).strip()
        try:
            flashcards = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
            flashcards = json.loads(match.group(0)) if match else []
        return jsonify({"flashcards": flashcards})
    except Exception as e:
        print("Flashcards generation failed:", e)
        return jsonify({"error": "Failed to generate flashcards"}), 500

# --- Run app ---
if __name__ == "__main__":
    app.run(debug=True)
