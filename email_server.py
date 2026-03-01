#!/usr/bin/env python3
"""
Quiz Server with User Management
Handles user authentication, quiz generation, and result tracking
"""

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
import hashlib
import uuid
import sqlite3
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow cross-origin requests
app.secret_key = 'quiz-app-secret-key-2026'  # For session management

# Database files
USERS_DB = 'users.json'
DB_FILE = 'quizzes.db'
QUIZ_RESULTS_DIR = 'results'

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db()
    cursor = conn.cursor()

    # Create quizzes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            questions_json TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create quiz_attempts table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            score TEXT NOT NULL,
            percentage TEXT NOT NULL,
            attempt_data_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
        )
    ''')

    # Create official_exams table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS official_exams (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            subject TEXT NOT NULL,
            paper TEXT NOT NULL,
            date TEXT NOT NULL,
            data_json_path TEXT NOT NULL,
            er_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create official_exam_progress table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS official_exam_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            paper_id TEXT NOT NULL,
            current_question_idx INTEGER DEFAULT 0,
            answers_json TEXT,
            status TEXT DEFAULT 'started',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (paper_id) REFERENCES official_exams (id)
        )
    ''')

    # Insert default exam if table is empty
    cursor.execute("SELECT COUNT(*) FROM official_exams")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO official_exams (id, title, subject, paper, date, data_json_path)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            'biology_2B_nov_2025', 
            'Pearson Edexcel International GCSE (9–1) Friday 14 November 2025 Biology Paper 2B',
            'Biology', '2B', 'Nov 2025', 'exam_data/biology_2B_nov_2025.json'
        ))

    conn.commit()
    conn.close()



def load_users():
    """Load users from JSON file"""
    if os.path.exists(USERS_DB):
        with open(USERS_DB, 'r') as f:
            return json.load(f)
    return {}


def save_users(users):
    """Save users to JSON file"""
    with open(USERS_DB, 'w') as f:
        json.dump(users, f, indent=2)


def hash_password(password):
    """Simple password hashing"""
    return hashlib.sha256(password.encode()).hexdigest()


# Initialize users database with admin user
if not os.path.exists(USERS_DB):
    users = {
        'admin': {
            'password': hash_password('pass123'),
            'role': 'admin',
            'created_at': datetime.now().isoformat(),
            'quizzes_taken': 0
        }
    }
    save_users(users)
else:
    # Ensure admin user exists
    users = load_users()
    if 'admin' not in users:
        users['admin'] = {
            'password': hash_password('pass123'),
            'role': 'admin',
            'created_at': datetime.now().isoformat(),
            'quizzes_taken': 0
        }
        save_users(users)


# Ensure results directory exists
os.makedirs(QUIZ_RESULTS_DIR, exist_ok=True)


@app.route('/')
def index():
    """Serve the exam generator HTML"""
    return send_from_directory('.', 'exam_generator_v2.html')


@app.route('/quiz_template.html')
def quiz_template():
    """Serve the quiz template"""
    return send_from_directory('.', 'quiz_template.html')


@app.route('/register.html')
def register_page():
    """Serve the registration page"""
    return send_from_directory('.', 'register.html')


@app.route('/login.html')
def login_page():
    """Serve the login page"""
    return send_from_directory('.', 'login.html')


@app.route('/admin_login.html')
def admin_login_page():
    """Serve the admin login page"""
    return send_from_directory('.', 'admin_login.html')


import PyPDF2
from pdf2image import convert_from_path

@app.route('/admin_users.html')
def admin_users_page():
    """Serve the admin user management page"""
    return send_from_directory('.', 'admin_users.html')


@app.route('/admin_exams.html')
def admin_exams_page():
    """Serve the official exam management page"""
    return send_from_directory('.', 'admin_exams.html')


@app.route('/exam_questions.html')
def exam_questions_page():
    """Serve the official exam list page (Gallery)"""
    return send_from_directory('.', 'exam_questions.html')


