
import os
import requests

BASE_URL = "http://localhost:5001"
ADMIN_USER = "admin"

def process(qp, ms, er, subject, paper_id):
    print(f"🚀 Importing [{subject}] {paper_id}...")
    payload = {
        "admin_username": ADMIN_USER,
        "qp_path": os.path.abspath(qp),
        "ms_path": os.path.abspath(ms),
        "er_path": os.path.abspath(er) if er else "",
        "subject": subject,
        "id": paper_id
    }
    resp = requests.post(f"{BASE_URL}/api/admin/process-exam", json=payload, timeout=600)
    print(f"  Result: {resp.status_code} - {resp.json().get('message')}")

# 1. Biology Perfect Sample
process(
    "resources/igcse_edxcel_exampapers/biology/29. Nov 2025 Biology-1B QP.pdf",
    "resources/igcse_edxcel_exampapers/biology/29. Nov 2025 Biology-1B MS.pdf",
    None,
    "Biology",
    "Biology_Nov_2025_1B"
)

# 2. English Perfect Sample
process(
    "resources/igcse_edxcel_exampapers/english/2019 Jun/Question-paper/Questionpaper-Paper1-June2019.pdf",
    "resources/igcse_edxcel_exampapers/english/2019 Jun/Mark-scheme/Markscheme-Paper1-June2019.pdf",
    "resources/igcse_edxcel_exampapers/english/2019 Jun/Examiner-report/Examinerreport-Paper1-June2019.pdf",
    "English",
    "English_June_2019_Paper_1"
)
