#!/usr/bin/env python3
"""
Manual import script for English June 2024 Paper
Bypasses the admin UI to directly call the backend API
"""

import requests
import json
import uuid
import time
import subprocess
import re

BASE_URL = "http://localhost:5001"
API_PREFIX = f"{BASE_URL}/api"

# File paths
QP_PATH = "/home/obo/playground/examQ/resources/igcse_edxcel_exampapers/english/8. June 2024 -que-RECYCLE.pdf"
MS_PATH = "/home/obo/playground/examQ/resources/igcse_edxcel_exampapers/english/8 .June 2024  rms-RECYCLE.pdf"
ER_PATH = "/home/obo/playground/examQ/resources/igcse_edxcel_exampapers/english/8. June 2024 Exam Report.pdf"

def extract_pdf_text(filepath, timeout=120):
    """Extract text from PDF using pdftotext with timeout"""
    try:
        res = subprocess.run(['pdftotext', '-layout', filepath, '-'], capture_output=True, text=True, check=True, timeout=timeout)
        pages = res.stdout.split('\f')
        return pages
    except subprocess.TimeoutExpired as e:
        print(f"  ⚠️  PDF extraction timeout after {timeout}s")
        return []
    except Exception as e:
        if isinstance(e, subprocess.TimeoutExpired):
            print(f"  ⚠️  PDF extraction timeout")
        return []

def detect_reading_booklet(pages):
    """
    Detect reading booklet/source booklet pages in English papers.
    Reading booklets typically start with a header page and contain source texts.
    Returns pages with actual reading passages (excludes info/header page and trailing blank pages).
    """
    if len(pages) < 5:
        return []

    # Helper function to find end of reading passages (stop before blank pages)
    def find_end(pages, start_idx):
        end = start_idx
        for i in range(start_idx, len(pages)):
            if pages[i].strip():
                end = i + 1
            else:
                break
        return end

    # Strategy 1: Look for "Do not return this booklet" - unique to source booklet header
    for i, page in enumerate(pages):
        page_lower = page.lower()
        if 'do not return this booklet' in page_lower:
            if i + 1 < len(pages):
                next_page = pages[i + 1].lower()
                if 'text one' in next_page or 'text two' in next_page:
                    end = find_end(pages, i + 2)
                    return list(range(i + 2, end))

    # Strategy 2: Look for "Source Booklet" header with "Turn over"
    for i, page in enumerate(pages):
        page_lower = page.lower()
        lines = page.split('\n')
        source_idx = -1
        for j, line in enumerate(lines):
            if 'source booklet' in line.lower():
                source_idx = j
                break
        if source_idx >= 0:
            for j in range(source_idx + 1, len(lines)):
                if lines[j].strip() == '' and j + 1 < len(lines) and 'turn over' in lines[j + 1].lower():
                    if i + 1 < len(pages):
                        next_page = pages[i + 1].lower()
                        if 'text one' in next_page or 'text two' in next_page:
                            end = find_end(pages, i + 2)
                            return list(range(i + 2, end))

    # Strategy 3: Look for "Paper reference" + "English Language B" + "Source Booklet"
    for i, page in enumerate(pages):
        page_lower = page.lower()
        if 'paper reference' in page_lower and 'english language b' in page_lower and 'source booklet' in page_lower:
            if i + 1 < len(pages):
                next_page = pages[i + 1].lower()
                if 'text one' in next_page or 'text two' in next_page:
                    end = find_end(pages, i + 2)
                    return list(range(i + 2, end))

    # Strategy 4: Look for "Text One" at start of page (after blank lines)
    for i, page in enumerate(pages):
        lines = page.split('\n')
        for j, line in enumerate(lines):
            stripped = line.strip()
            if stripped.lower().startswith('text one') or stripped.lower().startswith('text two'):
                if j >= 2:
                    prev_blank = all(lines[k].strip() == '' for k in range(j-1, max(0, j-3), -1))
                    if prev_blank:
                        start = i + 1
                        end = find_end(pages, start)
                        return list(range(start, end))
                elif j < 10:
                    start = i + 1
                    end = find_end(pages, start)
                    return list(range(start, end))

    return []

