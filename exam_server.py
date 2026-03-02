#!/usr/bin/env python3
"""
Quiz Server with User Management
Handles user authentication, quiz generation, and result tracking
"""

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import sqlite3
from datetime import datetime
import PyPDF2
from pdf2image import convert_from_path
import pytesseract
import threading
import uuid
import re
import shutil

app = Flask(__name__)
CORS(app)

# Configuration
DATABASE = 'quizzes.db'
QUIZ_RESULTS_DIR = 'results'
RESOURCES_BASE = '/home/obo/playground/examQ/resources/igcse_edxcel_exampapers'
OLLAMA_API = "http://localhost:11434/api/generate"

# Global state for background import jobs
import_jobs = {}

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT DEFAULT 'student',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Check if created_at column exists (for older databases)
    cursor.execute("PRAGMA table_info(users)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'created_at' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT '2026-03-02 15:30:00'")
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS official_exams (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL, 
            paper TEXT NOT NULL, date TEXT NOT NULL, data_json_path TEXT NOT NULL, 
            er_text TEXT, source_path TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, paper_id TEXT, 
            current_question_idx INTEGER DEFAULT 0, answers_json TEXT, 
            status TEXT DEFAULT 'in_progress', last_updated DATETIME DEFAULT CURRENT_TIMESTAMP, 
            UNIQUE(username, paper_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, quiz_data_json TEXT, 
            answers_json TEXT, score INTEGER, total_marks INTEGER, 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    # New table for saved quizzes (AI generated)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, quiz_json TEXT, 
            created_by TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            username TEXT PRIMARY KEY, theme_json TEXT, ui_state_json TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', 'pass123', 'admin')")
    conn.commit()
    conn.close()

import subprocess

def extract_pdf_text(filepath):
    # Try pdftotext first (most reliable for text-layer PDFs)
    try:
        res = subprocess.run(['pdftotext', '-layout', filepath, '-'], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            # pdftotext uses \f (form feed) for page breaks
            pages = res.stdout.split('\f')
            if len(pages) > 1 or len(pages[0]) > 100:
                return "\n---PAGE BREAK---\n".join(pages)
    except:
        pass

    # Fallback to Tesseract (OCR)
    try:
        images = convert_from_path(filepath, dpi=200)
        text_pages = [pytesseract.image_to_string(img) for img in images]
        return "\n---PAGE BREAK---\n".join(text_pages)
    except Exception as e:
        print(f"OCR Error: {e}")
        try:
            with open(filepath, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = [p.extract_text() for p in reader.pages]
                return "\n---PAGE BREAK---\n".join(text)
        except:
            return ""

def load_users():
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT username, password, role FROM users")
    users = {row['username']: {'password': row['password'], 'role': row['role']} for row in cursor.fetchall()}
    conn.close(); return users

def clean_ai_json(text):
    """Robustly extract JSON from AI response"""
    try:
        # 1. Try to find any JSON list
        match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
        if match: return json.loads(match.group(0))

        # 2. Try to find any JSON object
        match = re.search(r'\{\s*".*"\s*:.*\}', text, re.DOTALL)
        if match: return json.loads(match.group(0))

        # 3. Simple list of strings match
        match = re.search(r'\[\s*".*"\s*\]', text, re.DOTALL)
        if match: return json.loads(match.group(0))

        return json.loads(text)
    except:
        return None

# --- API ROUTES ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    users = load_users()
    u, p = data.get('username'), data.get('password')
    if u in users and users[u]['password'] == p:
        return jsonify({'success': True, 'username': u, 'role': users[u].get('role', 'student')}), 200
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'}), 200

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    u, p = data.get('username'), data.get('password')
    if not u or not p: return jsonify({'success': False}), 400
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (u, p))
        conn.commit(); conn.close(); return jsonify({'success': True}), 201
    except: return jsonify({'success': False}), 400

@app.route('/api/verify-admin', methods=['POST'])
def verify_admin():
    data = request.json
    username = data.get('username')
    users = load_users()
    if username in users and users[username].get('role') == 'admin':
        return jsonify({'success': True}), 200
    return jsonify({'success': False}), 200

@app.route('/api/admin/users', methods=['POST'])
def admin_get_users():
    data = request.json
    admin_username = data.get('admin_username')
    
    # Simple check for admin role
    users_data = load_users()
    if admin_username not in users_data or users_data[admin_username].get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get all users with their quiz count
        cursor.execute('''
            SELECT u.username, u.role, u.created_at, 
                   (SELECT COUNT(*) FROM quiz_results r WHERE r.username = u.username) as quizzes_taken
            FROM users u
            ORDER BY u.created_at DESC
        ''')
        
        users_list = {}
        for row in cursor.fetchall():
            users_list[row['username']] = {
                'role': row['role'],
                'created_at': row['created_at'],
                'quizzes_taken': row['quizzes_taken']
            }
        
        conn.close()
        return jsonify({'success': True, 'users': users_list})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/update-user', methods=['POST'])
def admin_update_user():
    data = request.json
    admin_username = data.get('admin_username')
    
    # Simple check for admin role
    users_data = load_users()
    if admin_username not in users_data or users_data[admin_username].get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    old_username = data.get('old_username')
    new_username = data.get('new_username')
    new_password = data.get('new_password')
    
    if not old_username:
        return jsonify({'success': False, 'message': 'Missing old_username'}), 400
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE username = ?", (old_username,))
        if not cursor.fetchone():
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Update username if provided
        if new_username and new_username != old_username:
            # Check if new username already exists
            cursor.execute("SELECT * FROM users WHERE username = ?", (new_username,))
            if cursor.fetchone():
                return jsonify({'success': False, 'message': 'New username already exists'}), 400
            
            cursor.execute("UPDATE users SET username = ? WHERE username = ?", (new_username, old_username))
            # Also update quiz results and exam progress to maintain consistency
            cursor.execute("UPDATE quiz_results SET username = ? WHERE username = ?", (new_username, old_username))
            cursor.execute("UPDATE exam_progress SET username = ? WHERE username = ?", (new_username, old_username))
            cursor.execute("UPDATE saved_quizzes SET created_by = ? WHERE created_by = ?", (new_username, old_username))
            
            # Use new_username for password update if also provided
            target_username = new_username
        else:
            target_username = old_username
            
        # Update password if provided
        if new_password:
            cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, target_username))
            
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/list-folders')
def list_resource_folders():
    try:
        folders = [f for f in os.listdir(RESOURCES_BASE) if os.path.isdir(os.path.join(RESOURCES_BASE, f))]
        return jsonify({'success': True, 'folders': sorted(folders)})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/admin/list-files', methods=['POST'])
def list_server_files():
    try:
        data = request.json
        target_dir = os.path.join(RESOURCES_BASE, data.get('folder_name', ''))
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT source_path FROM official_exams"); imported = [row['source_path'] for row in cursor.fetchall()]; conn.close()
        files = []
        for root, _, filenames in os.walk(target_dir):
            for f in filenames:
                if f.lower().endswith('.pdf'):
                    path = os.path.abspath(os.path.join(root, f))
                    y = re.search(r'(20\d{2}|19\d{2})', f)
                    files.append({
                        'name': f, 'path': path, 'rel_path': os.path.relpath(path, target_dir),
                        'size': f"{os.path.getsize(path)/1024/1024:.2f} MB",
                        'is_imported': path in imported, 'year': int(y.group(1)) if y else 0
                    })
        return jsonify({'success': True, 'files': sorted(files, key=lambda x: (x['year'], x['name']), reverse=True)})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/admin/import-progress')
def get_import_progress():
    job_id = request.args.get('job_id')
    return jsonify(import_jobs.get(job_id, {'status': 'not_found'})), (200 if job_id in import_jobs else 404)

@app.route('/api/generate-quiz', methods=['POST'])
def generate_quiz_api():
    """Generate a quiz using Ollama and save it"""
    try:
        data = request.json
        topic = data.get('topic')
        num = data.get('num_questions', 10)
        username = data.get('username')

        prompt = f"""Create a multiple-choice quiz about: {topic}.
Number of questions: {num}.
For each question, provide 4 options (A, B, C, D) and identify the correct letter.

Return ONLY a JSON list of objects:
[
  {{
    "question": "...",
    "options": ["option 1", "option 2", "option 3", "option 4"],
    "answer": "A/B/C/D"
  }}
]"""

        # Call Ollama
        response = requests.post(OLLAMA_API, json={
            'model': 'llama3',
            'prompt': prompt,
            'stream': False,
            'format': 'json'
        }, timeout=120)
        
        if response.status_code != 200:
            return jsonify({'success': False, 'error': 'AI model failed'}), 500
            
        quiz_json_raw = response.json().get('response', '[]')
        questions = clean_ai_json(quiz_json_raw)
        
        if not questions:
            return jsonify({'success': False, 'error': 'Failed to parse AI response'}), 500

        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO saved_quizzes (topic, quiz_json, created_by) VALUES (?, ?, ?)",
            (topic, json.dumps(questions), username)
        )
        quiz_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'quiz_id': quiz_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/save-quiz', methods=['POST'])
