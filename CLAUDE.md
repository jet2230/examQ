# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

### Backend (exam_server.py)
- Flask-based API server running on port 5001
- SQLite database (`quizzes.db`) for persistent storage
- Single file containing all routes, handlers, and database logic

### Frontend
- HTML templates served directly by Flask (no separate build step)
- Key files:
  - `official_exam_player.html` - Interactive exam interface for official papers
  - `exam_generator_v2.html` - Custom quiz generator
  - `admin_exams.html` - Admin exam library management
  - `admin_users.html` - User management console
  - `results_dashboard.html` - Student performance tracking

### Database Schema
- `users`: username, password, role (student/admin), timestamps
- `official_exams`: paper metadata and file paths
- `exam_progress`: student progress tracking per paper
- `quiz_results`: AI grading results
- `saved_quizzes`: User-generated quizzes
- `user_preferences`: Theme and UI state per user
- `messages`: In-app messaging system
- `game_sessions`: Multiplayer game sessions (Hangman, etc.)

### External Dependencies
- Ollama (local LLM server, model: llama3)
- System tools: `poppler-utils` (pdftotext), `tesseract-ocr`

## Key Functions and Patterns

### PDF Processing (`exam_server.py:160-185`)
```python
def extract_pdf_text(filepath):
    # Try pdftotext first (text-layer extraction)
    # Fallback to Tesseract OCR
    # Final fallback to PyPDF2
```

### AI Grading Flow
1. Student submits answers via `/api/official-exams/submit`
2. Server extracts question text and page mappings from JSON
3. Renders exam player with images from `static/exams/<paper_id>/qp/`
4. Student answers questions in textarea fields
5. Submit triggers AI grading against mark schemes in `ms_text` field

### Exam JSON Structure
```json
{
  "paper_id": "...",
  "questions": [
    {
      "id": 1,
      "max_marks": 1,
      "sub_questions": [{
        "sub_id": "1",
        "type": "text",
        "qp_pages": [2],  // Page number(s) to show in viewer
        "ms_text": "marking criteria...",
        "question_text": "Actual question..."
      }]
    }
  ]
}
```

## Common Commands

### Start the server
```bash
python3 exam_server.py
# Or use the startup script
./start_servers.sh
```

### Install dependencies
```bash
pip3 install -r requirements.txt
```

### Database operations
```bash
python3 -c "import sqlite3; conn = sqlite3.connect('quizzes.db'); ..."
```

### View server logs
```bash
tail -f server.log
```

## Data Flow

1. **Admin imports PDF**: Uses `/api/admin/process-exam` to upload Question Paper + Mark Scheme PDFs
2. **Processing**: Extracts text/images, generates JSON in `exam_data/`
3. **Registration**: Adds entry to `official_exams` table with `data_json_path`
4. **Student access**: Fetches JSON via `/api/official-exams/<paper_id>`, renders HTML with images
5. **AI grading**: Compares student answers against `ms_text` using Llama3

## File Organization

- `exam_data/` - Processed exam JSON files (per-paper)
- `static/exams/<paper_id>/qp/` - Question paper images
- `static/exams/<paper_id>/ms/` - Mark scheme images
- `resources/` - Original PDF uploads
- `quizzes.db` - SQLite database

## Git / Commit Rules

**NEVER commit or push without explicit user authorization.** Always ask the user first before:
- `git add` any files
- `git commit` any changes
- `git push` to remote

This applies to all changes: bug fixes, feature additions, deletions, refactoring, and database updates.

## Testing
- No test suite present
- Manual testing via browser at http://localhost:5001
- Admin login: admin / pass123