def check_server():
    """Check if server is running"""
    try:
        resp = requests.get(f"{API_PREFIX}/health", timeout=5)
        print(f"✓ Server is running: {resp.status_code}")
        return True
    except requests.exceptions.ConnectionError:
        print("✗ Server not running. Starting it...")
        import subprocess
        subprocess.run(["bash", "./start_servers.sh"], check=True)
        time.sleep(3)
        try:
            resp = requests.get(f"{API_PREFIX}/health", timeout=5)
            print(f"✓ Server started successfully: {resp.status_code}")
            return True
        except:
            print("✗ Failed to start server")
            return False

def main():
    print("\n" + "="*60)
    print("Importing English June 2024 Paper")
    print("="*60 + "\n")

    # Check server
    if not check_server():
        return False

    # Generate unique ID for this exam
    paper_id = str(uuid.uuid4())[:8]
    print(f"Paper ID: {paper_id}")

    # Prepare metadata matching the existing structure
    metadata = {
        "title": "Pearson Edexcel International GCSE English Language Paper 1 - June 2024",
        "subject": "English",
        "paper": "1",
        "date": "June 2024",
        "id": paper_id
    }

    # Call the import API
    print("\nCalling /api/admin/process-exam...")
    payload = {
        "admin_username": "admin",  # Will be validated by server
        "qp_path": QP_PATH,
        "ms_path": MS_PATH,
        "er_path": ER_PATH
    }

    resp = requests.post(f"{API_PREFIX}/admin/process-exam", json=payload, timeout=30)
    if resp.status_code != 202:
        print(f"✗ Import failed: {resp.text}")
        return False

    result = resp.json()
    job_id = result.get('job_id')
    print(f"✓ Import started with job_id: {job_id}")

    # Poll for progress
    print("\nMonitoring import progress...")
    max_wait = 300  # 5 minutes max
    elapsed = 0

    while elapsed < max_wait:
        time.sleep(2)
        elapsed += 2

        resp = requests.get(f"{API_PREFIX}/admin/import-progress?job_id={job_id}", timeout=5)
        data = resp.json()

        status = data.get('status', '')
        print(f"  Status: {status}", end='\r')

        if status == 'extracting_text':
            print(f"  Extracting text from PDFs...")
        elif status == 'mapping':
            print(f"  Mapping questions: {data.get('current_page', 0)}/{data.get('total_pages', 0)} pages", end='\r')
        elif status == 'images':
            print(f"  Processing images...")
        elif status == 'completed':
            print(f"\n✓ Import completed successfully!")
            print(f"\nExported files:")
            print(f"  - JSON: exam_data/{paper_id}.json")
            print(f"  - Images: static/exams/{paper_id}/qp/")
            print(f"  - Database: official_exams table updated")

            # Post-process: Detect and add reading booklet pages
            try:
                print(f"\n[POST-PROCESS] Detecting reading booklet...")
                pdf_pages = extract_pdf_text(QP_PATH)
                extract_pages = detect_reading_booklet(pdf_pages)
                if extract_pages:
                    print(f"  ✓ Reading booklet detected: pages {extract_pages}")
                    # Update JSON file
                    json_path = f"exam_data/{paper_id}.json"
                    with open(json_path, 'r') as f:
                        exam_data = json.load(f)
                    exam_data['extract_pages'] = extract_pages
                    with open(json_path, 'w') as f:
                        json.dump(exam_data, f, indent=2)
                    print(f"  ✓ Updated {json_path} with extract_pages")
                else:
                    print(f"  ℹ️  No reading booklet detected (paper may not have one)")
            except Exception as e:
                print(f"  ⚠️  Could not detect reading booklet: {e}")

            return True
        elif status == 'failed':
            print(f"\n✗ Import failed: {data.get('error', 'Unknown error')}")
            return False

    print(f"\n⚠️  Timeout after {max_wait}s. Import may still be in progress.")

    # Final status check
    resp = requests.get(f"{API_PREFIX}/admin/import-progress?job_id={job_id}")
    print(f"  Final status: {resp.json().get('status', 'unknown')}")

    return False

if __name__ == "__main__":
    main()