def save_quiz():
    """Save an AI generated quiz to the database"""
    try:
        data = request.json
        topic = data.get('topic')
        questions = data.get('questions')
        created_by = data.get('created_by')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO saved_quizzes (topic, quiz_json, created_by) VALUES (?, ?, ?)",
            (topic, json.dumps(questions), created_by)
        )
        quiz_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'quiz_id': quiz_id}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/my-quizzes')
def get_my_quizzes():
    """Get list of quizzes created by a user"""
    try:
        username = request.args.get('username')
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, topic, created_at FROM saved_quizzes WHERE created_by = ? ORDER BY created_at DESC",
            (username,)
        )
        rows = cursor.fetchall()
        quizzes = [dict(r) for r in rows]
        conn.close()
        return jsonify({'success': True, 'quizzes': quizzes})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/quiz/<int:quiz_id>')
def get_single_quiz(quiz_id):
    """Fetch a single AI-generated quiz by its ID"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, topic, quiz_json FROM saved_quizzes WHERE id = ?", (quiz_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return jsonify({
                'success': True, 
                'quiz': {
                    'id': row['id'], 
                    'topic': row['topic'], 
                    'questions': json.loads(row['quiz_json'])
                }
            })
        return jsonify({'success': False, 'message': 'Quiz not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/quiz_<int:quiz_id>.html')
def serve_quiz_player(quiz_id):
    """Serve the dynamic quiz player for any quiz ID"""
    return send_from_directory('.', 'quiz_player.html')

@app.route('/api/official-exams/submit', methods=['POST'])
def submit_official_exam():
    try:
        data = request.json
        u = data.get('username')
        paper_id = data.get('paper_id')
        topic = data.get('topic')
        score = data.get('score')
        total = data.get('total_marks')
        answers = data.get('answers')
        
        if not u or not paper_id: return jsonify({'error': 'Missing data'}), 400
        
        # Structure the quiz_data_json to match AI quiz expectations for the dashboard
        quiz_summary = {
            'paper_id': paper_id,
            'title': topic,
            'topic': topic,
            'is_official': True
        }
        
        conn = get_db(); cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)",
            (u, json.dumps(quiz_summary), json.dumps(answers), score, total)
        )
        conn.commit(); conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz():
    """Save the results of a taken AI quiz from the generator"""
    try:
        data = request.json
        username = data.get('username')
        topic = data.get('topic')
        score_str = data.get('score') # Format: "X / Y"
        percentage = data.get('percentage')
        questions_results = data.get('questions')
        
        # Parse score
        try:
            score_parts = score_str.split(' / ')
            score = int(score_parts[0])
            total = int(score_parts[1])
        except:
            score = 0
            total = 0

        # Construct quiz_data_json to match results dashboard expectation
        quiz_data = {
            'topic': topic,
            'questions': questions_results
        }
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)",
            (username, json.dumps(quiz_data), json.dumps(questions_results), score, total)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/quiz-results/save', methods=['POST'])
def save_quiz_results():
    """Save the results of a taken quiz"""
    try:
        data = request.json
        username = data.get('username')
        quiz_data = data.get('quiz_data') # Original quiz
        answers = data.get('answers') # Student answers
        score = data.get('score')
        total = data.get('total')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)",
            (username, json.dumps(quiz_data), json.dumps(answers), score, total)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- BACKGROUND IMPORT LOGIC ---

def run_import_background(job_id, qp_path, ms_path, er_path, metadata):
    try:
        import_jobs[job_id]['status'] = 'extracting_text'
        qp_text = extract_pdf_text(qp_path); ms_text = extract_pdf_text(ms_path)
        er_text = extract_pdf_text(er_path) if er_path and os.path.exists(er_path) else ""
        qp_pages = qp_text.split('\n---PAGE BREAK---\n'); all_questions_map = {}; total_pages = len(qp_pages)
        
        for i, page_content in enumerate(qp_pages):
            page_num = i + 1
            import_jobs[job_id].update({'status': 'mapping', 'current_page': page_num, 'total_pages': total_pages, 'questions_found': len(all_questions_map)})
            if not page_content.strip(): continue

            # Robust ID Identification
            id_prompt = f"""Analyze this IGCSE exam page text. Identify ALL question and sub-question IDs (e.g. 1, 1(a), 1(b)(i), 2(c), 10) that appear.
