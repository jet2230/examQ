
import os
import requests
import time

BASE_URL = "http://localhost:5001"
ADMIN_USER = "admin"

def process_paper(qp, ms, er, subject, paper_id):
    print(f"🔄 Processing [{subject}] {paper_id}...")
    try:
        resp = requests.post(f"{BASE_URL}/api/admin/process-exam", json={
            "admin_username": ADMIN_USER,
            "qp_path": os.path.abspath(qp),
            "ms_path": os.path.abspath(ms),
            "er_path": os.path.abspath(er) if er else "",
            "subject": subject,
            "id": paper_id
        }, timeout=600)
        if resp.status_code == 200:
            print(f"  ✅ Success: {resp.json().get('message')}")
        else:
            print(f"  ❌ Failed: {resp.text}")
    except Exception as e:
        print(f"  ❌ Error: {str(e)}")

def run_import():
    # 1. Biology Papers
    bio_dir = "resources/igcse_edxcel_exampapers/biology"
    bio_files = os.listdir(bio_dir)
    
    # Match QP/MS pairs for Biology
    # Format: "X. 1B-Jan 2012.pdf" and "X. 1B-msc-Jan 2012.pdf"
    # Or: "29. Nov 2025 Biology-1B QP.pdf" and "29. Nov 2025 Biology-1B MS.pdf"
    
    qps = []
    for f in bio_files:
        if not f.endswith(".pdf"): continue
        if "msc" in f.lower() or "ms.pdf" in f.lower() or "report" in f.lower(): continue
        qps.append(f)
        
    for qp in qps:
        base = qp.replace(".pdf", "")
        # Find MS
        ms = None
        if "QP" in qp:
            ms = qp.replace("QP.pdf", "MS.pdf")
        else:
            # "1. 1B-Jan 2012.pdf" -> "1. 1B-msc-Jan 2012.pdf"
            parts = qp.split("-")
            if len(parts) > 1:
                ms = parts[0] + "-msc-" + "-".join(parts[1:])
            else:
                # Fallback for papers like "1. 1B-Jan 2012.pdf" where split might be different
                ms = qp.replace("1B-", "1B-msc-").replace("2B-", "2B-msc-")
        
        if ms and os.path.exists(os.path.join(bio_dir, ms)):
            paper_id = "Biology_" + base.replace(" ", "_").replace(".", "").replace("-", "_")
            process_paper(os.path.join(bio_dir, qp), os.path.join(bio_dir, ms), None, "Biology", paper_id)
        else:
            print(f"  ⚠️ No MS found for Biology paper: {qp} (tried {ms})")

    # 2. English Papers
    eng_dir = "resources/igcse_edxcel_exampapers/english/2019 Jun"
    eng_qp_dir = os.path.join(eng_dir, "Question-paper")
    eng_ms_dir = os.path.join(eng_dir, "Mark-scheme")
    eng_er_dir = os.path.join(eng_dir, "Examiner-report")
    
    for qp in os.listdir(eng_qp_dir):
        if not qp.endswith(".pdf"): continue
        ms = qp.replace("Questionpaper", "Markscheme")
        er = qp.replace("Questionpaper", "Examinerreport")
        
        paper_id = "English_" + qp.replace(".pdf", "").replace("-", "_")
        process_paper(
            os.path.join(eng_qp_dir, qp), 
            os.path.join(eng_ms_dir, ms), 
            os.path.join(eng_er_dir, er), 
            "English", 
            paper_id
        )

if __name__ == "__main__":
    run_import()
