#!/usr/bin/env python3
"""
Quiz Server with User Management
Handles user authentication, quiz generation, and result tracking
"""

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
            answers_json TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
        )
    ''')

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


@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.json
        username = data.get('username', '').strip().lower()
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
        username = data.get('username', '').strip().lower()
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
        username = data.get('username', '').strip().lower()
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
        username = data.get('username', '').strip().lower()

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
    """Get all quiz results for the dashboard"""
    try:
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
                                quiz_data = json.load(f)
                                results.append(quiz_data)

        return jsonify({'results': results}), 200

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


if __name__ == '__main__':
    print("=" * 60)
    print("🎓 Quiz Server with Login")
    print("=" * 60)
    print(f"\nServer will run on: http://localhost:5001")
    print(f"\n✓ User registration: ENABLED")
    print(f"✓ Login required: ENABLED")
    print(f"✓ Quiz tracking: ENABLED")
    print(f"✓ Results saved to: {QUIZ_RESULTS_DIR}/")
    print(f"✓ Database: {DB_FILE}")
    print(f"\nPages:")
    print(f"  - Student Login:  http://localhost:5001/login.html")
    print(f"  - Student Register: http://localhost:5001/register.html")
    print(f"  - Quiz Generator: http://localhost:5001/")
    print(f"  - Admin Login:    http://localhost:5001/admin_login.html")
    print(f"  - Admin Dashboard: http://localhost:5001/results")
    print(f"\nAdmin credentials:")
    print(f"  Username: admin")
    print(f"  Password: pass123")
    print(f"\nStarting server...\n")

    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=True)