Note: In English Language papers, questions might just be a number followed by text (e.g. "1 In lines 7-14..."). 
Look for bold numbers or labels at the start of paragraphs.

TEXT:
{page_content}

Return a JSON list of strings only.
Example: ["1", "2", "3", "4", "5"]"""
            
            try:
                resp = requests.post('http://localhost:11434/api/generate', json={'model': 'llama3', 'prompt': id_prompt, 'stream': False, 'format': 'json', 'temperature': 0}, timeout=45)
                found_data = clean_ai_json(resp.json().get('response', '[]'))
                
                # Fallback: Use regex if AI returns nothing
                if not found_data or not isinstance(found_data, list):
                    found_data = re.findall(r'Question\s+(\d+)', page_content, re.IGNORECASE)
                    # Also look for English-style single numbers at start of lines
                    more = re.findall(r'^\s*(\d+)\s+[A-Z]', page_content, re.MULTILINE)
                    found_data = list(set(found_data + more))
                
                print(f"  [IMPORT] Page {page_num} found IDs: {found_data}", flush=True)

                if not found_data: continue

                for sub_id in sorted(found_data):
                    m = re.search(r'(\d+)', str(sub_id))
                    if not m: continue
                    main_id = int(m.group(1))

                    q_prompt = f"""Extract marking details for sub-question {sub_id} from the mark scheme.
