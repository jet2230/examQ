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
OLLAMA_API = "http://127.0.0.1:11434/api/generate"

# Global state for background import jobs
import_jobs = {}

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Check current columns in users table
    cursor.execute("PRAGMA table_info(users)")
    columns = [row['name'] for row in cursor.fetchall()]
    
    if not columns:
        cursor.execute('''
            CREATE TABLE users (
                username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT DEFAULT 'student',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_online DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        if 'created_at' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN created_at DATETIME DEFAULT '2026-03-02 15:30:00'")
        if 'last_online' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_online DATETIME DEFAULT '2026-03-03 00:00:00'")    
    
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
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
    if not text: return None
    
    # 0. Basic cleaning
    text = text.strip()
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)

    try:
        # 1. Direct parse
        return json.loads(text)
    except:
        # 2. Try to find largest matching block
        # Look for [ ... ]
        list_match = re.findall(r'\[.*\]', text, re.DOTALL)
        if list_match:
            # Sort by length descending to find the most complete JSON
            list_match.sort(key=len, reverse=True)
            for m in list_match:
                try: return json.loads(m)
                except: continue

        # 3. Look for { ... }
        obj_match = re.findall(r'\{.*\}', text, re.DOTALL)
        if obj_match:
            obj_match.sort(key=len, reverse=True)
            for m in obj_match:
                try: return json.loads(m)
                except: continue
        
        # 4. Final attempt: deep cleaning of common AI escape issues
        try:
            # Sometimes AI adds comments or trailing commas
            cleaned = re.sub(r'//.*', '', text) # Remove single line comments
            cleaned = re.sub(r',\s*([\]\}])', r'\1', cleaned) # Remove trailing commas
            return json.loads(cleaned)
        except:
            return None

# --- API ROUTES ---

@app.route('/api/user/heartbeat', methods=['POST'])
def user_heartbeat():
    try:
        data = request.json
        u = data.get('username')
        if not u: return jsonify({'error': 'Missing username'}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_online = CURRENT_TIMESTAMP WHERE username = ?", (u,))
        conn.commit(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/users/all')
def get_all_users_status():
    try:
        conn = get_db(); cursor = conn.cursor()
        # Get all users and their status (online if seen in last 2 mins)
        cursor.execute("""
            SELECT username, role, last_online,
            CASE WHEN last_online > datetime('now', '-2 minutes') THEN 1 ELSE 0 END as is_online
            FROM users
            ORDER BY is_online DESC, username ASC
        """)
        rows = cursor.fetchall(); conn.close()
        users = [{'username': r['username'], 'role': r['role'], 'is_online': bool(r['is_online']), 'last_online': r['last_online']} for r in rows]
        return jsonify({'success': True, 'users': users}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/send', methods=['POST'])
def send_message():
    try:
        data = request.json
        s, r, m = data.get('sender'), data.get('recipient'), data.get('message')
        if not s or not r or not m: return jsonify({'error': 'Missing fields'}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", (s, r, m))
        conn.commit(); conn.close()
        return jsonify({'success': True}), 201
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/get')
def get_messages():
    try:
        u = request.args.get('username')
        other = request.args.get('other')
        if not u: return jsonify({'error': 'Missing username'}), 400
        conn = get_db(); cursor = conn.cursor()
        if other:
            # Get conversation with specific user
            cursor.execute("""
                SELECT * FROM messages 
                WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                ORDER BY timestamp ASC
            """, (u, other, other, u))
        else:
            # Get all recent messages for user
            cursor.execute("SELECT * FROM messages WHERE recipient = ? OR sender = ? ORDER BY timestamp DESC LIMIT 50", (u, u))
        
        rows = cursor.fetchall(); conn.close()
        results = [dict(r) for r in rows]
        return jsonify({'success': True, 'messages': results}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/read', methods=['POST'])
def mark_messages_read():
    try:
        data = request.json
        u, other = data.get('username'), data.get('other')
        if not u or not other: return jsonify({'error': 'Missing fields'}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_read = 1 WHERE recipient = ? AND sender = ?", (u, other))
        conn.commit(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/unread-count')
def get_unread_count():
    try:
        u = request.args.get('username')
        conn = get_db(); cursor = conn.cursor()
        # Total unread count
        cursor.execute("SELECT COUNT(*) as count FROM messages WHERE recipient = ? AND is_read = 0", (u,))
        total = cursor.fetchone()['count']
        
        # Breakdown by sender
        cursor.execute("SELECT sender, COUNT(*) as count FROM messages WHERE recipient = ? AND is_read = 0 GROUP BY sender", (u,))
        rows = cursor.fetchall(); conn.close()
        by_sender = {r['sender']: r['count'] for r in rows}
        
        return jsonify({'success': True, 'count': total, 'by_sender': by_sender}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    users = load_users()
    u, p = data.get('username'), data.get('password')
    if u in users and users[u]['password'] == p:
        # Update last online on login
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_online = CURRENT_TIMESTAMP WHERE username = ?", (u,))
        conn.commit(); conn.close()
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
        cursor.execute("INSERT INTO users (username, password, created_at, last_online) VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (u, p))
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
    users_data = load_users()
    if admin_username not in users_data or users_data[admin_username].get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute('''
            SELECT u.username, u.role, u.created_at, 
                   (SELECT COUNT(*) FROM quiz_results r WHERE r.username = u.username) as quizzes_taken
            FROM users u
            ORDER BY u.created_at DESC
        ''')
        users_list = {row['username']: {'role': row['role'], 'created_at': row['created_at'], 'quizzes_taken': row['quizzes_taken']} for row in cursor.fetchall()}
        conn.close()
        return jsonify({'success': True, 'users': users_list})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/update-user', methods=['POST'])
def admin_update_user():
    data = request.json
    admin_username = data.get('admin_username')
    users_data = load_users()
    if admin_username not in users_data or users_data[admin_username].get('role') != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    old_username = data.get('old_username')
    new_username = data.get('new_username')
    new_password = data.get('new_password')
    try:
        conn = get_db(); cursor = conn.cursor()
        if new_username and new_username != old_username:
            cursor.execute("UPDATE users SET username = ? WHERE username = ?", (new_username, old_username))
            cursor.execute("UPDATE quiz_results SET username = ? WHERE username = ?", (new_username, old_username))
            cursor.execute("UPDATE exam_progress SET username = ? WHERE username = ?", (new_username, old_username))
            cursor.execute("UPDATE saved_quizzes SET created_by = ? WHERE created_by = ?", (new_username, old_username))
            target_username = new_username
        else: target_username = old_username
        if new_password: cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, target_username))
        conn.commit(); conn.close(); return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500

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
    try:
        data = request.json; topic = data.get('topic'); num = data.get('num_questions', 10); username = data.get('username')
        prompt = f"""Create a multiple-choice quiz about: {topic}. Number of questions: {num}.
For each question: 1. Provide a clear, challenging question. 2. Provide 4 unique, descriptive options. 
3. CRITICAL: Exactly ONE option must be correct. The other THREE options must be definitively INCORRECT distractors.
4. DO NOT create questions where multiple options could be considered correct. 5. DO NOT use letters like 'A', 'B', 'C', 'D' as the option text. 
6. Identify the correct answer letter (A, B, C, or D). Return ONLY a JSON list."""
        response = requests.post(OLLAMA_API, json={'model': 'llama3', 'prompt': prompt, 'stream': False, 'format': 'json'}, timeout=120)
        questions = clean_ai_json(response.json().get('response', '[]'))
        if not questions: return jsonify({'success': False, 'error': 'Failed to parse AI response'}), 500
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO saved_quizzes (topic, quiz_json, created_by) VALUES (?, ?, ?)", (topic, json.dumps(questions), username))
        quiz_id = cursor.lastrowid; conn.commit(); conn.close()
        return jsonify({'success': True, 'quiz_id': quiz_id})
    except Exception as e: return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/my-quizzes')
def get_my_quizzes():
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT id, topic, created_at, created_by FROM saved_quizzes ORDER BY created_at DESC")
        rows = cursor.fetchall(); quizzes = [dict(r) for r in rows]; conn.close()
        return jsonify({'success': True, 'quizzes': quizzes})
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/delete-quiz', methods=['POST'])
def delete_quiz():
    try:
        data = request.json; admin_u = data.get('admin_username'); quiz_id = data.get('quiz_id')
        users = load_users()
        if not admin_u in users or users[admin_u].get('role') != 'admin': return jsonify({'error': 'Unauthorized'}), 403
        conn = get_db(); cursor = conn.cursor(); cursor.execute("DELETE FROM saved_quizzes WHERE id = ?", (quiz_id,))
        conn.commit(); conn.close(); return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/quiz/<int:quiz_id>')
def get_single_quiz(quiz_id):
    try:
        conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT id, topic, quiz_json FROM saved_quizzes WHERE id = ?", (quiz_id,))
        row = cursor.fetchone(); conn.close()
        if row: return jsonify({'success': True, 'quiz': {'id': row['id'], 'topic': row['topic'], 'questions': json.loads(row['quiz_json'])}})
        return jsonify({'success': False, 'message': 'Quiz not found'}), 404
    except Exception as e: return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/quiz_<int:quiz_id>.html')
def serve_quiz_player(quiz_id): return send_from_directory('.', 'quiz_player.html')

@app.route('/api/official-exams/submit', methods=['POST'])
def submit_official_exam():
    try:
        data = request.json; u = data.get('username'); paper_id = data.get('paper_id'); topic = data.get('topic'); score = data.get('score'); total = data.get('total_marks'); answers = data.get('answers')
        if not u or not paper_id: return jsonify({'error': 'Missing data'}), 400
        quiz_summary = {'paper_id': paper_id, 'title': topic, 'topic': topic, 'is_official': True}
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)", (u, json.dumps(quiz_summary), json.dumps(answers), score, total))
        conn.commit(); conn.close(); return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz_api():
    try:
        data = request.json; username = data.get('username'); topic = data.get('topic'); score_str = data.get('score'); questions_results = data.get('questions')
        try:
            parts = score_str.split(' / '); score, total = int(parts[0]), int(parts[1])
        except: score, total = 0, 0
        quiz_data = {'topic': topic, 'questions': questions_results}
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)", (username, json.dumps(quiz_data), json.dumps(questions_results), score, total))
        conn.commit(); conn.close(); return jsonify({'success': True}), 201
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/official-exams/grade', methods=['POST'])
def grade_official_question():
    try:
        data = request.json; paper_id = data.get('paper_id'); sub_id = data.get('sub_id'); user_answer = data.get('user_answer'); mark_scheme = data.get('mark_scheme'); max_marks = data.get('max_marks', 1); q_type = data.get('type')
        conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT er_text FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone(); er_text = row['er_text'] if row and row['er_text'] else ""; conn.close()
        if q_type in ['draw', 'graph']:
            return jsonify({"marks_awarded": max_marks, "max_marks": max_marks, "feedback": f"VISUAL EVALUATION: As an AI, I cannot grade your drawing or graph. You have been awarded full marks automatically. Please verify your work against the official criteria.\n\nFULL MARK SCHEME: {mark_scheme}", "marking_points_met": ["Self-evaluation required"]}), 200
        cleaned_ans = user_answer.strip().upper()
        if q_type == 'mcq' or (len(cleaned_ans) == 1 and cleaned_ans in ['A', 'B', 'C', 'D']):
            mcq_match = re.search(r'(?:Correct Answer|Answer is|Correct|Key)[:\s]+([A-D])', mark_scheme, re.I)
            if not mcq_match: mcq_match = re.search(r'(?:^|\.|\s)([A-D])\s*\(', mark_scheme)
            if mcq_match:
                correct_letter = mcq_match.group(1).upper()
                if cleaned_ans == correct_letter: return jsonify({"marks_awarded": max_marks, "max_marks": max_marks, "feedback": f"Correct! The answer is {correct_letter}.", "marking_points_met": ["Correct MCQ selection"]}), 200
                else: return jsonify({"marks_awarded": 0, "max_marks": max_marks, "feedback": f"Incorrect. Your answer was {cleaned_ans}, but the correct answer is {correct_letter}. \n\nMODEL ANSWER: {mark_scheme}", "marking_points_met": []}), 200
        prompt = f"""You are an expert IGCSE Edexcel Examiner. [OFFICIAL MARK SCHEME] {mark_scheme} [STUDENT ANSWER] {user_answer} [TASK] 1. Compare answer to scheme. 2. Score out of {max_marks}. 3. For text, mark semantically. 4. For math, exact numbers required. [OUTPUT JSON] {{"marks_awarded": integer, "max_marks": {max_marks}, "feedback": "JUSTIFICATION: ...\n\nFULL MARK SCHEME: {mark_scheme.replace('"',"'")}"}}"""
        resp = requests.post(OLLAMA_API, json={'model': 'llama3', 'prompt': prompt, 'stream': False, 'format': 'json', 'temperature': 0})
        result = clean_ai_json(resp.json().get('response', '{}')) or {"marks_awarded": 0, "feedback": "AI Parsing Error"}
        return jsonify(result), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/student/exam-progress/save', methods=['POST'])
def save_exam_progress():
    try:
        data = request.json; conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO exam_progress (username, paper_id, current_question_idx, answers_json, last_updated) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)", (data.get('username'), data.get('paper_id'), data.get('current_question_idx', 0), json.dumps(data.get('answers', {}))))
        conn.commit(); conn.close(); return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/student/exam-progress/get')
def get_exam_progress():
    try:
        conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT * FROM exam_progress WHERE username = ? AND paper_id = ?", (request.args.get('username'), request.args.get('paper_id')))
        row = cursor.fetchone(); conn.close()
        if row: return jsonify({'success': True, 'current_question_idx': row['current_question_idx'], 'answers': json.loads(row['answers_json']), 'status': row['status']}), 200
        return jsonify({'success': False}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/results/detail')
def get_result_detail():
    u = request.args.get('username'); paper_id = request.args.get('paper_id')
    conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT * FROM quiz_results WHERE username = ? AND quiz_data_json LIKE ? ORDER BY timestamp DESC LIMIT 1", (u, f'%"{paper_id}"%'))
    row = cursor.fetchone(); conn.close()
    if row: return jsonify({'success': True, 'answers': json.loads(row['answers_json']), 'score': row['score'], 'total_marks': row['total_marks'], 'timestamp': row['timestamp']})
    return jsonify({'success': False, 'message': 'Result not found'}), 404

@app.route('/api/results')
def get_results_api():
    try:
        conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT * FROM quiz_results ORDER BY timestamp DESC")
        rows = cursor.fetchall(); results = []
        for r in rows:
            try: qd = json.loads(r['quiz_data_json']); topic = qd.get('topic') or qd.get('title') or 'Official Paper'
            except: topic = 'Quiz'
            results.append({'id': r['id'], 'username': r['username'], 'topic': topic, 'score': r['score'], 'total_marks': r['total_marks'], 'timestamp': r['timestamp'], 'answers': json.loads(r['answers_json']), 'quiz_data': json.loads(r['quiz_data_json'])})
        conn.close(); return jsonify({'success': True, 'results': results})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/student/exam-progress/list')
def list_student_progress():
    try:
        u = request.args.get('username'); conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT paper_id, status, last_updated FROM exam_progress WHERE username = ?", (u,))
        rows = cursor.fetchall(); conn.close()
        return jsonify({'success': True, 'progress': {r['paper_id']: {'status': r['status'], 'last_updated': r['last_updated']} for r in rows}}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/admin/all-progress')
def list_all_progress():
    try:
        u = request.args.get('username'); users = load_users()
        if not u in users or users[u].get('role') != 'admin': return jsonify({'error': 'Unauthorized'}), 403
        conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT p.username, p.paper_id, p.status, p.last_updated, e.title FROM exam_progress p LEFT JOIN official_exams e ON p.paper_id = e.id ORDER BY p.last_updated DESC")
        rows = cursor.fetchall(); conn.close()
        results = [{'username': r['username'], 'paper_id': r['paper_id'], 'title': r['title'] or r['paper_id'], 'status': r['status'], 'last_updated': r['last_updated']} for r in rows]
        return jsonify({'success': True, 'all_progress': results}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/user/preferences/get')
def get_user_preferences():
    try:
        u = request.args.get('username'); conn = get_db(); cursor = conn.cursor(); cursor.execute("SELECT theme_json, ui_state_json FROM user_preferences WHERE username = ?", (u,))
        row = cursor.fetchone(); conn.close()
        if row: return jsonify({'success': True, 'theme': json.loads(row['theme_json']) if row['theme_json'] else None, 'ui_state': json.loads(row['ui_state_json']) if row['ui_state_json'] else None})
        return jsonify({'success': True, 'theme': None, 'ui_state': None})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/user/preferences/save', methods=['POST'])
def save_user_preferences():
    try:
        data = request.json; u = data.get('username'); conn = get_db(); cursor = conn.cursor()
        if 'theme' in data: cursor.execute("INSERT INTO user_preferences (username, theme_json) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET theme_json = excluded.theme_json, updated_at = CURRENT_TIMESTAMP", (u, json.dumps(data['theme'])))
        if 'ui_state' in data: cursor.execute("INSERT INTO user_preferences (username, ui_state_json) VALUES (?, ?) ON CONFLICT(username) DO UPDATE SET ui_state_json = excluded.ui_state_json, updated_at = CURRENT_TIMESTAMP", (u, json.dumps(data['ui_state'])))
        conn.commit(); conn.close(); return jsonify({'success': True})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/')
def home_page(): return send_from_directory('.', 'exam_generator_v2.html')

@app.route('/api/student/exam-progress/delete', methods=['POST'])
def delete_exam_progress():
    try:
        data = request.json; u, paper_id = data.get('username'), data.get('paper_id')
        conn = get_db(); cursor = conn.cursor(); cursor.execute("DELETE FROM exam_progress WHERE username = ? AND paper_id = ?", (u, paper_id))
        conn.commit(); conn.close(); return jsonify({'success': True})
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
