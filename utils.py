import os
import docx2txt
from PyPDF2 import PdfReader

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(path, filename):
    ext = filename.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        text = ""
        try:
            reader = PdfReader(path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            raise RuntimeError(f"PDF read error: {e}")
        return text
    elif ext == 'docx':
        try:
            text = docx2txt.process(path)
            return text or ""
        except Exception as e:
            raise RuntimeError(f"DOCX read error: {e}")
    elif ext == 'txt':
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    else:
        raise ValueError("Unsupported file type")
