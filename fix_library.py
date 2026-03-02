
import os
import requests
import json
import sys

BASE_URL = "http://localhost:5001"
ADMIN_USER = "admin"
RESOURCES_DIR = "resources"
EXAM_DATA_DIR = "exam_data"

def log(msg):
    print(msg, flush=True)

def get_all_pdfs():
    pdfs = []
    for root, _, files in os.walk(RESOURCES_DIR):
        for f in files:
            if f.endswith(".pdf"):
                pdfs.append(os.path.join(root, f))
    return pdfs

def get_clean_base(path):
    filename = os.path.basename(path).lower()
    base = filename.replace("questionpaper-", "").replace("markscheme-", "").replace("examinerreport-", "") \
                   .replace("msc-", "").replace(".pdf", "").replace(" ", "").replace("-", "").replace("_", "").replace(".", "") \
                   .replace("biology", "").replace("english", "").replace("science", "").replace("doubleaward", "")
    return base

def is_qp(filename):
    n = filename.lower()
    if "markscheme" in n or "msc" in n or "report" in n or "ms.pdf" in n or "er.pdf" in n:
        return False
    return True

def fix_library():
    log("🚀 Starting Targeted Library Refresh...")
    
    all_pdfs = get_all_pdfs()
    log(f"Found {len(all_pdfs)} total PDFs.")
    
    qps = [p for p in all_pdfs if is_qp(os.path.basename(p))]
    log(f"Found {len(qps)} potential Question Papers.")

    # Prioritize English papers as requested
    english_qps = [p for p in qps if "english" in p.lower()]
    other_qps = [p for p in qps if "english" not in p.lower()]
    
    target_qps = english_qps + other_qps
    log(f"Processing {len(target_qps)} papers (English first)...")

    for qp_path in target_qps:
        qp_name = os.path.basename(qp_path)
        parent = os.path.dirname(qp_path)
        qp_base = get_clean_base(qp_path)
        
        match_ms = None
        match_er = ""
        
        search_dirs = [parent]
        if "Question-paper" in parent:
            search_dirs.append(parent.replace("Question-paper", "Mark-scheme"))
            search_dirs.append(parent.replace("Question-paper", "Examiner-report"))

        for s_dir in search_dirs:
            if not os.path.exists(s_dir): continue
            for f in os.listdir(s_dir):
                if not f.endswith(".pdf"): continue
                f_path = os.path.join(s_dir, f)
                if f_path == qp_path: continue
                if get_clean_base(f) == qp_base:
                    low = f.lower()
                    if "ms" in low or "markscheme" in low or "msc" in low: match_ms = f_path
                    elif "er" in low or "report" in low or "examiner" in low: match_er = f_path

        if match_ms:
            log(f"🔄 Importing: {qp_name}")
            try:
                # Use a shorter timeout per request so we don't hang forever if one fails
                resp = requests.post(f"{BASE_URL}/api/admin/process-exam", json={
                    "admin_username": ADMIN_USER,
                    "qp_path": os.path.abspath(qp_path),
                    "ms_path": os.path.abspath(match_ms),
                    "er_path": os.path.abspath(match_er) if match_er else ""
                }, timeout=600) 
                log(f"  ✅ Result: {resp.status_code}")
            except Exception as e:
                log(f"  ❌ Error processing {qp_name}: {str(e)}")
        else:
            log(f"  ⚠️ No MS found for {qp_name}")

if __name__ == "__main__":
    fix_library()
