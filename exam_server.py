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
import random
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
AI_PLAYERS = ['Bob', 'Tim']

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_sessions (
            id TEXT PRIMARY KEY,
            game_type TEXT NOT NULL,
            host_username TEXT NOT NULL,
            players_json TEXT NOT NULL, -- List of {username, status: 'invited'|'accepted'}
            state_json TEXT, -- Current game state (word, guessed letters, etc)
            status TEXT DEFAULT 'pending', -- 'pending', 'active', 'finished'
            version INTEGER DEFAULT 0,
            logs_json TEXT DEFAULT '[]',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME
        )
    ''')
    # Check for logs_json column
    cursor.execute("PRAGMA table_info(game_sessions)")
    game_cols = [row['name'] for row in cursor.fetchall()]
    if game_cols and 'logs_json' not in game_cols:
        cursor.execute("ALTER TABLE game_sessions ADD COLUMN logs_json TEXT DEFAULT '[]'")
    if game_cols and 'version' not in game_cols:
        cursor.execute("ALTER TABLE game_sessions ADD COLUMN version INTEGER DEFAULT 0")
    if game_cols and 'expires_at' not in game_cols:
        cursor.execute("ALTER TABLE game_sessions ADD COLUMN expires_at DATETIME")
    
    conn.commit()
    
    cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES ('admin', 'pass123', 'admin')")
    for ai in AI_PLAYERS:
        cursor.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, 'ai_player', 'student')", (ai,))
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

# --- GAME API ---

@app.route('/api/games/leave', methods=['POST'])
def leave_game_session():
    try:
        data = request.json
        session_id = data.get('session_id')
        username = data.get('username')
        
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT players_json, host_username, status FROM game_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row: return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        players = json.loads(row['players_json'])
        # Filter out the leaving player
        new_players = [p for p in players if p['username'] != username]
        
        if row['host_username'] == username:
            # If host leaves, delete the session
            cursor.execute("DELETE FROM game_sessions WHERE id = ?", (session_id,))
        else:
            # If guest leaves, just update players list
            cursor.execute("UPDATE game_sessions SET players_json = ?, version = version + 1 WHERE id = ?", (json.dumps(new_players), session_id))
            
        conn.commit(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/create', methods=['POST'])
def game_create():
    try:
        data = request.json
        host = data.get('host')
        game_type = data.get('game_type')
        if not host or not game_type: return jsonify({'error': 'Missing data'}), 400
        
        conn = get_db(); cursor = conn.cursor()
        
        # Check if user already has an active session
        cursor.execute("SELECT id FROM game_sessions WHERE host_username = ? AND status != 'finished'", (host,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': 'You already have an active game session. Please finish or delete it first.'}), 400

        session_id = str(uuid.uuid4())[:8]
        players = [{'username': host, 'status': 'accepted'}]
            
        cursor.execute(
            "INSERT INTO game_sessions (id, game_type, host_username, players_json, status, expires_at, logs_json) VALUES (?, ?, ?, ?, ?, datetime('now', '+10 minutes'), '[]')",
            (session_id, game_type, host, json.dumps(players), 'pending')
        )
        conn.commit(); conn.close()
        return jsonify({'success': True, 'session_id': session_id}), 201
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/invite', methods=['POST'])
def game_invite():
    try:
        data = request.json
        host = data.get('host')
        game_type = data.get('game_type')
        invitees = data.get('invitees', []) # List of usernames
        session_id = data.get('session_id') # Optional: invite to existing session
        
        if not host: return jsonify({'error': 'Missing host'}), 400
        
        conn = get_db(); cursor = conn.cursor()
        
        if not session_id:
            session_id = str(uuid.uuid4())[:8]
            players = [{'username': host, 'status': 'accepted'}]
            for u in invitees:
                players.append({'username': u, 'status': 'invited'})
            cursor.execute(
                "INSERT INTO game_sessions (id, game_type, host_username, players_json, status, expires_at, logs_json) VALUES (?, ?, ?, ?, ?, datetime('now', '+10 minutes'), '[]')",
                (session_id, game_type, host, json.dumps(players), 'pending')
            )
        else:
            # Adding invitees to existing session
            cursor.execute("SELECT players_json FROM game_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row: return jsonify({'error': 'Session not found'}), 404
            players = json.loads(row['players_json'])
            existing_users = [p['username'] for p in players]
            for u in invitees:
                if u not in existing_users:
                    status = 'accepted' if u in AI_PLAYERS else 'invited'
                    players.append({'username': u, 'status': status})
            cursor.execute("UPDATE game_sessions SET players_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(players), session_id))
        
        # Send messages to invitees
        invite_msg = f"🎮 {host} invited you to play {game_type}! Click here to join: {request.host_url}games.html?join={session_id}"
        for u in invitees:
            # Check length just in case host name or game type is somehow massive
            m_safe = invite_msg[:10000]
            cursor.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", ('System', u, m_safe))
            
        conn.commit(); conn.close()
        trigger_ai_if_needed(session_id)
        return jsonify({'success': True, 'session_id': session_id}), 201
    except Exception as e: return jsonify({'error': str(e)}), 500

def log_game_action(cursor, session_id, message):
    cursor.execute("SELECT logs_json FROM game_sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    logs = []
    if row and row['logs_json']:
        try:
            logs = json.loads(row['logs_json'])
        except:
            logs = []
    
    logs.insert(0, {'msg': message, 'time': int(datetime.now().timestamp())})
    # Keep last 50 logs
    cursor.execute("UPDATE game_sessions SET logs_json = ? WHERE id = ?", (json.dumps(logs[:50]), session_id))

def fmt_name(s):
    if not s: return ""
    # Capitalize first letter
    name = s[0].upper() + s[1:] if len(s) > 0 else ""
    # Truncate
    truncated = name[:10] + "..." if len(name) > 10 else name
    return f"<b>{truncated}</b>"

def get_next_uno_turn(order, current_idx, direction, finishers):
    """Calculate next player, skipping those who have finished."""
    idx = current_idx
    for _ in range(len(order)):
        idx = (idx + direction + len(order)) % len(order)
        if order[idx] not in finishers:
            return order[idx]
    return order[current_idx]

def check_uno_game_over(state, order):
    """Check if only one player is left and set winner/loser."""
    finishers = state.get('finishers', [])
    finishers_lower = [f.lower() for f in finishers]
    
    # Robust hand count lookup (case-insensitive keys)
    hands = state.get('hands', {})
    hand_counts = {k.lower(): len(v) for k, v in hands.items()}
    
    # A player is remaining if:
    # 1. They are NOT in the finishers list
    # 2. They still have cards in their hand
    remaining = []
    for u in order:
        u_lower = u.lower()
        count = hand_counts.get(u_lower, 0)
        if u_lower not in finishers_lower and count > 0:
            remaining.append(u)
    
    if len(remaining) <= 1:
        # The winner is the first person who finished.
        state['winner'] = finishers[0] if finishers else (state.get('lastFinisher') or "Unknown")
        # The loser is the lone person left with cards, or the last person in order
        state['loser'] = remaining[0] if remaining else (order[-1] if order else "Unknown")
        state['status'] = 'finished'
        return True
    return False

def apply_uno_move(state, action, username, params):
    """Centralized UNO logic for both AI and Humans"""
    order = state.get('playersOrder', [])
    if not order: return state, "Invalid game state"
    
    current_turn = state.get('currentTurn')
    if action != 'CALL_UNO' and (not current_turn or current_turn.lower() != username.lower()):
        return state, f"Not your turn (Current: {current_turn})"

    # Case-insensitive index lookup
    order_lower = [o.lower() for o in order]
    if current_turn.lower() not in order_lower:
        return state, "Current player not in turn order"
    curr_idx = order_lower.index(username.lower())

    new_state = json.loads(json.dumps(state)) # Deep copy
    if 'finishers' not in new_state: new_state['finishers'] = []
    
    # Pre-action cleanup: solidified winners
    if action in ['DRAW_CARD', 'PLAY_CARD', 'SELECT_COLOR'] and new_state.get('vulnerableWin'):
        lf = new_state.get('lastFinisher')
        if lf and lf not in new_state['finishers']: new_state['finishers'].append(lf)
        new_state.pop('vulnerableWin', None); new_state.pop('lastFinisher', None)
    
    if action == 'CALL_UNO':
        if 'unoCalls' not in new_state: new_state['unoCalls'] = []
        if username not in new_state['unoCalls']: new_state['unoCalls'].append(username)
        return new_state, None

    if action == 'DISPUTE':
        if not new_state.get('vulnerableWin'): return state, "No vulnerable win"
        target = new_state.get('lastFinisher')
        for _ in range(2):
            if not new_state['deck'] and len(new_state['discard']) > 1:
                top_c = new_state['discard'].pop(); random.shuffle(new_state['discard'])
                new_state['deck'] = new_state['discard']; new_state['discard'] = [top_c]
            if new_state['deck']: new_state['hands'][target].append(new_state['deck'].pop())
        new_state.pop('vulnerableWin', None); new_state.pop('lastFinisher', None)
        check_uno_game_over(new_state, order)
        return new_state, None

    if action == 'DRAW_CARD':
        if not new_state['deck']:
            if len(new_state['discard']) > 1:
                top = new_state['discard'].pop(); random.shuffle(new_state['discard'])
                new_state['deck'] = new_state['discard']; new_state['discard'] = [top]
            else: return state, "No cards left"
        
        card = new_state['deck'].pop()
        new_state['hands'][username].append(card)
        if 'unoCalls' in new_state and username in new_state['unoCalls'] and len(new_state['hands'][username]) > 1:
            new_state['unoCalls'].remove(username)
        
        top = new_state['discard'][-1]
        cur_color = new_state.get('currentColor', top['color'])
        can_p = card['color'] == 'black' or card['color'] == cur_color or card['value'] == top['value']
        
        if not can_p:
            new_state['currentTurn'] = get_next_uno_turn(order, curr_idx, new_state['direction'], new_state['finishers'])
        else: 
            new_state['justDrewPlayable'] = True

        check_uno_game_over(new_state, order)

    elif action == 'PLAY_CARD':
        card_idx = params.get('card_idx')
        if card_idx is None or card_idx >= len(new_state['hands'][username]): return state, "Invalid index"
        card = new_state['hands'][username].pop(card_idx)
        new_state['discard'].append(card)

        is_f = len(new_state['hands'][username]) == 0
        has_c = 'unoCalls' in new_state and username in new_state['unoCalls']

        if is_f:
            if has_c:
                if username not in new_state['finishers']:
                    new_state['finishers'].append(username)
                    if not new_state.get('winner'):
                        new_state['winner'] = username
            else:
                new_state['vulnerableWin'] = True; new_state['lastFinisher'] = username

        # If it's a black card and color is provided in same action
        if card['color'] == 'black' and params.get('color'):
            new_state['currentColor'] = params.get('color')
            card['color_selected'] = True # Marker for logging

        if card['color'] != 'black' or params.get('color'):
            if card['color'] != 'black':
                new_state['currentColor'] = card['color']

            step = 1
            val = card['value']
            if val == 'Reverse':

                if (len(order) - len(new_state['finishers'])) == 2: step = 2
                else: new_state['direction'] *= -1
            elif card['value'] == 'Skip': step = 2
            elif card['value'] == 'Draw2':
                victim = get_next_uno_turn(order, curr_idx, new_state['direction'], new_state['finishers'])
                for _ in range(2): 
                    if not new_state['deck'] and len(new_state['discard']) > 1:
                        top_c = new_state['discard'].pop(); random.shuffle(new_state['discard'])
                        new_state['deck'] = new_state['discard']; new_state['discard'] = [top_c]
                    if new_state['deck']: new_state['hands'][victim].append(new_state['deck'].pop())
                step = 2
                
            if check_uno_game_over(new_state, order):
                return new_state, None

            target_idx = curr_idx
            for _ in range(step):
                nxt = get_next_uno_turn(order, target_idx, new_state['direction'], new_state['finishers'])
                target_idx = order_lower.index(nxt.lower())
            new_state['currentTurn'] = nxt
        else:
            new_state['pendingColorSelection'] = True
            return new_state, None

    elif action == 'SELECT_COLOR':
        new_state['currentColor'] = params.get('color')
        new_state.pop('pendingColorSelection', None)
        if 'finishers' not in new_state: new_state['finishers'] = []
        
        top = new_state['discard'][-1]
        step = 1
        if top['value'] == 'WildDraw4':
            victim = get_next_uno_turn(order, curr_idx, new_state['direction'], new_state['finishers'])
            for _ in range(4):
                if not new_state['deck'] and len(new_state['discard']) > 1:
                    top_c = new_state['discard'].pop(); random.shuffle(new_state['discard'])
                    new_state['deck'] = new_state['discard']; new_state['discard'] = [top_c]
                if new_state['deck']: new_state['hands'][victim].append(new_state['deck'].pop())
            step = 2
            
        if len(new_state['hands'][username]) == 0 and not new_state.get('vulnerableWin'):
            if username not in new_state['finishers']: 
                new_state['finishers'].append(username)
                if not new_state.get('winner'):
                    new_state['winner'] = username

        if check_uno_game_over(new_state, order):
            return new_state, None

        target_idx = curr_idx
        for _ in range(step):
            nxt = get_next_uno_turn(order, target_idx, new_state['direction'], new_state['finishers'])
            target_idx = order_lower.index(nxt.lower())
        new_state['currentTurn'] = nxt

    new_state['updatedAt'] = int(datetime.now().timestamp() * 1000)
    return new_state, None

    new_state['updatedAt'] = int(datetime.now().timestamp() * 1000)
    return new_state, None

def apply_hangman_move(state, action, username, params):
    """Centralized Hangman logic"""
    if action == 'GUESS':
        letter = params.get('letter') # Can be None for timeout
        actor = username
        
        current_turn = state.get('currentTurn', '')
        if not current_turn or current_turn.lower() != actor.lower():
            return state, "Not your turn"
            
        new_state = json.loads(json.dumps(state))
        word = new_state.get('word', '').upper()
        
        if 'guessedLetters' not in new_state:
            new_state['guessedLetters'] = []
        if 'wrongGuesses' not in new_state:
            new_state['wrongGuesses'] = 0
            
        if letter:
            letter = letter.upper()
            if letter in [l.upper() for l in new_state['guessedLetters']]:
                return state, "Already guessed"
            new_state['guessedLetters'].append(letter)
            is_correct = letter in word
        else:
            is_correct = False # Timeout
            
        if not is_correct:
            new_state['wrongGuesses'] = new_state.get('wrongGuesses', 0) + 1
            
        is_won = all(c == ' ' or c.upper() in [l.upper() for l in new_state['guessedLetters']] for c in word)
        is_lost = new_state['wrongGuesses'] >= 6
        
        if is_won:
            new_state['winner'] = actor
            new_state['status'] = 'finished'
            return new_state, None
        if is_lost:
            new_state['status'] = 'finished'
            return new_state, None
            
        # Change turn if incorrect or timeout
        if not is_correct:
            players = new_state.get('playersOrder', [])
            if players:
                players_lower = [p.lower() for p in players]
                try:
                    current_idx = players_lower.index(actor.lower())
                except ValueError:
                    current_idx = 0
                    
                next_idx = (current_idx + 1) % len(players)
                
                host = params.get('host_username')
                if len(players) > 1 and host and players[next_idx].lower() == host.lower():
                    next_idx = (next_idx + 1) % len(players)
                
                new_state['currentTurn'] = players[next_idx]
                
        new_state['turnStartedAt'] = int(datetime.now().timestamp() * 1000)
        new_state['updatedAt'] = int(datetime.now().timestamp() * 1000)
        return new_state, None
    
    return state, "Unknown action"

def process_ai_action(session_id):
    """Handle AI player logic for Bob and Tim using Ollama"""
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM game_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row: return
        
        status = row['status']
        game_type = row['game_type']
        host = row['host_username']
        players = json.loads(row['players_json'])
        state = json.loads(row['state_json']) if row['state_json'] else {}
        current_turn = state.get('currentTurn')
        
        print(f"[AI-DEBUG] Session {session_id} | Type: {game_type} | Status: {status} | Host: {host} | Turn: {current_turn}")

        # --- LOBBY LOGIC (PENDING or STARTING) ---
        # AI auto-start from pending, OR manual start signal (from button)
        is_starting = (status == 'pending' and host in AI_PLAYERS) or (status == 'active' and state.get('starting'))
        
        if is_starting:
            accepted_all = [p for p in players if p['status'] == 'accepted']
            if len(accepted_all) < 2:
                # If human tried to start alone, just ignore it and stay in lobby
                if status == 'active' and state.get('starting'):
                    cursor.execute("UPDATE game_sessions SET status = 'pending', version = version + 1 WHERE id = ?", (session_id,))
                    conn.commit()
                conn.close(); return

            accepted_guests = [p for p in players if p['status'] == 'accepted' and p['username'].lower() != host.lower()]

            if game_type == 'Hangman':
                print(f"[AI-DEBUG] AI host {host} choosing word...")
                prompt = """You are playing Hangman. You are the host. 
Choose a RANDOM, UNIQUE secret word or short common phrase (max 30 chars).
Pick from categories like: Nature, Science, History, Tech, Movies, or everyday objects.
Ensure the word/phrase is correctly spelled and commonly known.
If you choose a phrase, INCLUDE THE SPACES between words.
Respond ONLY with a JSON object in this format: {"word": "YOUR CHOICE"}"""
                
                try:
                    response = requests.post(OLLAMA_API, json={'model': 'llama3', 'prompt': prompt, 'stream': False, 'format': 'json', 'options': {'temperature': 0.9}}, timeout=30)
                    ai_data = json.loads(response.json().get('response', '{}'))
                    word = ai_data.get('word', '').strip().upper()
                    word = re.sub(r'[^A-Z ]', '', word).strip()
                    if not word or len(word) < 3:
                        word = random.choice(["ADVENTURE", "GALAXY", "MYSTERY", "VOLCANO"])
                except:
                    word = "CHALLENGE"
                
                new_state = {
                    'word': word, 'guessedLetters': [], 'wrongGuesses': 0,
                    'currentTurn': accepted_guests[0]['username'] if accepted_guests else host, 
                    'playersOrder': [p['username'] for p in accepted_all],
                    'allowNumbers': False, 'restarting': False, 'cluesRequestedBy': [], 'clueStack': [],
                    'turnStartedAt': int(datetime.now().timestamp() * 1000), 'updatedAt': int(datetime.now().timestamp() * 1000)
                }
                cursor.execute("UPDATE game_sessions SET state_json = ?, status = 'active', version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), session_id))
                log_game_action(cursor, session_id, f"{host} started the game")
                conn.commit(); conn.close(); return

            elif game_type == 'UNO':
                # UNO Lobby Start
                new_deck = []
                colors = ['red', 'blue', 'green', 'yellow']
                for color in colors:
                    new_deck.append({'color': color, 'value': '0'})
                    for i in range(1, 10):
                        new_deck.extend([{'color': color, 'value': str(i)}, {'color': color, 'value': str(i)}])
                    for act in ['Skip', 'Reverse', 'Draw2']:
                        new_deck.extend([{'color': color, 'value': act}, {'color': color, 'value': act}])
                for _ in range(4):
                    new_deck.extend([{'color': 'black', 'value': 'Wild'}, {'color': 'black', 'value': 'WildDraw4'}])
                
                random.shuffle(new_deck)
                
                accepted_names = [p['username'] for p in accepted_all]
                hands = {}
                for name in accepted_names:
                    hands[name] = [new_deck.pop() for _ in range(7)]
                
                top_card = new_deck.pop()
                while top_card['color'] == 'black':
                    new_deck.insert(0, top_card)
                    top_card = new_deck.pop()
                
                new_state = {
                    'deck': new_deck, 'discard': [top_card], 'hands': hands,
                    'currentTurn': accepted_names[0], 'direction': 1, 'currentColor': top_card['color'],
                    'playersOrder': accepted_names, 'updatedAt': int(datetime.now().timestamp() * 1000)
                }
                cursor.execute("UPDATE game_sessions SET state_json = ?, status = 'active', version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), session_id))
                log_game_action(cursor, session_id, f"{host} started the game")
                conn.commit(); conn.close(); return

        # --- ACTIVE GAME LOGIC ---
        if status == 'active':
            # 1. AI providing clue (Host) - Hangman Only
            if host in AI_PLAYERS and game_type == 'Hangman':
                clue_stack = state.get('clueStack', [])
                if clue_stack and clue_stack[-1]['type'] == 'request':
                    print(f"[AI-DEBUG] AI host {host} providing clue...")
                    p = f"You are the host in Hangman. Word is '{state.get('word')}'. Give a short, helpful hint. Return ONLY text."
                    
                    try:
                        resp = requests.post(OLLAMA_API, json={'model': 'llama3', 'prompt': p, 'stream': False}, timeout=30)
                        hint = resp.json().get('response', 'Good luck!').strip().replace('"', '')
                    except: hint = "Keep going!"
                    
                    new_state = state.copy()
                    new_state['clueStack'].append({'type': 'clue', 'text': hint})
                    new_state['updatedAt'] = int(datetime.now().timestamp() * 1000)
                    cursor.execute("UPDATE game_sessions SET state_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), session_id))
                    conn.commit(); conn.close(); return

            # 2. AI making move (Guest/Turn)
            if current_turn in AI_PLAYERS:
                if game_type == 'Hangman':
                    print(f"[AI-DEBUG] AI {current_turn} guessing Hangman...")
                    # 20% clue request
                    if random.random() < 0.2 and current_turn not in state.get('cluesRequestedBy', []):
                        state['cluesRequestedBy'] = state.get('cluesRequestedBy', []) + [current_turn]
                        state['clueStack'] = state.get('clueStack', []) + [{'type': 'request', 'user': current_turn}]
                        state['updatedAt'] = int(datetime.now().timestamp() * 1000)
                        cursor.execute("UPDATE game_sessions SET state_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(state), session_id))
                        conn.commit()

                    word = state.get('word', 'UNKNOWN')
                    guessed = state.get('guessedLetters', [])
                    word_disp = "".join([c if c.upper() in [g.upper() for g in guessed] or c == ' ' else '_' for c in word])
                    prompt = f"Hangman: {word_disp}. Guessed: {','.join(guessed)}. Pick next letter. Return ONLY the letter."
                    
                    try:
                        resp = requests.post(OLLAMA_API, json={'model': 'llama3', 'prompt': prompt, 'stream': False}, timeout=30)
                        letter = re.search(r'[A-Z]', resp.json().get('response', 'E').upper()).group(0)
                    except: letter = 'E'
                    
                    if letter in [g.upper() for g in guessed]:
                        for l in "ETAOINSHRDLU":
                            if l not in [g.upper() for g in guessed]: letter = l; break
                    
                    new_state, err = apply_hangman_move(state, 'GUESS', current_turn, {'letter': letter, 'host_username': host})
                    
                    if not err:
                        msg = f"{current_turn} guessed {letter}"
                        new_status = 'finished' if new_state.get('winner') or new_state.get('wrongGuesses', 0) >= 6 else 'active'
                        cursor.execute("UPDATE game_sessions SET state_json = ?, status = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), new_status, session_id))
                        log_game_action(cursor, session_id, msg)
                        conn.commit()
                        if new_status == 'active' and new_state.get('currentTurn') in AI_PLAYERS:
                            threading.Timer(2.0, process_ai_action, [session_id]).start()
                        elif new_status == 'finished':
                            threading.Timer(5.0, process_ai_action, [session_id]).start()
                    else:
                        print(f"[AI-ERROR] {current_turn} Hangman move failed: {err}")

                    conn.close(); return

                elif game_type == 'UNO':
                    print(f"[AI-DEBUG] AI {current_turn} playing UNO...")
                    order = state.get('playersOrder', [])
                    order_lower = [o.lower() for o in order]
                    curr_idx = order_lower.index(current_turn.lower())
                    finishers = state.get('finishers', [])
                    
                    my_hand = state['hands'].get(current_turn, [])
                    
                    # 1. Probabilistic UNO Call: if have 1 card and haven't called yet
                    if len(my_hand) == 1 and current_turn not in state.get('unoCalls', []):
                        if random.random() < 0.85: # 85% chance to call it
                            print(f"[AI-DEBUG] AI {current_turn} calling UNO!")
                            state, _ = apply_uno_move(state, 'CALL_UNO', current_turn, {})
                            # PERSIST THE CALL IMMEDIATELY so it shows up in polling
                            cursor.execute("UPDATE game_sessions SET state_json = ?, version = version + 1 WHERE id = ?", (json.dumps(state), session_id))
                            log_game_action(cursor, session_id, f"{current_turn} called UNO!")
                            conn.commit()
                    
                    top = state['discard'][-1]
                    cur_color = state.get('currentColor', top['color'])
                    
                    playable = [i for i, c in enumerate(my_hand) if c['color'] == 'black' or c['color'] == cur_color or c['value'] == top['value']]
                    
                    if playable:
                        # Pick a card
                        card_idx = random.choice(playable)
                        card = my_hand[card_idx]
                        val = card['value']
                        
                        new_state, err = apply_uno_move(state, 'PLAY_CARD', current_turn, {'card_idx': card_idx})
                        
                        if not err:
                            # Update locals after move
                            finishers = new_state.get('finishers', [])
                            next_p = get_next_uno_turn(order, curr_idx, new_state.get('direction', 1), finishers)
                            
                            if val == 'Reverse': 
                                msg = f"{fmt_name(current_turn)} used reverse card, reversing turn order to {fmt_name(next_p)}"
                            elif val == 'Skip':
                                skipped_idx = order_lower.index(next_p.lower())
                                actual_next = get_next_uno_turn(order, skipped_idx, new_state.get('direction', 1), finishers)
                                msg = f"{fmt_name(current_turn)} skipped {fmt_name(next_p)}, it is now {fmt_name(actual_next)}'s turn"
                            elif val == 'Draw2':
                                actual_next = get_next_uno_turn(order, order_lower.index(next_p.lower()), new_state.get('direction', 1), finishers)
                                msg = f"{fmt_name(current_turn)} used a Draw 2, {fmt_name(next_p)} draws 2 and is skipped, next is {fmt_name(actual_next)}"
                            elif val == 'WildDraw4':
                                actual_next = get_next_uno_turn(order, order_lower.index(next_p.lower()), new_state.get('direction', 1), finishers)
                                msg = f"{fmt_name(current_turn)} used a Wild Draw 4, {fmt_name(next_p)} draws 4 and is skipped, next is {fmt_name(actual_next)}"
                            else: msg = f"{fmt_name(current_turn)} played {card['color']} {val}, next is {fmt_name(next_p)}"

                            if card['color'] == 'black':
                                # AI chooses color
                                counts = {c: 0 for c in ['red', 'blue', 'green', 'yellow']}
                                for c in my_hand: 
                                    if c['color'] in counts: counts[c['color']] += 1
                                best_color = max(counts, key=counts.get)
                                new_state, err = apply_uno_move(new_state, 'SELECT_COLOR', current_turn, {'color': best_color})
                                if not err:
                                    final_finishers = new_state.get('finishers', [])
                                    final_next = get_next_uno_turn(order, curr_idx, new_state.get('direction', 1), final_finishers)
                                    if val == 'WildDraw4':
                                        msg = f"{fmt_name(current_turn)} used a Wild Draw 4 and chose {best_color}, {fmt_name(next_p)} draws 4 and is skipped, next is {fmt_name(actual_next)}"
                                    else:
                                        msg = f"{fmt_name(current_turn)} played {val} and chose {best_color}, next is {fmt_name(final_next)}"
                    else:
                        new_state, err = apply_uno_move(state, 'DRAW_CARD', current_turn, {})
                        if not err:
                            if new_state.get('justDrewPlayable'):
                                msg = f"{fmt_name(current_turn)} drew a playable card and can still move"
                            else:
                                next_p = get_next_uno_turn(order, curr_idx, new_state.get('direction', 1), new_state.get('finishers', []))
                                msg = f"{fmt_name(current_turn)} drew a card, it is now {fmt_name(next_p)}'s turn"

                    if not err:
                        new_status = new_state.get('status', 'active')
                        cursor.execute("UPDATE game_sessions SET state_json = ?, status = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), new_status, session_id))
                        log_game_action(cursor, session_id, msg)
                        conn.commit()
                        if new_status == 'active' and new_state.get('currentTurn') in AI_PLAYERS:
                            threading.Timer(2.0, process_ai_action, [session_id]).start()
                        elif new_status == 'finished':
                            threading.Timer(5.0, process_ai_action, [session_id]).start()
                    else:
                        print(f"[AI-ERROR] {current_turn} move failed: {err}")

                    conn.close(); return

        # --- FINISHED / RESTART LOGIC ---
        if status == 'finished' and (state.get('winner') in AI_PLAYERS or host in AI_PLAYERS):
            last_upd = state.get('updatedAt', 0)
            if int(datetime.now().timestamp() * 1000) - last_upd > 5000:
                print(f"[AI-DEBUG] AI host/winner restarting game {session_id}...")
                new_state = {'restarting': True, 'updatedAt': int(datetime.now().timestamp() * 1000)}
                new_host = state.get('winner') if state.get('winner') in AI_PLAYERS else host
                cursor.execute("UPDATE game_sessions SET state_json = ?, status = 'pending', host_username = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(new_state), new_host, session_id))
                conn.commit()
                threading.Timer(2.0, process_ai_action, [session_id]).start()
        
        conn.close()
    except Exception as e:
        print(f"AI Error in {session_id}: {e}")
        import traceback; traceback.print_exc()

def trigger_ai_if_needed(session_id):
    # Short delay to ensure the database commit from the triggering request is fully finished
    # and the client has a moment to see the change
    threading.Timer(2.0, process_ai_action, [session_id]).start()

@app.route('/api/games/respond', methods=['POST'])
def game_respond():
    try:
        data = request.json
        session_id = data.get('session_id')
        username = data.get('username')
        action = data.get('action') # 'accept' or 'decline'
        
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT players_json, status FROM game_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row: return jsonify({'error': 'Session not found'}), 404
        
        players = json.loads(row['players_json'])
        found = False
        for p in players:
            if p['username'] == username:
                p['status'] = 'accepted' if action == 'accept' else 'declined'
                found = True; break
        
        if not found and action == 'accept':
            # Allow "joining" via link even if not invited
            players.append({'username': username, 'status': 'accepted'})
            found = True
        
        if not found: return jsonify({'error': 'User not in invite list'}), 403
        
        cursor.execute("UPDATE game_sessions SET players_json = ?, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(players), session_id))
        conn.commit(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/session/<session_id>')
def get_game_session(session_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM game_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if not row: 
            conn.close()
            return jsonify({'error': 'Not found'}), 404
        
        status = row['status']
        host = row['host_username']
        state = json.loads(row['state_json']) if row['state_json'] else None
        
        # Proactive trigger: if it's an AI's turn OR game is currently starting
        needs_trigger = (status == 'active' and state and state.get('currentTurn') in AI_PLAYERS) or \
                        (status == 'active' and state and state.get('starting')) or \
                        (status == 'pending' and host in AI_PLAYERS)
        
        if needs_trigger:
            # Check if we should trigger (only if updatedAt is older than 3s to avoid double triggers)
            last_upd = state.get('updatedAt', 0) if state else 0
            if int(datetime.now().timestamp() * 1000) - last_upd > 3000:
                trigger_ai_if_needed(session_id)

        resp = jsonify({
            'success': True,
            'session': {
                'id': row['id'],
                'game_type': row['game_type'],
                'host': host,
                'players': json.loads(row['players_json']),
                'state': state,
                'status': status,
                'version': row['version'],
                'logs': json.loads(row['logs_json'] if row['logs_json'] else '[]'),
                'winner': state.get('winner') if state else None,
                'loser': state.get('loser') if state else None
            }
        })
        conn.close()
        return resp
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/action', methods=['POST'])
def game_action():
    try:
        data = request.json
        print(f"[ACTION-DEBUG] Incoming action: {data}")
        session_id = data.get('session_id')
        username = data.get('username')
        action = data.get('action')
        params = data.get('params', {})
        client_version = data.get('version')
        
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM game_sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close(); return jsonify({'error': 'Session not found'}), 404
            
        current_version = row['version']
        if client_version is not None and client_version < current_version and action != 'CALL_UNO':
            # Client is out of date, but we should return current state to let them catch up
            state = json.loads(row['state_json']) if row['state_json'] else {}
            conn.close()
            return jsonify({'error': 'State out of date', 'current_state': state, 'version': current_version}), 409
            
        state = json.loads(row['state_json']) if row['state_json'] else {}
        game_type = row['game_type']
        
        # PRE-CAPTURE card details for logging before hands change
        pre_card_details = None
        if game_type == 'UNO' and action == 'PLAY_CARD':
            try:
                hand = state.get('hands', {}).get(username, [])
                card_idx = params.get('card_idx')
                if card_idx is not None and card_idx < len(hand):
                    pre_card_details = hand[card_idx]
            except: pass

        if game_type == 'UNO':
            new_state, err = apply_uno_move(state, action, username, params)
        elif game_type == 'Hangman':
            params['host_username'] = row['host_username']
            new_state, err = apply_hangman_move(state, action, username, params)
        else:
            conn.close(); return jsonify({'error': 'Game type does not support actions yet'}), 400
            
        if err:
            print(f"[ACTION-REJECTED] Session {session_id} | User {username} | Action {action} | Error: {err}")
            # If it's a duplicate guess, return 200 so browser doesn't log a red error
            status_code = 200 if err == "Already guessed" else 400
            conn.close(); return jsonify({'error': err}), status_code
            
        if game_type == 'UNO':
            # Calculate next player while skipping finished ones
            finishers = new_state.get('finishers', [])
            order = new_state.get('playersOrder', [])
            order_lower = [o.lower() for o in order]
            try:
                curr_idx = order_lower.index(username.lower())
                next_p = get_next_uno_turn(order, curr_idx, new_state.get('direction', 1), finishers)
            except:
                next_p = new_state.get('currentTurn', 'Unknown')

            msg = f"{fmt_name(username)} performed {action}"
            try:
                if action == 'PLAY_CARD':
                    if pre_card_details:
                        val = pre_card_details['value']
                        if val == 'Reverse':
                            # For Reverse, next_p is already calculated correctly above using get_next_uno_turn
                            msg = f"{fmt_name(username)} used reverse card, reversing turn order to {fmt_name(next_p)}"
                        elif val == 'Skip':
                            # Skip means skip one active player and go to the one after
                            skipped_p = next_p
                            skipped_idx = order_lower.index(skipped_p.lower())
                            actual_next = get_next_uno_turn(order, skipped_idx, state.get('direction', 1), finishers)
                            msg = f"{fmt_name(username)} skipped {fmt_name(skipped_p)}, it is now {fmt_name(actual_next)}'s turn"
                        elif val == 'Draw2':
                            victim = next_p
                            victim_idx = order_lower.index(victim.lower())
                            actual_next = get_next_uno_turn(order, victim_idx, state.get('direction', 1), finishers)
                            msg = f"{fmt_name(username)} used a Draw 2, {fmt_name(victim)} draws 2 and is skipped, next is {fmt_name(actual_next)}"
                        elif val == 'WildDraw4':
                            victim = next_p
                            victim_idx = order_lower.index(victim.lower())
                            actual_next = get_next_uno_turn(order, victim_idx, state.get('direction', 1), finishers)
                            color_str = f" and chose {params.get('color')}" if params.get('color') else ""
                            msg = f"{fmt_name(username)} used a Wild Draw 4{color_str}, {fmt_name(victim)} draws 4 and is skipped, next is {fmt_name(actual_next)}"
                        elif val == 'Wild':
                            color_str = f" and chose {params.get('color')}" if params.get('color') else ""
                            msg = f"{fmt_name(username)} played a Wild{color_str}, next is {fmt_name(next_p)}"
                        else:
                            msg = f"{fmt_name(username)} played {pre_card_details['color']} {val}, next is {fmt_name(next_p)}"
                    else:
                        msg = f"{fmt_name(username)} played a card, next is {fmt_name(next_p)}"
                elif action == 'DRAW_CARD':
                    if new_state.get('justDrewPlayable'):
                        msg = f"{fmt_name(username)} drew a playable card and can still move"
                    else:
                        msg = f"{fmt_name(username)} drew a card, it is now {fmt_name(next_p)}'s turn"
                elif action == 'SELECT_COLOR':
                    msg = f"{fmt_name(username)} chose {params.get('color')}, next is {fmt_name(next_p)}"
                elif action == 'CALL_UNO':
                    msg = f"{fmt_name(username)} called UNO!"
                elif action == 'DISPUTE':
                    target = state.get('lastFinisher', 'someone')
                    msg = f"{fmt_name(username)} disputed the win! {fmt_name(target)} draws 2 and is back in!"
            except Exception as le:
                print(f"[LOG-ERROR] Failed to construct message: {le}")
        elif game_type == 'Hangman':
            if action == 'GUESS':
                l = params.get('letter')
                msg = f"{username} guessed {l}" if l else f"{username} timed out"
            else: msg = f"{username} performed {action}"
        else: msg = f"{username} performed {action}"

        if game_type == 'UNO':
            new_status = new_state.get('status', 'active')
        else:
            new_status = 'finished' if (new_state.get('winner') or new_state.get('status') == 'finished') else 'active'
        new_version = current_version + 1
        cursor.execute(
            "UPDATE game_sessions SET state_json = ?, status = ?, version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND version = ?",
            (json.dumps(new_state), new_status, new_version, session_id, current_version)
        )
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Concurrency conflict, please retry'}), 409
            
        log_game_action(cursor, session_id, msg)
        conn.commit(); conn.close()
        trigger_ai_if_needed(session_id)
        return jsonify({'success': True, 'version': new_version}), 200
        
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/games/update', methods=['POST'])
def update_game_state():
    try:
        data = request.json
        session_id = data.get('session_id')
        state = data.get('state')
        status = data.get('status') # optional
        new_host = data.get('new_host') # optional
        
        conn = get_db(); cursor = conn.cursor()
        
        updates = []
        params = []
        
        if state is not None:
            updates.append("state_json = ?")
            params.append(json.dumps(state))
        if status:
            updates.append("status = ?")
            params.append(status)
            if status == 'pending':
                updates.append("logs_json = '[]'")
        if new_host:
            updates.append("host_username = ?")
            params.append(new_host)
            
        if not updates: return jsonify({'error': 'No updates provided'}), 400
        
        # Always increment version on manual state update
        updates.append("version = version + 1")
        
        params.append(session_id)
        query = f"UPDATE game_sessions SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        cursor.execute(query, tuple(params))
        
        conn.commit(); conn.close()
        trigger_ai_if_needed(session_id)
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/available')
def get_available_games():
    try:
        conn = get_db(); cursor = conn.cursor()
        # Cleanup: Delete pending sessions that have expired
        cursor.execute("DELETE FROM game_sessions WHERE status = 'pending' AND expires_at < datetime('now')")
        conn.commit()
        # Find all pending sessions
        cursor.execute("SELECT * FROM game_sessions WHERE status = 'pending'")
        rows = cursor.fetchall(); conn.close()
        return jsonify({'success': True, 'sessions': [dict(r) for r in rows]}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/my-active')
def get_my_active_games():
    try:
        u = request.args.get('username')
        conn = get_db(); cursor = conn.cursor()
        # Cleanup: Delete pending sessions that have expired
        cursor.execute("DELETE FROM game_sessions WHERE status = 'pending' AND expires_at < datetime('now')")
        conn.commit()
        # Find sessions where user is a player and session is not finished
        cursor.execute("SELECT * FROM game_sessions WHERE status != 'finished' AND players_json LIKE ?", (f'%"{u}"%',))
        rows = cursor.fetchall(); conn.close()
        return jsonify({'success': True, 'sessions': [dict(r) for r in rows]}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/games/delete', methods=['POST'])
def delete_game_session():
    try:
        data = request.json
        session_id = data.get('session_id')
        username = data.get('username')
        
        conn = get_db(); cursor = conn.cursor()
        # Fetch session to check ownership
        cursor.execute("SELECT host_username FROM game_sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()
        if not session: return jsonify({'error': 'Session not found'}), 404
        
        # Check if user is admin
        cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        is_admin = user and user['role'] == 'admin'
        
        if not is_admin and session['host_username'] != username:
            conn.close(); return jsonify({'error': 'Unauthorized'}), 403
            
        cursor.execute("DELETE FROM game_sessions WHERE id = ?", (session_id,))
        conn.commit(); conn.close()
        return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

# --- API ROUTES ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    users = load_users()
    u, p = data.get('username'), data.get('password')
    if u in users and users[u]['password'] == p:
        conn = get_db(); cursor = conn.cursor(); cursor.execute("UPDATE users SET last_online = CURRENT_TIMESTAMP WHERE username = ?", (u,))
        conn.commit(); conn.close()
        return jsonify({'success': True, 'username': u, 'role': users[u].get('role', 'student')}), 200
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/user/heartbeat', methods=['POST'])
def user_heartbeat():
    try:
        data = request.json; u = data.get('username')
        if not u: return jsonify({'error': 'Missing username'}), 400
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_online = CURRENT_TIMESTAMP WHERE username = ?", (u,))
        conn.commit(); conn.close(); return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/users/all')
def get_all_users_status():
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("""
            SELECT username, role, last_online,
            CASE WHEN last_online > datetime('now', '-2 minutes') THEN 1 ELSE 0 END as is_online
            FROM users ORDER BY is_online DESC, username ASC
        """)
        rows = cursor.fetchall(); conn.close()
        users = []
        for r in rows:
            is_online = bool(r['is_online'])
            if r['username'] in AI_PLAYERS:
                is_online = True
            users.append({'username': r['username'], 'role': r['role'], 'is_online': is_online, 'last_online': r['last_online']})
        return jsonify({'success': True, 'users': users}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

def trigger_ai_chat_response(sender, recipient, message):
    """Generate an AI response for chat using Ollama"""
    try:
        # personality based on name
        personality = "You are Bob, a friendly and helpful student AI player."
        if recipient == 'Tim':
            personality = "You are Tim, a slightly witty and competitive student AI player."
            
        prompt = f"""{personality}
You just received a message from {sender}: "{message}"
Write a short, conversational response (max 2 sentences).
Keep the tone appropriate for a school setting.
Return ONLY the response text."""

        response = requests.post(OLLAMA_API, json={
            'model': 'llama3',
            'prompt': prompt,
            'stream': False
        }, timeout=30)
        
        if response.status_code == 200:
            reply = response.json().get('response', '').strip().replace('"', '')
            if reply:
                conn = get_db(); cursor = conn.cursor()
                cursor.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", (recipient, sender, reply))
                conn.commit(); conn.close()
    except Exception as e:
        print(f"AI Chat Error: {e}")

@app.route('/api/messages/send', methods=['POST'])
def send_message():
    try:
        data = request.json; s, r, m = data.get('sender'), data.get('recipient'), data.get('message')
        if not s or not r or not m: return jsonify({'error': 'Missing fields'}), 400
        
        # Prevent massive messages that freeze browsers
        if len(m) > 10000:
            return jsonify({'error': 'Message too long (max 10,000 chars)'}), 400
            
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)", (s, r, m))
        conn.commit(); conn.close()
        
        # Trigger AI response if recipient is an AI bot
        if r in AI_PLAYERS:
            threading.Thread(target=trigger_ai_chat_response, args=(s, r, m)).start()
            
        return jsonify({'success': True}), 201
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/get')
def get_messages():
    try:
        u, other = request.args.get('username'), request.args.get('other')
        if not u: return jsonify({'error': 'Missing username'}), 400
        
        # print(f"  [CHAT] Fetching. user='{u}', other='{other}'", flush=True)
        
        conn = get_db(); cursor = conn.cursor()
        if other: 
            # Use lower() or trim() if suspecting whitespace issues, though SQL is usually case-sensitive for strings
            cursor.execute("SELECT * FROM messages WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?) ORDER BY timestamp ASC", (u, other, other, u))
        else: 
            cursor.execute("SELECT * FROM messages WHERE recipient = ? OR sender = ? ORDER BY timestamp DESC LIMIT 50", (u, u))
        
        rows = cursor.fetchall(); conn.close()
        msgs = [dict(r) for r in rows]
        
        if u == 'the22one98and7only68the78smartest6abdullah' or other == 'the22one98and7only68the78smartest6abdullah':
            print(f"  [CHAT] DEBUG for long-name user. Found {len(msgs)} messages.", flush=True)
            if len(msgs) > 0:
                print(f"  [CHAT] First msg: {msgs[0]['sender']} -> {msgs[0]['recipient']}: {msgs[0]['message'][:20]}...", flush=True)
        
        return jsonify({'success': True, 'messages': msgs}), 200
    except Exception as e: 
        print(f"  [CHAT] Error: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages/read', methods=['POST'])
def mark_messages_read():
    try:
        data = request.json; u, other = data.get('username'), data.get('other')
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_read = 1 WHERE recipient = ? AND sender = ?", (u, other))
        conn.commit(); conn.close(); return jsonify({'success': True}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/messages/unread-count')
def get_unread_count():
    try:
        u = request.args.get('username'); conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM messages WHERE recipient = ? AND is_read = 0", (u,))
        total = cursor.fetchone()['count']
        cursor.execute("SELECT sender, COUNT(*) as count FROM messages WHERE recipient = ? AND is_read = 0 GROUP BY sender", (u,))
        rows = cursor.fetchall(); conn.close()
        return jsonify({'success': True, 'count': total, 'by_sender': {r['sender']: r['count'] for r in rows}}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

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

@app.route('/api/all-quizzes')
def get_all_quizzes():
    """Get list of all saved quizzes with their attempt counts"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        # Count by quiz_id OR matching topic for older results
        cursor.execute("""
            SELECT q.id, q.topic, q.created_by, q.created_at,
            (SELECT COUNT(*) FROM quiz_results r WHERE 
                r.quiz_data_json LIKE '%"id": ' || q.id || ',%' OR
                r.quiz_data_json LIKE '%"topic": "' || q.topic || '"%'
            ) as taken_count
            FROM saved_quizzes q
            ORDER BY q.created_at DESC
        """)
        rows = cursor.fetchall()
        quizzes = [dict(r) for r in rows]
        conn.close()
        return jsonify({'success': True, 'quizzes': quizzes})
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
            quiz_data = json.loads(row['quiz_json'])
            # If the JSON is a dict with 'questions' key, extract that list
            questions = quiz_data.get('questions', []) if isinstance(quiz_data, dict) else quiz_data
            return jsonify({
                'success': True, 
                'quiz': {
                    'id': row['id'], 
                    'topic': row['topic'], 
                    'questions': questions
                }
            })
        return jsonify({'success': False, 'message': 'Quiz not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/quiz/update', methods=['POST'])
def update_quiz():
    """Update quiz questions (for edits)"""
    try:
        data = request.json
        quiz_id = data.get('quiz_id')
        questions = data.get('questions')
        
        if not quiz_id or questions is None:
            return jsonify({'success': False, 'message': 'Missing data'}), 400
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE saved_quizzes SET quiz_json = ? WHERE id = ?",
            (json.dumps(questions), quiz_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
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
        quiz_id = data.get('quiz_id')
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
            'id': quiz_id,
            'topic': topic,
            'questions': questions_results
        }
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO quiz_results (username, quiz_data_json, answers_json, score, total_marks) VALUES (?, ?, ?, ?, ?)",
            (username, json.dumps(quiz_data), json.dumps(questions_results), score, total)
        )
        result_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'result_id': result_id}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/games.html')
def games_page(): return send_from_directory('.', 'games.html')

@app.route('/hangman.html')
def hangman_page(): return send_from_directory('.', 'hangman.html')

@app.route('/quiz_review.html')
def quiz_review_page():
    return send_from_directory('.', 'quiz_review.html')

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

                    q_prompt = f"""Extract marking details for sub-question {sub_id} from the mark scheme AND determine the correct input format based on the question paper text.
                    MATCHING QUESTION ID: {sub_id}
                    
                    QUESTION PAPER TEXT (Page Context):
                    {page_content}

                    MARK SCHEME TEXT:
                    {ms_text[:40000]}

                    Return ONLY a JSON object:
                    {{
                    "sub_id": "{sub_id}",
                    "type": "text/mcq/calculation/draw/list",
                    "max_marks": 1,
                    "lines_provided": 2, // Number of physical lines for the answer in the question paper
                    "ms_text": "Complete marking criteria for this question",
                    "options": ["A", "B", "C", "D"], // Only for mcq type
                    "final_label": "Value", // Only for calculation type
                    "final_unit": "unit" // Only for calculation type
                    }}

                    MANDATORY RULES:
                    1. TYPE SELECTION (Look at the QUESTION PAPER TEXT):
                       - Use 'list' ONLY if the question paper explicitly asks for distinct points (e.g., "State two...", "Give three...") or provides numbered/bulleted lines for the answer.
                       - Use 'calculation' if the question paper asks to "calculate", "work out", or if there's a dotted line followed by a unit (e.g., "....... cm").
                       - Use 'mcq' if the question paper provides options A, B, C, D.
                       - Use 'draw' if the question paper asks to "draw", "plot", or "sketch" a diagram, pyramid, or chart (unless it's a line graph, then use 'graph').
                       - Use 'text' for standard open-ended questions, explanations, or descriptions.
                    2. ANSWER SPACE: Closely examine the QUESTION PAPER TEXT to see how many dotted lines (..........) are provided for the student to write on. Set 'lines_provided' to this count.
                    3. For 'calculation' questions, closely examine the QUESTION PAPER TEXT near the dotted answer line to identify the exact label (e.g., 'rate', 'Length', 'Ratio') and unit (e.g., 'cm per second', 'µm').
                    4. ms_text must be the full marking criteria from the MARK SCHEME TEXT.
                    """                    
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
        q_type = data.get('type')

        # Get Examiner Report if available
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT er_text FROM official_exams WHERE id = ?", (paper_id,))
        row = cursor.fetchone(); er_text = row['er_text'] if row and row['er_text'] else ""; conn.close()

        # INSTANT BYPASS FOR VISUAL QUESTIONS
        if q_type in ['draw', 'graph']:
            return jsonify({
                "marks_awarded": max_marks,
                "max_marks": max_marks,
                "feedback": f"VISUAL EVALUATION: As an AI, I cannot grade your drawing or graph. You have been awarded full marks automatically. Please verify your work against the official criteria.\\n\\nFULL MARK SCHEME: {mark_scheme}",
                "marking_points_met": ["Self-evaluation required"]
            }), 200

        # PROGRAMMATIC MCQ CHECK
        cleaned_ans = user_answer.strip().upper()
        if q_type == 'mcq' or (len(cleaned_ans) == 1 and cleaned_ans in ['A', 'B', 'C', 'D']):
            # Search for "Correct Answer: X" or "Answer is X" or just "X (" in the mark scheme
            import re
            mcq_match = re.search(r'(?:Correct Answer|Answer is|Correct|Key)[:\s]+([A-D])', mark_scheme, re.I)
            if not mcq_match:
                # Fallback: look for "X (" at start or after a dot
                mcq_match = re.search(r'(?:^|\.|\s)([A-D])\s*\(', mark_scheme)
            
            if mcq_match:
                correct_letter = mcq_match.group(1).upper()
                is_correct = (cleaned_ans == correct_letter)
                if is_correct:
                    return jsonify({
                        "marks_awarded": max_marks,
                        "max_marks": max_marks,
                        "feedback": f"Correct! The answer is {correct_letter}.",
                        "marking_points_met": ["Correct MCQ selection"]
                    }), 200
                else:
                    return jsonify({
                        "marks_awarded": 0,
                        "max_marks": max_marks,
                        "feedback": f"Incorrect. Your answer was {cleaned_ans}, but the correct answer is {correct_letter}. \n\nMODEL ANSWER: {mark_scheme}",
                        "marking_points_met": []
                    }), 200

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
1. ZERO TOLERANCE: If the student's answer is gibberish, irrelevant, or a REQUEST FOR HELP (e.g. "tell me", "I don't know", "what is the answer?"), you MUST award 0 marks. Do not attempt to find a match.
2. MCQ (MULTIPLE CHOICE): Award FULL marks if correct letter matches, 0 if wrong.
3. STANDARD TEXT QUESTIONS (SEMANTIC MATCHING):
   - Award marks ONLY if the student is actually attempting to answer the question.
   - Use semantic matching for genuine attempts (e.g. 'seed type' matches 'type of seeds').
   - PROHIBITION: Do not award "pity marks" for irrelevant text or help requests.
4. CALCULATION QUESTIONS (HYPER-STRICT NUMERICAL MATCH): 
   - Award marks ONLY if the specific numbers/steps from the mark scheme are LITERALLY WRITTEN.
   - [FINAL_ANSWER_START]: Must match the final value exactly.
   - [WORKING_START]: Award 1 mark ONLY for specific correct numerical steps.
   - PROHIBITION: No "implied" marks for wrong numbers.
5. EVIDENCE-BASED JUSTIFICATION: State exactly which points or numbers matched.
6. MODEL ANSWER (MANDATORY): You MUST copy the entirety of the [OFFICIAL MARK SCHEME] text provided above into this section. DO NOT summarize, DO NOT edit, and DO NOT leave anything out. The student needs to see the full official criteria.

RESPONSE FORMAT (JSON ONLY):
{{
  "marks_awarded": (integer),
  "max_marks": {max_marks},
  "feedback": "MARKING JUSTIFICATION: [Your explanation]\\n\\nFULL MARK SCHEME: [THE ENTIRE OFFICIAL MARK SCHEME COPIED VERBATIM]",
  "marking_points_met": []
}}

MANDATORY RULES:
1. If the student's numbers do not exist in the mark scheme, the score MUST be 0.
2. No "benefit of the doubt". No "partial effort" marks for wrong numbers.
3. You MUST return a valid JSON object.
"""
        print(f"  [GRADING] Q {sub_id} Student Answer: {user_answer[:100]}...", flush=True)
        
        payload = {
            'model': 'llama3', 
            'prompt': prompt, 
            'stream': False, 
            'format': 'json',
            'options': {
                'temperature': 0,
                'seed': 42,
                'num_predict': 500
            }
        }
        
        result = None
        for attempt in range(2): # Try up to 2 times
            try:
                resp = requests.post('http://localhost:11434/api/generate', json=payload, timeout=90)
                raw = resp.json().get('response', '{}')
                print(f"  [GRADING] Q {sub_id} RAW AI (Attempt {attempt+1}): {raw.strip()}", flush=True)
                
                parsed = clean_ai_json(raw)
                if parsed and isinstance(parsed, dict) and 'marks_awarded' in parsed:
                    result = parsed
                    break
                else:
                    print(f"  [GRADING] Attempt {attempt+1} failed to parse or missing keys. Retrying...", flush=True)
            except Exception as e:
                print(f"  [GRADING] Attempt {attempt+1} error: {str(e)}", flush=True)
        
        if not result:
            result = {"marks_awarded": 0, "feedback": "AI Marking Error - The AI failed to provide a valid grade after multiple attempts. Please try again or check the manual mark scheme below."}
        
        # MANUALLY ENSURE FULL MODEL ANSWER IS PRESENT
        # The AI often truncates the mark scheme, so we ensure the original is appended.
        feedback = result.get('feedback', 'No justification provided.')
        
        # If the AI provided its own MODEL ANSWER/FULL MARK SCHEME, we replace its content with the original 
        # to ensure it hasn't been truncated or hallucinated.
        model_answer_html = f"<div style='background: #ffffcc; padding: 15px; border: 1px solid #e6e600; border-radius: 8px; margin-top: 15px; color: #333;'><strong style='color: #000; display: block; margin-bottom: 8px; border-bottom: 1px solid #e6e600; padding-bottom: 5px;'>OFFICIAL MODEL ANSWER:</strong>{mark_scheme}</div>"
        
        if "FULL MARK SCHEME:" in feedback:
            parts = feedback.split("FULL MARK SCHEME:")
            result['feedback'] = f"{parts[0].strip()}{model_answer_html}"
        elif "MODEL ANSWER:" in feedback:
            parts = feedback.split("MODEL ANSWER:")
            result['feedback'] = f"{parts[0].strip()}{model_answer_html}"
        else:
            result['feedback'] = f"{feedback.strip()}{model_answer_html}"
            
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

@app.route('/api/results/id/<int:result_id>')
def get_result_by_id(result_id):
    try:
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT * FROM quiz_results WHERE id = ?", (result_id,))
        row = cursor.fetchone(); conn.close()
        if row:
            quiz_data = json.loads(row['quiz_data_json'])
            topic = quiz_data.get('topic') or quiz_data.get('title') or 'Quiz'
            return jsonify({
                'success': True,
                'result': {
                    'id': row['id'],
                    'username': row['username'],
                    'topic': topic,
                    'score': row['score'],
                    'total_marks': row['total_marks'],
                    'timestamp': row['timestamp'],
                    'answers': json.loads(row['answers_json']) if row['answers_json'] else [],
                    'quiz_data': quiz_data
                }
            }), 200
        return jsonify({'success': False, 'message': 'Result not found'}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/results')
def get_results_api():
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_results ORDER BY timestamp DESC")
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

@app.route('/api/admin/all-progress')
def get_all_student_progress():
    try:
        # Check if the requester is an admin
        u = request.args.get('username')
        if not u: return jsonify({'error': 'Missing username'}), 400
        
        conn = get_db(); cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE username = ?", (u,))
        user = cursor.fetchone()
        if not user or user['role'] != 'admin':
            conn.close()
            return jsonify({'error': 'Unauthorized'}), 403
            
        # Fetch progress joined with exam titles
        cursor.execute("""
            SELECT p.username, p.paper_id, p.status, p.last_updated, e.title
            FROM exam_progress p
            JOIN official_exams e ON p.paper_id = e.id
            ORDER BY p.last_updated DESC
        """)
        rows = cursor.fetchall(); conn.close()
        
        all_progress = [{
            'username': r['username'],
            'paper_id': r['paper_id'],
            'status': r['status'],
            'last_updated': r['last_updated'],
            'title': r['title']
        } for r in rows]
        
        return jsonify({'success': True, 'all_progress': all_progress}), 200
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/admin/delete-quiz', methods=['POST'])
def delete_quiz():
    """Admin endpoint to delete a saved quiz"""
    try:
        data = request.json
        admin_username = data.get('admin_username')
        quiz_id = data.get('quiz_id')
        
        if not admin_username or not quiz_id:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
            
        # Verify admin role
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE username = ?", (admin_username,))
        user = cursor.fetchone()
        
        if not user or user['role'] != 'admin':
            conn.close()
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
        cursor.execute("DELETE FROM saved_quizzes WHERE id = ?", (quiz_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
    # Silence noisy polling logs
    import logging
    class NoPollingFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # Only filter standard Werkzeug GET/POST logs for these endpoints
            # This allows our explicit print("[CHAT] ...") to still show up
            if "[AI-DEBUG]" in msg: return False
            return not any(x in msg for x in [
                '/api/messages/unread-count', 
                '/api/messages/get',
                '/api/user/heartbeat',
                '/api/users/all',
                '/api/student/exam-progress/save',
                '/api/admin/all-progress',
                '/api/games/session',
                '/api/games/my-active',
                '/api/games/available',
                '/api/user/preferences/save',
                '/api/user/preferences/get'
            ])
    logging.getLogger('werkzeug').addFilter(NoPollingFilter())
    
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