@app.route('/official_exam_player.html')
def official_exam_player_page():
    """Serve the interactive official exam player"""
    return send_from_directory('.', 'official_exam_player.html')


@app.route('/api/official-exams/list')
def list_official_exams():
    """List available official exam papers from database"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, subject, paper, date FROM official_exams ORDER BY created_at DESC")
        exams = cursor.fetchall()
        conn.close()
        
        return jsonify({
            'success': True,
            'exams': [dict(e) for e in exams]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/official-exams/<paper_id>')
def get_official_exam(paper_id):
    """Get the structured data for a specific official exam"""
    data_path = f'exam_data/{paper_id}.json'
    if os.path.exists(data_path):
        with open(data_path, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({'error': 'Exam not found'}), 404

def extract_pdf_text(filepath):
    """Extract full text from a PDF file with page markers"""
    try:
        with open(filepath, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for i, page in enumerate(reader.pages):
                text += f"--- PAGE {i+1} ---\n"
                text += page.extract_text() + "\n"
            return text
    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/api/admin/list-files', methods=['POST'])
def list_server_files():
    """List PDF files recursively in a server directory for the admin browser"""
    try:
        data = request.json
        dir_path = data.get('dir_path', '/home/obo/playground/examQ/resources/igcse_edxcel_exampapers/biology/')
        admin_username = data.get('admin_username')

        # Verify admin
        users = load_users()
        if admin_username not in users or users[admin_username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        if not os.path.exists(dir_path):
            return jsonify({'success': False, 'message': 'Directory not found'}), 404

        files = []
        # Recursive walk
        for root, dirs, filenames in os.walk(dir_path):
            for f in sorted(filenames):
                if f.endswith('.pdf'):
                    full_path = os.path.join(root, f)
                    files.append({
                        'name': f,
                        'path': full_path,
                        'size': f"{os.path.getsize(full_path) / 1024 / 1024:.2f} MB"
                    })

        return jsonify({'success': True, 'files': files, 'current_dir': dir_path}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/process-exam', methods=['POST'])
def process_official_exam():
    """Intelligently process a new official exam paper from PDF paths"""
    try:
        data = request.json
        qp_path = data.get('qp_path')
        ms_path = data.get('ms_path')
        er_path = data.get('er_path') # Optional Examiner Report
        admin_username = data.get('admin_username')

        if not qp_path or not ms_path:
            return jsonify({'success': False, 'message': 'Both QP and MS paths are required'}), 400

        # Verify admin
        users = load_users()
        if admin_username not in users or users[admin_username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        if not os.path.exists(qp_path) or not os.path.exists(ms_path):
            return jsonify({'success': False, 'message': 'PDF files not found on server'}), 400

        # 1. Extract Text
        qp_text = extract_pdf_text(qp_path)
        ms_text = extract_pdf_text(ms_path)
        er_text = ""
        if er_path and os.path.exists(er_path):
            er_text = extract_pdf_text(er_path)

        # 2. Use LLaMA to determine Metadata
        meta_prompt = f"""Analyze this IGCSE exam paper header text and return JSON metadata.
TEXT:
{qp_text[:2000]}

JSON FORMAT:
{{
  "id": "subject_paper_date_slug",
  "title": "Full Exam Title",
  "subject": "Biology/Physics/Math/English",
  "paper": "1B/2B/1/2/etc",
  "date": "Month Year"
}}
"""
        meta_resp = requests.post('http://localhost:11434/api/generate', json={
            'model': 'llama3', 'prompt': meta_prompt, 'stream': False, 'format': 'json', 'temperature': 0
        })
        metadata = json.loads(meta_resp.json().get('response', '{}'))
        paper_id = metadata.get('id', str(uuid.uuid4())[:8])

        # CHECK FOR DUPLICATE
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM official_exams WHERE id = ?", (paper_id,))
        exists = cursor.fetchone()
        conn.close()

        if exists:
            return jsonify({
                'success': True, 
                'message': f'Skipped "{metadata.get("title")}" - Already in library.',
                'paper_id': paper_id,
                'skipped': True
            }), 200

        # 3. Use LLaMA to generate Question Mapping
        map_prompt = f"""Analyze this IGCSE exam paper and its mark scheme. 