MATCHING QUESTION ID: {sub_id}
MARK SCHEME TEXT:
{ms_text[:40000]}

Return ONLY a JSON object: {{"sub_id": "{sub_id}", "type": "text/mcq/calculation/draw/list", "max_marks": 1, "ms_text": "..."}}"""
                    
                    q_resp = requests.post('http://localhost:11434/api/generate', json={'model': 'llama3', 'prompt': q_prompt, 'stream': False, 'format': 'json', 'temperature': 0}, timeout=90)
                    sq = clean_ai_json(q_resp.json().get('response', '{}'))
                    print(f"    [IMPORT] Sub-ID {sub_id} detail AI raw: {q_resp.json().get('response', '')[:100]}...", flush=True)
                    if not sq or not sq.get('sub_id'): continue
                    
                    if main_id not in all_questions_map: all_questions_map[main_id] = {"id": main_id, "sub_questions": []}
                    existing = next((s for s in all_questions_map[main_id]['sub_questions'] if s['sub_id'] == sq['sub_id']), None)
                    if not existing:
                        sq['qp_pages'] = [page_num]
                        all_questions_map[main_id]['sub_questions'].append(sq)
                    else:
                        if page_num not in existing.get('qp_pages', []): existing.setdefault('qp_pages', []).append(page_num)
                        if len(str(sq.get('ms_text', ''))) > len(str(existing.get('ms_text', ''))): existing['ms_text'] = sq['ms_text']
            except: pass

        import_jobs[job_id]['status'] = 'images'
        qp_img_dir = f"static/exams/{metadata['id']}/qp"; os.makedirs(qp_img_dir, exist_ok=True)
        images = convert_from_path(qp_path, dpi=150)
        for i, img in enumerate(images): img.save(os.path.join(qp_img_dir, f"page_{i+1:02d}.png"), 'PNG')
        
        final_data = {"paper_id": metadata['id'], "title": metadata['title'], "subject": metadata['subject'], "qp_img_dir": f"/{qp_img_dir}/", "er_text": er_text, "questions": sorted(all_questions_map.values(), key=lambda q: q['id']), "extract_pages": []}
        json_path = f"exam_data/{metadata['id']}.json"
        with open(json_path, 'w') as f: json.dump(final_data, f, indent=2)
        conn = sqlite3.connect(DATABASE); cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO official_exams (id, title, subject, paper, date, data_json_path, er_text, source_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (metadata['id'], metadata['title'], metadata['subject'], metadata['paper'], metadata['date'], json_path, er_text, os.path.abspath(qp_path)))
        conn.commit(); conn.close(); import_jobs[job_id]['status'] = 'completed'
    except Exception as e: import_jobs[job_id].update({'status': 'failed', 'error': str(e)})

@app.route('/api/admin/process-exam', methods=['POST'])
def process_official_exam():
    try:
        data = request.json; qp_path = data.get('qp_path')
        if not qp_path: return jsonify({'success': False}), 400
        qp_snippet = extract_pdf_text(qp_path)[:3000]
        meta_prompt = f"Return JSON metadata (title, subject, paper, date) for: {qp_snippet}"
        try:
            resp = requests.post('http://localhost:11434/api/generate', json={'model': 'llama3', 'prompt': meta_prompt, 'stream': False, 'format': 'json'}, timeout=40)
            metadata = clean_ai_json(resp.json().get('response', '{}'))
        except: metadata = {}
        
        # Regex Fallback for Date
        if not metadata.get('date') or metadata['date'] == 'Unknown':
            date_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}', qp_snippet, re.I)
            if date_match: metadata['date'] = date_match.group(0)
            else:
                year_match = re.search(r'20\d{2}', qp_snippet)
                if year_match: metadata['date'] = year_match.group(0)

        metadata['title'] = metadata.get('title') or os.path.basename(qp_path).replace('.pdf', '')
        if 'biology' in qp_path.lower(): metadata['subject'] = 'Biology'
        elif 'english' in qp_path.lower(): metadata['subject'] = 'English'
        metadata['paper'] = metadata.get('paper') or 'Paper'; metadata['date'] = metadata.get('date') or 'Unknown'
        metadata['id'] = data.get('id') or str(uuid.uuid4())[:8]
        job_id = str(uuid.uuid4())
        import_jobs[job_id] = {'status': 'starting', 'paper_id': metadata['id'], 'title': metadata['title'], 'current_page': 0, 'total_pages': 0, 'questions_found': 0}
        threading.Thread(target=run_import_background, args=(job_id, qp_path, data.get('ms_path'), data.get('er_path'), metadata)).start()
        return jsonify({'success': True, 'job_id': job_id}), 202
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/admin/delete-exam', methods=['POST'])
def delete_official_exam():
    try:
        data = request.json; paper_id = data.get('paper_id')
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT data_json_path FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        if row:
            if os.path.exists(row['data_json_path']): os.remove(row['data_json_path'])
            static_dir = f"static/exams/{paper_id}"
            if os.path.exists(static_dir): shutil.rmtree(static_dir)
        cursor.execute("DELETE FROM official_exams WHERE id = ?", (paper_id,))
        conn.commit(); conn.close(); return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/official-exams/list')
def list_official_exams():
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT id, title, subject, paper, date, data_json_path FROM official_exams ORDER BY created_at DESC")
        exams = [dict(e) for e in cursor.fetchall()]; conn.close()
        for e in exams:
            try:
                with open(e['data_json_path'], 'r') as f: e['total_questions'] = len(json.load(f).get('questions', []))
            except: e['total_questions'] = 0
        return jsonify({'success': True, 'exams': exams}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/official-exams/check/<paper_id>')
def check_exam_exists(paper_id):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT id FROM official_exams WHERE id = ?", (paper_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return jsonify({'exists': exists})

@app.route('/api/official-exams/<paper_id>')
def get_official_exam(paper_id):
    path = f'exam_data/{paper_id}.json'
    if not os.path.exists(path): return jsonify({'error': 'Not found'}), 404
    with open(path, 'r') as f: return jsonify(json.load(f))

@app.route('/api/official-exams/<paper_id>/page-count')
def get_exam_page_count(paper_id):
    try:
        with open(f'exam_data/{paper_id}.json', 'r') as f: data = json.load(f)
        full_path = os.path.join(os.getcwd(), data['qp_img_dir'].lstrip('/'))
        return jsonify({'count': len([f for f in os.listdir(full_path) if f.endswith('.png')])})
    except: return jsonify({'count': 0})

@app.route('/api/official-exams/<paper_id>/extracts-text')
def get_extracts_text(paper_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT source_path, data_json_path FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        if not row: return jsonify({'error': 'Not found'}), 404
        
        source_path = row['source_path']
        with open(row['data_json_path'], 'r') as f:
            extract_pages = json.load(f).get('extract_pages', [])
        
        if not extract_pages: return jsonify({'success': True, 'texts': []})

        # Extract text using pdftotext
        res = subprocess.run(['pdftotext', '-layout', source_path, '-'], capture_output=True, text=True)
        if res.returncode != 0: return jsonify({'error': 'PDF extraction failed'}), 500
        
        all_pages = res.stdout.split('\f')
        extract_texts = []
        for p_num in extract_pages:
            if 0 < p_num <= len(all_pages):
                extract_texts.append({
                    'page': p_num,
                    'text': all_pages[p_num-1].strip()
                })
        
        return jsonify({'success': True, 'texts': extract_texts})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/official-exams/grade', methods=['POST'])
def grade_official_question():
    try:
        data = request.json
        paper_id = data.get('paper_id')
        sub_id = data.get('sub_id')
        user_answer = data.get('user_answer')
        mark_scheme = data.get('mark_scheme')
        max_marks = data.get('max_marks', 1)
        image_data = data.get('image_data')

        # Get Examiner Report if available
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT er_text FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone(); er_text = row['er_text'] if row and row['er_text'] else ""; conn.close()

        prompt = f"""You are an expert IGCSE Edexcel Examiner. 
