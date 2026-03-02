
import requests
import json
import os
import sqlite3
from pdf2image import convert_from_path
import pytesseract

def extract_text_from_pdf(path):
    print(f"  Extracting text from {os.path.basename(path)}...")
    images = convert_from_path(path, dpi=150)
    page_texts = [pytesseract.image_to_string(img) for img in images]
    return page_texts, images

def import_paper(qp_path, ms_path, subject, paper_id, title):
    # Step 1: Clean up any previous partial imports
    print(f"Cleaning up previous data for {paper_id}...")
    conn = sqlite3.connect('quizzes.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM official_exams WHERE id = ?", (paper_id,))
    conn.commit()
    conn.close()
    if os.path.exists(f"exam_data/{paper_id}.json"):
        os.remove(f"exam_data/{paper_id}.json")
    if os.path.exists(f"static/exams/{paper_id}"):
        import shutil
        shutil.rmtree(f"static/exams/{paper_id}")

    # Step 2: Extract text and get images
    qp_pages_text, qp_images = extract_text_from_pdf(qp_path)
    ms_pages_text, _ = extract_text_from_pdf(ms_path)
    ms_text = "\\n".join(ms_pages_text)
    
    all_questions_map = {}

    # Step 3: Iterate page by page
    for i, page_content in enumerate(qp_pages_text):
        page_num = i + 1
        print(f"  Scanning Page {page_num}/{len(qp_pages_text)}...")

        page_prompt = f"""Analyze Page {page_num} of an IGCSE paper. Find any questions starting on this page.
PAGE TEXT: {page_content}
FULL MARK SCHEME: {ms_text}
Return a JSON list of question objects or an empty list []."""
        
        try:
            page_resp = requests.post('http://localhost:11434/api/generate', json={
                'model': 'llama3', 'prompt': page_prompt, 'stream': False, 'format': 'json'
            }, timeout=300)
            
            page_q_list = json.loads(page_resp.json().get('response', '[]'))
            for q_data in page_q_list:
                if 'id' not in q_data or 'sub_questions' not in q_data: continue
                q_id = q_data['id']
                if q_id not in all_questions_map:
                    all_questions_map[q_id] = q_data
                else:
                    all_questions_map[q_id]['sub_questions'].extend(q_data['sub_questions'])
        except Exception as e:
            print(f"  Warning: AI mapping failed for page {page_num}. Error: {e}")

    # Step 4: Save images
    print("  Saving images...")
    qp_img_dir = f"static/exams/{paper_id}/qp"
    os.makedirs(qp_img_dir, exist_ok=True)
    for i, image in enumerate(qp_images):
        image.save(os.path.join(qp_img_dir, f"page_{i+1:02d}.png"), 'PNG')

    # Step 5: Assemble and save final JSON
    final_questions = sorted(all_questions_map.values(), key=lambda q: q['id'])
    final_json = {
        "paper_id": paper_id,
        "title": title,
        "subject": subject,
        "qp_img_dir": f"/{qp_img_dir}/",
        "extract_pages": [],
        "questions": final_questions
    }

    json_path = f"exam_data/{paper_id}.json"
    with open(json_path, 'w') as f:
        json.dump(final_json, f, indent=2)

    # Step 6: Add to database
    conn = sqlite3.connect('quizzes.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO official_exams (id, title, subject, paper, date, data_json_path) VALUES (?, ?, ?, ?, ?, ?)', 
                   (paper_id, title, subject, '1B', 'Nov 2025', json_path))
    conn.commit()
    conn.close()

    print(f"\n✅ Import complete for {paper_id}!")

if __name__ == '__main__':
    import_paper(
        "resources/igcse_edxcel_exampapers/biology/29. Nov 2025 Biology-1B QP.pdf",
        "resources/igcse_edxcel_exampapers/biology/29. Nov 2025 Biology-1B MS.pdf",
        "Biology",
        "Biology_Nov_2025_1B",
        "Pearson Edexcel International GCSE (9-1) Biology Paper 1B - Nov 2025"
    )
