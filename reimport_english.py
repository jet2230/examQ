
import requests
import os

BASE_URL = "http://localhost:5001"
ADMIN_USER = "admin"

qp_path = os.path.abspath("resources/igcse_edxcel_exampapers/english/2019 Jun/Question-paper/Questionpaper-Paper1-June2019.pdf")
ms_path = os.path.abspath("resources/igcse_edxcel_exampapers/english/2019 Jun/Mark-scheme/Markscheme-Paper1-June2019.pdf")
er_path = os.path.abspath("resources/igcse_edxcel_exampapers/english/2019 Jun/Examiner-report/Examinerreport-Paper1-June2019.pdf")

print(f"Re-importing: {qp_path}")
resp = requests.post(f"{BASE_URL}/api/admin/process-exam", json={
    "admin_username": ADMIN_USER,
    "qp_path": qp_path,
    "ms_path": ms_path,
    "er_path": er_path
}, timeout=600)

print(f"Status Code: {resp.status_code}")
try:
    print(resp.json())
except:
    print(resp.text)