Your task is to mark a student's answer based STRICTLY on the official Mark Scheme provided.

PAPER ID: {paper_id}
QUESTION: {sub_id}
MAX MARKS: {max_marks}

OFFICIAL MARK SCHEME:
{mark_scheme}

EXAMINER REPORT:
{er_text[:3000]}

STUDENT'S ANSWER:
{user_answer}

MARKING INSTRUCTIONS:
1. ZERO TOLERANCE: If the student's answer is gibberish, nonsensical, irrelevant text (like "abc", "testing", "random"), or just a request for help (unless help keywords are used), you MUST award 0 marks.
2. MCQ (MULTIPLE CHOICE): If the student's answer is a single letter (A, B, C, or D), award FULL MARKS if it matches the correct answer in the mark scheme. Otherwise, award 0.
3. HELP REQUESTS: If the student asks for help (e.g., "show me", "tell me"), award 0 marks but provide a warm, helpful explanation of the concept and the correct answer.
4. CALCULATION HANDLING: 
   - Answer is structured with [WORKING_START] and [FINAL_ANSWER_START].
   - If [FINAL_ANSWER_START] is correct according to the mark scheme, award FULL MARKS (2/2).
   - If [FINAL_ANSWER_START] is wrong or missing, award 1 mark ONLY if a valid intermediate step (like a correct subtraction or division shown in the mark scheme) is clearly visible in [WORKING_START].
   - DO NOT award marks for "trying" or for unrelated numbers.
