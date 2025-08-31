document.addEventListener("DOMContentLoaded", () => {
  let currentUser = null;

  // === DOM elements ===
  const uploadForm = document.getElementById("uploadForm");
  const fileInput = document.getElementById("fileInput");
  const summaryText = document.getElementById("summaryText");
  const summarySection = document.getElementById("summarySection");
  const quizSection = document.getElementById("quizSection");
  const genQuizBtn = document.getElementById("genQuizBtn");
  const difficultySelect = document.getElementById("difficulty");
  const quizForm = document.getElementById("quizForm");
  const resultArea = document.getElementById("resultArea");
  const status = document.getElementById("status");
  const signupForm = document.getElementById("signupForm");
  const signupStatus = document.getElementById("signupStatus");

  // === Check current user info ===
  fetch("/me")
    .then(res => res.json())
    .then(data => {
      currentUser = data.user || null;
      console.log("Logged in user:", currentUser);

      // Redirect if user is NOT logged in and we are on dashboard
      if (!currentUser && window.location.pathname === "/dashboard") {
        window.location.href = "/login";
      }
    })
    .catch(() => {
      currentUser = null;
      if (window.location.pathname === "/dashboard") {
        window.location.href = "/login";
      }
    });

  function setStatus(msg, isError = false) {
    status.textContent = msg;
    status.style.color = isError ? "crimson" : "green";
  }

  function smoothScrollTo(el) {
    el.scrollIntoView({ behavior: "smooth" });
  }

  function cleanSummaryText(text) {
    return text.replace(/[*#]/g, "").trim();
  }

  // === File Preview ===
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) setStatus(`Selected: ${file.name}`);
  });

  // === Upload Notes ===
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    if (!file) return setStatus("Select a file first", true);

    setStatus("Uploading and summarizing...");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) return setStatus(data.error || "Upload failed", true);

      summaryText.textContent = cleanSummaryText(data.summary);
      summarySection.classList.remove("hidden");
      quizSection.classList.remove("hidden");
      summarySection.dataset.summary = data.summary;

      setStatus("Summary ready. Generate a quiz when ready.");
      smoothScrollTo(summarySection);
    } catch (err) {
      setStatus("An error occurred while uploading.", true);
    }
  });

  // === Generate Quiz ===
  genQuizBtn.addEventListener("click", async () => {
    const summary = summarySection.dataset.summary;
    if (!summary) return setStatus("No summary available", true);

    setStatus("Generating quiz...");
    quizForm.innerHTML = `<div class="spinner"></div>`; // spinner

    try {
      const res = await fetch("/generate_quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          summary,
          difficulty: difficultySelect.value,
        }),
      });

      const data = await res.json();
      if (!res.ok) return setStatus(data.error || "Quiz generation failed", true);

      buildQuizUI(data.quiz.questions);
      setStatus("Quiz ready!");
      smoothScrollTo(quizSection);
    } catch (err) {
      setStatus("An error occurred while generating quiz.", true);
    }
  });

  function buildQuizUI(questions) {
    quizForm.innerHTML = "";
    questions.forEach((q, idx) => {
      const div = document.createElement("div");
      div.className = "question";
      div.innerHTML = `<p><strong>Q${idx + 1}:</strong> ${q.question}</p>`;
      for (const [letter, text] of Object.entries(q.options)) {
        div.innerHTML += `
          <label>
            <input type="radio" name="q${idx}" value="${letter}"> ${letter}) ${text}
          </label>
        `;
      }
      div.dataset.answer = q.answer;
      quizForm.appendChild(div);
    });

    const submitBtn = document.createElement("button");
    submitBtn.textContent = "Submit Quiz";
    submitBtn.type = "button";
    submitBtn.addEventListener("click", () => checkAnswers(questions));
    quizForm.appendChild(submitBtn);
  }

  function checkAnswers(questions) {
    let score = 0;
    questions.forEach((q, idx) => {
      const selected = document.querySelector(`input[name="q${idx}"]:checked`);
      if (selected && selected.value === q.answer) {
        score++;
      }
    });
    animateScore(score, questions.length);
    saveQuizResult(score, questions.length, questions); // auto-save after scoring
  }

  function animateScore(score, total) {
    resultArea.classList.remove("hidden");
    let current = 0;
    resultArea.innerHTML = "";

    const counter = document.createElement("h3");
    counter.textContent = "Score: 0";
    resultArea.appendChild(counter);

    const interval = setInterval(() => {
      counter.textContent = `Score: ${current} / ${total}`;
      if (current === score) {
        clearInterval(interval);
      } else {
        current++;
      }
    }, 100);
  }

  async function saveQuizResult(score, total, questions) {
    try {
      const res = await fetch("/save_quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ score, total, questions }),
      });

      const data = await res.json();
      if (!res.ok) {
        console.error("Error saving quiz:", data.error || "Unknown error");
      } else {
        console.log("Quiz saved successfully:", data);
      }
    } catch (err) {
      console.error("Network error while saving quiz:", err);
    }
  }

  // === Signup Form ===
  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    signupStatus.textContent = "Creating account...";
    signupStatus.style.color = "black";

    const payload = {
      name: document.getElementById("signupName").value,
      email: document.getElementById("signupEmail").value,
      password: document.getElementById("signupPassword").value,
    };

    try {
      const res = await fetch("/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        signupStatus.textContent = data.error || "Signup failed";
        signupStatus.style.color = "crimson";
        return;
      }

      signupStatus.textContent = "Account created! Check your email.";
      signupStatus.style.color = "green";
      signupForm.reset();
    } catch (err) {
      signupStatus.textContent = "An error occurred during signup.";
      signupStatus.style.color = "crimson";
    }
  });
});