Generate a mapping of each main question to its page numbers and the relevant mark scheme text.

QP TEXT SNIPPET:
{qp_text[:5000]}

MS TEXT SNIPPET:
{ms_text[:5000]}

JSON FORMAT (STRICT):
{{
  "questions": [
    {{
      "id": 1,
      "sub_questions": [
        {{
          "sub_id": "1(a)",
          "type": "mcq", 
          "options": ["A", "B", "C", "D"],
          "qp_pages": [2],
          "ms_text": "Exact mark scheme answer",
          "max_marks": 1
        }},
        {{
          "sub_id": "1(b)",
          "type": "text",
          "qp_pages": [2],
          "ms_text": "Detailed mark scheme points",
          "max_marks": 2
        }}
      ]
    }}
  ]
}}

TYPE RULES:
- Use "mcq" ONLY if the question has A,B,C,D options. ALWAYS include "options": ["A", "B", "C", "D"] for these.
- Use "calculation" for multi-mark math questions.
- Use "list" for "Name two..." type questions.
- Use "text" for all others (especially long English answers).
"""
        map_resp = requests.post('http://localhost:11434/api/generate', json={
            'model': 'llama3', 'prompt': map_prompt, 'stream': False, 'format': 'json', 'temperature': 0
        })
        mapping_data = json.loads(map_resp.json().get('response', '{"questions": []}'))

        # 4. Convert PDF to Images
        qp_img_dir = f"static/exams/{paper_id}/qp"
        os.makedirs(qp_img_dir, exist_ok=True)
        images = convert_from_path(qp_path, dpi=150)
        for i, image in enumerate(images):
            image.save(os.path.join(qp_img_dir, f"page_{i+1:02d}.png"), 'PNG')

        # 5. Save Final JSON
        final_data = {
            "paper_id": paper_id,
            "title": metadata.get('title'),
            "subject": metadata.get('subject'),
            "qp_img_dir": f"/{qp_img_dir}/",
            "er_text": er_text,
            "questions": mapping_data.get('questions', [])
        }
        json_path = f"exam_data/{paper_id}.json"
        os.makedirs('exam_data', exist_ok=True)
        with open(json_path, 'w') as f:
            json.dump(final_data, f, indent=2)

        # 6. Add to Database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO official_exams (id, title, subject, paper, date, data_json_path, er_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            paper_id, metadata.get('title'), metadata.get('subject'), 
            metadata.get('paper'), metadata.get('date'), json_path, er_text
        ))
        conn.commit()
        conn.close()

        return jsonify({
            'success': True, 
            'message': f'Exam "{metadata.get("title")}" processed!',
            'paper_id': paper_id
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Process Error: {str(e)}"}), 500

@app.route('/api/admin/delete-exam', methods=['POST'])
def delete_official_exam():
    """Remove an official exam from the library"""
    try:
        data = request.json
        paper_id = data.get('paper_id')
        admin_username = data.get('admin_username')

        # Verify admin
        users = load_users()
        if admin_username not in users or users[admin_username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM official_exams WHERE id = ?", (paper_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'Exam deleted'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/official-exams/grade', methods=['POST'])
def grade_official_question():
    """Grade a user's answer using LLaMA and the official mark scheme"""
    try:
        data = request.json
        paper_id = data.get('paper_id')
        question_id = data.get('question_id')
        sub_id = data.get('sub_id')
        user_answer = data.get('user_answer')
        mark_scheme = data.get('mark_scheme')
        max_marks = data.get('max_marks', 1)

        # Get Examiner Report if available
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT er_text FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone()
        er_text = row['er_text'] if row and row['er_text'] else ""
        conn.close()

        # Prompt for LLaMA
        prompt = f"""You are an expert IGCSE Edexcel Examiner. 
Your task is to mark a student's answer based STRICTLY on the official Mark Scheme provided.

PAPER ID: {paper_id}
QUESTION: {sub_id}
MAX MARKS: {max_marks}

OFFICIAL MARK SCHEME:
{mark_scheme}

EXAMINER REPORT (REAL-WORLD ADVICE):
{er_text[:3000]}

STUDENT'S ANSWER:
{user_answer}

MARKING INSTRUCTIONS:
1. MANDATORY: If the student's answer is blank, award 0 marks.
2. Award marks (0 to {max_marks}) based on the "OFFICIAL MARK SCHEME".
3. Use the "EXAMINER REPORT" to provide high-quality feedback on what examiners are actually looking for.
4. If the student did not receive full marks, you MUST provide a "MODEL ANSWER" based on the mark scheme.

RESPONSE FORMAT (JSON ONLY):
{{
  "marks_awarded": 0,
  "max_marks": {max_marks},
  "feedback": "Evaluation. \n\nMODEL ANSWER: [Correct steps]",
  "marking_points_met": []
}}
"""

        # Call local Ollama
        response = requests.post('http://localhost:11434/api/generate', json={
            'model': 'llama3',
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            'temperature': 0.0
        })

        if response.status_code == 200:
            result = response.json().get('response', '{}')
            return jsonify(json.loads(result)), 200
        else:
            return jsonify({'error': 'Failed to connect to LLaMA'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/student/exam-progress/save', methods=['POST'])
def save_exam_progress():
    """Save student's current progress on an official exam"""
    try:
        data = request.json
        username = data.get('username')
        paper_id = data.get('paper_id')
        current_idx = data.get('current_question_idx', 0)
        answers = data.get('answers', {})

        if not username or not paper_id:
            return jsonify({'success': False, 'message': 'Missing data'}), 400

        conn = get_db()
        cursor = conn.cursor()
        
        # Check if record exists
        cursor.execute("SELECT id FROM official_exam_progress WHERE username = ? AND paper_id = ?", (username, paper_id))
        row = cursor.fetchone()
        
        if row:
            cursor.execute('''
                UPDATE official_exam_progress 
                SET current_question_idx = ?, answers_json = ?, last_updated = CURRENT_TIMESTAMP
                WHERE username = ? AND paper_id = ?
            ''', (current_idx, json.dumps(answers), username, paper_id))
        else:
            cursor.execute('''
                INSERT INTO official_exam_progress (username, paper_id, current_question_idx, answers_json)
                VALUES (?, ?, ?, ?)
            ''', (username, paper_id, current_idx, json.dumps(answers)))
            
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/student/exam-progress/get', methods=['GET'])
def get_exam_progress():
    """Retrieve saved progress for a specific student and paper"""
    try:
        username = request.args.get('username')
        paper_id = request.args.get('paper_id')
        
        if not username or not paper_id:
            return jsonify({'success': False}), 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT current_question_idx, answers_json, status 
            FROM official_exam_progress 
            WHERE username = ? AND paper_id = ?
        ''', (username, paper_id))
        row = cursor.fetchone()
        conn.close()

        if row:
            return jsonify({
                'success': True,
                'current_question_idx': row['current_question_idx'],
                'answers': json.loads(row['answers_json'] or '{}'),
                'status': row['status']
            }), 200
        else:
            return jsonify({'success': False, 'message': 'No progress found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/student/exam-progress/list', methods=['GET'])
def list_student_progress():
    """List progress for all official exams for a specific student"""
    try:
        username = request.args.get('username')
        if not username:
            return jsonify({'success': False}), 400

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT paper_id, status, last_updated, current_question_idx 
            FROM official_exam_progress 
            WHERE username = ?
        ''', (username,))
        rows = cursor.fetchall()
        conn.close()

        progress = {r['paper_id']: {
            'status': r['status'],
            'last_updated': r['last_updated'],
            'current_question_idx': r['current_question_idx']
        } for r in rows}

        return jsonify({'success': True, 'progress': progress}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/student/exam-progress/complete', methods=['POST'])
def complete_exam_progress():
    """Mark an exam as completed"""
    try:
        data = request.json
        username = data.get('username')
        paper_id = data.get('paper_id')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE official_exam_progress 
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP, last_updated = CURRENT_TIMESTAMP
            WHERE username = ? AND paper_id = ?
        ''', (username, paper_id))
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.json
        username = (data.get('username') or '').strip().lower()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password required'}), 400

        if len(username) < 3:
            return jsonify({'success': False, 'message': 'Username must be at least 3 characters'}), 400

        users = load_users()

        if username in users:
            return jsonify({'success': False, 'message': 'Username already exists'}), 400

        # Create new user
        users[username] = {
            'password': hash_password(password),
            'created_at': datetime.now().isoformat(),
            'quizzes_taken': 0
        }

        save_users(users)

        return jsonify({'success': True, 'message': 'Registration successful! Please login.'}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/login', methods=['POST'])
def login():
    """Authenticate user"""
    try:
        data = request.json
        username = (data.get('username') or '').strip().lower()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'success': False, 'message': 'Username and password required'}), 400

        users = load_users()

        if username not in users:
            return jsonify({'success': False, 'message': 'Invalid username or password'}), 401

        if users[username]['password'] != hash_password(password):
            return jsonify({'success': False, 'message': 'Invalid username or password'}), 401

        return jsonify({
            'success': True,
            'message': 'Login successful!',
            'username': username,
            'role': users[username].get('role', 'student')
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/change-password', methods=['POST'])
def change_password():
    """Change user password"""
    try:
        data = request.json
        username = (data.get('username') or '').strip().lower()
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')

        if not username or not old_password or not new_password:
            return jsonify({'success': False, 'message': 'All fields required'}), 400

        users = load_users()

        if username not in users:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if users[username]['password'] != hash_password(old_password):
            return jsonify({'success': False, 'message': 'Current password incorrect'}), 401

        users[username]['password'] = hash_password(new_password)
        save_users(users)

        return jsonify({'success': True, 'message': 'Password changed successfully!'}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    """Reset password (simple - just returns a new random password)"""
    try:
        data = request.json
        username = (data.get('username') or '').strip().lower()

        if not username:
            return jsonify({'success': False, 'message': 'Username required'}), 400

        users = load_users()

        if username not in users:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        # Generate a simple random password
        new_password = ''.join(str(uuid.uuid4())[:8])
        users[username]['password'] = hash_password(new_password)
        save_users(users)

        return jsonify({
            'success': True,
            'message': f'Password reset! New password: {new_password}',
            'new_password': new_password
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/submit-quiz', methods=['POST'])
def submit_quiz():
    """Receive and save quiz results"""
    try:
        data = request.json
        username = data.get('username', '')
        topic = data.get('topic', 'Quiz')
        score = data.get('score', '0 / 0')
        percentage = data.get('percentage', '0%')
        questions = data.get('questions', [])
        quiz_id = data.get('quiz_id')  # Optional: if retaking a saved quiz

        if not username:
            return jsonify({'success': False, 'message': 'Username required'}), 400

        # Create date directory
        date_dir = os.path.join(QUIZ_RESULTS_DIR, datetime.now().strftime('%Y-%m-%d'))
        os.makedirs(date_dir, exist_ok=True)

        # Create filename
        timestamp = datetime.now().strftime('%H%M%S')
        topic_slug = topic.lower().replace(' ', '_').replace('/', '_').replace('?', '')
        filename = f"{topic_slug}_{timestamp}_{username}.json"
        filepath = os.path.join(date_dir, filename)

        # Save quiz results
        quiz_data = {
            'username': username,
            'topic': topic,
            'score': score,
            'percentage': percentage,
            'timestamp': datetime.now().isoformat(),
            'questions': questions
        }

        with open(filepath, 'w') as f:
            json.dump(quiz_data, f, indent=2)

        # Save to database if quiz_id is provided
        if quiz_id:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO quiz_attempts (quiz_id, username, score, percentage, answers_json)
                VALUES (?, ?, ?, ?, ?)
            ''', (quiz_id, username, score, percentage, json.dumps(questions)))
            conn.commit()
            conn.close()

        # Update user's quiz count
        users = load_users()
        if username in users:
            users[username]['quizzes_taken'] = users[username].get('quizzes_taken', 0) + 1
            save_users(users)

        return jsonify({
            'success': True,
            'message': 'Quiz submitted successfully!'
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/save-quiz', methods=['POST'])
def save_quiz_to_db():
    """Save a generated quiz to the database"""
    try:
        data = request.json
        topic = data.get('topic', '')
        questions = data.get('questions', [])
        created_by = data.get('created_by', '')

        if not topic or not questions:
            return jsonify({'success': False, 'message': 'Topic and questions required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO quizzes (topic, questions_json, created_by)
            VALUES (?, ?, ?)
        ''', (topic, json.dumps(questions), created_by))

        quiz_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'quiz_id': quiz_id,
            'message': 'Quiz saved successfully!'
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/quizzes/list', methods=['GET'])
def get_all_quizzes_list():
    """Get all available quizzes for users to take"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, topic, created_by, created_at
            FROM quizzes
            ORDER BY created_at DESC
        ''', )
        quizzes = cursor.fetchall()
        conn.close()

        return jsonify({
            'success': True,
            'quizzes': [dict(q) for q in quizzes]
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/my-quizzes', methods=['GET'])
def get_my_quizzes():
    """Get quiz history for a specific student"""
    try:
        username = request.args.get('username', '')

        if not username:
            return jsonify({'success': False, 'message': 'Username required'}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get all quizzes created by this user
        cursor.execute('''
            SELECT id, topic, created_at
            FROM quizzes
            WHERE created_by = ?
            ORDER BY created_at DESC
        ''', (username,))
        quizzes = cursor.fetchall()

        # Get all attempts by this user with scores
        cursor.execute('''
            SELECT qa.quiz_id, q.topic, qa.score, qa.percentage, qa.timestamp
            FROM quiz_attempts qa
            JOIN quizzes q ON qa.quiz_id = q.id
            WHERE qa.username = ?
            ORDER BY qa.timestamp DESC
        ''', (username,))
        attempts = cursor.fetchall()

        conn.close()

        return jsonify({
            'success': True,
            'created_quizzes': [dict(q) for q in quizzes],
            'attempts': [dict(a) for a in attempts]
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/quiz/<int:quiz_id>', methods=['GET'])
def get_quiz(quiz_id):
    """Get a specific quiz by ID for retaking"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, topic, questions_json, created_by, created_at
            FROM quizzes
            WHERE id = ?
        ''', (quiz_id,))
        quiz = cursor.fetchone()

        conn.close()

        if not quiz:
            return jsonify({'success': False, 'message': 'Quiz not found'}), 404

        return jsonify({
            'success': True,
            'quiz': {
                'id': quiz['id'],
                'topic': quiz['topic'],
                'questions': json.loads(quiz['questions_json']),
                'created_by': quiz['created_by'],
                'created_at': quiz['created_at']
            }
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/results')
def results_dashboard():
    """Teacher dashboard to view all results - requires admin login"""
    return send_from_directory('.', 'results_dashboard.html')


@app.route('/api/verify-admin', methods=['POST'])
def verify_admin():
    """Verify if user is admin"""
    try:
        data = request.json
        username = data.get('username', '')

        users = load_users()

        if username not in users:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if users[username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403

        return jsonify({'success': True, 'message': 'Admin verified'}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/results')
def get_results():
    """Get quiz results for the dashboard. Admins see all, users see only their own."""
    try:
        username = request.args.get('username', '')
        
        if not username:
            return jsonify({'results': []}), 200

        # Load users to check role
        users = load_users()
        is_admin = False
        if username in users and users[username].get('role') == 'admin':
            is_admin = True

        results = []

        # Walk through results directory
        if os.path.exists(QUIZ_RESULTS_DIR):
            for date_dir in sorted(os.listdir(QUIZ_RESULTS_DIR), reverse=True):
                date_path = os.path.join(QUIZ_RESULTS_DIR, date_dir)
                if os.path.isdir(date_path):
                    for filename in os.listdir(date_path):
                        if filename.endswith('.json'):
                            filepath = os.path.join(date_path, filename)
                            with open(filepath, 'r') as f:
                                try:
                                    quiz_data = json.load(f)
                                    # Filter: if admin, show all. If not admin, only show matching username.
                                    if is_admin or quiz_data.get('username') == username:
                                        results.append(quiz_data)
                                except (json.JSONDecodeError, IOError):
                                    continue

        return jsonify({'results': results}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/admin/users', methods=['POST'])
def get_admin_users():
    """Get all users for admin dashboard"""
    try:
        data = request.json
        admin_username = data.get('admin_username', '')

        users = load_users()

        if admin_username not in users or users[admin_username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403

        safe_users = {}
        for username, user_data in users.items():
            safe_users[username] = {
                'role': user_data.get('role', 'student'),
                'created_at': user_data.get('created_at', ''),
                'quizzes_taken': user_data.get('quizzes_taken', 0)
            }

        return jsonify({'success': True, 'users': safe_users}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/api/admin/update-user', methods=['POST'])
def admin_update_user():
    """Admin update user (username or password)"""
    try:
        data = request.json
        admin_username = data.get('admin_username', '')
        old_username = data.get('old_username', '')
        new_username = (data.get('new_username') or '').strip().lower()
        new_password = data.get('new_password', '')

        users = load_users()

        if admin_username not in users or users[admin_username].get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403

        if old_username not in users:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        if new_password:
            users[old_username]['password'] = hash_password(new_password)

        if new_username and new_username != old_username:
            if new_username in users:
                return jsonify({'success': False, 'message': 'New username already exists'}), 400

            users[new_username] = users.pop(old_username)
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('UPDATE quizzes SET created_by = ? WHERE created_by = ?', (new_username, old_username))
            cursor.execute('UPDATE quiz_attempts SET username = ? WHERE username = ?', (new_username, old_username))
            conn.commit()
            conn.close()

        save_users(users)

        return jsonify({'success': True, 'message': 'User updated successfully'}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500

# Email functionality removed - results now saved to database for admin to view
# @app.route('/send-results', methods=['POST'])
# def send_results():
#     ...


@app.route('/save-quiz', methods=['POST'])
def save_quiz():
    """Save quiz HTML to project directory"""
    try:
        data = request.json
        html = data.get('html', '')
        filename = data.get('filename', 'quiz.html')

        # Save to current directory (project root)
        filepath = os.path.join(os.path.dirname(__file__), filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        return jsonify({
            'success': True,
            'message': f'Quiz saved to {filepath}',
            'filepath': filepath
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': f"Error: {str(e)}"}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200


import socket

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    local_ip = get_local_ip()
    print("=" * 60)
    print("🎓 Quiz Server with Login")
    print("=" * 60)
    print(f"\nServer will run on: http://{local_ip}:5001")
    print(f"\n✓ User registration: ENABLED")
    print(f"✓ Login required: ENABLED")
    print(f"✓ Quiz tracking: ENABLED")
    print(f"✓ Results saved to: {QUIZ_RESULTS_DIR}/")
    print(f"✓ Database: {DB_FILE}")
    print(f"\nPages:")
    print(f"  - Student Login:  http://{local_ip}:5001/login.html")
    print(f"  - Student Register: http://{local_ip}:5001/register.html")
    print(f"  - Quiz Generator: http://{local_ip}:5001/")
    print(f"  - Admin Login:    http://{local_ip}:5001/admin_login.html")
    print(f"  - Admin Dashboard: http://{local_ip}:5001/results")
    print(f"  - Admin Users:    http://{local_ip}:5001/admin_users.html")
    print(f"\nAdmin credentials:")
    print(f"  Username: admin")
    print(f"  Password: pass123")
    print(f"\nStarting server...\n")

    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=True)