5. Provide a "MODEL ANSWER" if the student didn't get full marks.

RESPONSE FORMAT (JSON ONLY):
{{
  "marks_awarded": 0,
  "max_marks": {max_marks},
  "feedback": "Your evaluation here. \\n\\nMODEL ANSWER: [Provide the correct answer and steps from the mark scheme]",
  "marking_points_met": []
}}

MANDATORY RULES:
1. If the student's answer is blank, nonsensical, or completely irrelevant, award 0 marks.
2. For calculations, only award marks if the numbers in the student's working or final answer actually appear in or are derived from the mark scheme.
3. You MUST return a valid JSON object. Do not include any text before or after the JSON.
"""
        payload = {'model': 'llama3', 'prompt': prompt, 'stream': False, 'format': 'json', 'temperature': 0}
        if image_data and image_data.startswith('data:image'):
            payload['images'] = [image_data.split(',')[1]]
            
        resp = requests.post('http://localhost:11434/api/generate', json=payload)
        raw = resp.json().get('response', '{}')
        print(f"  [GRADING] Q {sub_id} RAW AI: {raw.strip()}", flush=True)
        result = clean_ai_json(raw) or {"marks_awarded": 0, "feedback": "AI Parsing Error"}
        return jsonify(result), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/student/exam-progress/save', methods=['POST'])
def save_exam_progress():
    try:
        data = request.json
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO exam_progress (username, paper_id, current_question_idx, answers_json, last_updated) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)", (data.get('username'), data.get('paper_id'), data.get('current_question_idx', 0), json.dumps(data.get('answers', {}))))
        conn.commit(); conn.close(); return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/student/exam-progress/get')
def get_exam_progress():
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM exam_progress WHERE username = ? AND paper_id = ?", (request.args.get('username'), request.args.get('paper_id')))
        row = cursor.fetchone(); conn.close()
        if row: return jsonify({'success': True, 'current_question_idx': row['current_question_idx'], 'answers': json.loads(row['answers_json']), 'status': row['status']}), 200
        return jsonify({'success': False}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/results/detail')
def get_result_detail():
    u = request.args.get('username')
    paper_id = request.args.get('paper_id')
    if not u or not paper_id: return jsonify({'error': 'Missing params'}), 400
    
    conn = get_db(); cursor = conn.cursor()
    # Find the most recent result for this student and paper
    cursor.execute("""
        SELECT * FROM quiz_results 
        WHERE username = ? AND quiz_data_json LIKE ? 
        ORDER BY timestamp DESC LIMIT 1
    """, (u, f'%"{paper_id}"%'))
    row = cursor.fetchone(); conn.close()
    
    if row:
        return jsonify({
            'success': True,
            'answers': json.loads(row['answers_json']),
            'score': row['score'],
            'total_marks': row['total_marks'],
            'timestamp': row['timestamp']
        })
    return jsonify({'success': False, 'message': 'Result not found'}), 404

@app.route('/api/results')
def get_results_api():
    u = request.args.get('username'); conn = get_db(); cursor = conn.cursor()
    users = load_users(); is_admin = u in users and users[u].get('role') == 'admin'
    if is_admin: cursor.execute("SELECT * FROM quiz_results ORDER BY timestamp DESC")
    else: cursor.execute("SELECT * FROM quiz_results WHERE username = ? ORDER BY timestamp DESC", (u,))
    rows = cursor.fetchall(); results = []
    for row in rows:
        try:
            quiz_data = json.loads(row['quiz_data_json'])
            topic = quiz_data.get('topic') or quiz_data.get('title') or 'Official Paper'
        except:
            topic = 'Quiz'
            
        results.append({
            'id': row['id'], 
            'username': row['username'], 
            'topic': topic, 
            'score': row['score'], 
            'total_marks': row['total_marks'],
            'timestamp': row['timestamp'],
            'answers': json.loads(row['answers_json']) if row['answers_json'] else [],
            'quiz_data': json.loads(row['quiz_data_json']) if row['quiz_data_json'] else {}
        })
    conn.close(); return jsonify({'success': True, 'results': results})

@app.route('/api/student/exam-progress/list')
def list_student_progress():
    try:
        u = request.args.get('username'); conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT paper_id, status, last_updated FROM exam_progress WHERE username = ?", (u,))
        rows = cursor.fetchall(); conn.close()
        return jsonify({'success': True, 'progress': {r['paper_id']: {'status': r['status'], 'last_updated': r['last_updated']} for r in rows}}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

# --- USER PREFERENCES API ---

@app.route('/api/user/preferences/get')
def get_user_preferences():
    try:
        u = request.args.get('username')
        if not u: return jsonify({'error': 'Missing username'}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT theme_json, ui_state_json FROM user_preferences WHERE username = ?", (u,))
        row = cursor.fetchone(); conn.close()
        if row:
            return jsonify({
                'success': True,
                'theme': json.loads(row['theme_json']) if row['theme_json'] else None,
                'ui_state': json.loads(row['ui_state_json']) if row['ui_state_json'] else None
            })
        return jsonify({'success': True, 'theme': None, 'ui_state': None})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/user/preferences/save', methods=['POST'])
def save_user_preferences():
    try:
        data = request.json
        u = data.get('username')
        if not u: return jsonify({'error': 'Missing username'}), 400
        
        conn = get_db(); cursor = conn.cursor()
        if 'theme' in data:
            cursor.execute('''
                INSERT INTO user_preferences (username, theme_json) VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET theme_json = excluded.theme_json, updated_at = CURRENT_TIMESTAMP
            ''', (u, json.dumps(data['theme'])))
            
        if 'ui_state' in data:
            cursor.execute('''
                INSERT INTO user_preferences (username, ui_state_json) VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET ui_state_json = excluded.ui_state_json, updated_at = CURRENT_TIMESTAMP
            ''', (u, json.dumps(data['ui_state'])))
            
        conn.commit(); conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

# --- PAGE ROUTES ---

@app.route('/')
def home_page(): return send_from_directory('.', 'exam_generator_v2.html')

@app.route('/api/student/exam-progress/delete', methods=['POST'])
def delete_exam_progress():
    try:
        data = request.json
        u, paper_id = data.get('username'), data.get('paper_id')
        if not u or not paper_id: return jsonify({'success': False}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("DELETE FROM exam_progress WHERE username = ? AND paper_id = ?", (u, paper_id))
        conn.commit(); conn.close()
        return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/results')
def results_dashboard_page(): return send_from_directory('.', 'results_dashboard.html')

@app.route('/admin_exams.html')
def admin_exams_manager_page(): return send_from_directory('.', 'admin_exams.html')

@app.route('/admin_users.html')
def admin_users_manager_page(): return send_from_directory('.', 'admin_users.html')

@app.route('/login.html')
def auth_login_page(): return send_from_directory('.', 'login.html')

@app.route('/register.html')
def auth_register_page(): return send_from_directory('.', 'register.html')

@app.route('/exam_questions.html')
def paper_gallery_page(): return send_from_directory('.', 'exam_questions.html')

@app.route('/official_exam_player.html')
def exam_player_screen_page(): return send_from_directory('.', 'official_exam_player.html')

@app.route('/static/<path:path>')
def serve_static_assets(path): return send_from_directory('static', path)

@app.route('/<path:path>')
def serve_everything_else(path): return send_from_directory('.', path)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=True)
