# ExamQ: AI-Powered IGCSE Exam Platform

A comprehensive platform for generating quizzes, managing official IGCSE papers, and practicing with AI-powered grading.

## 🚀 Quick Start

### Start Everything
```bash
./start_servers.sh
```

Then open your browser to:
```
http://localhost:5001/
```

## ✨ Key Features

### 📖 Official Exam Library
- **AI-Powered Import:** Automatically convert official IGCSE PDFs (Question Paper + Mark Scheme) into interactive digital exams.
- **Side-by-Side Player:** View the exam paper and answer booklet simultaneously with smart scroll synchronization.
- **AI Grading:** Instant feedback and marking based strictly on official Edexcel mark schemes using Llama 3.
- **Extracts Booklet:** Built-in support for English Language reading booklets.

### 🤖 Quiz Generator
- Generate custom multiple-choice quizzes on any topic using Llama 3.
- Auto-save generated quizzes for offline practice.

### 👤 User & Admin Management
- **User Accounts:** Secure registration and login for students.
- **Admin Panel:** Comprehensive tools to manage users, monitor progress, and build the exam library.
- **Results Dashboard:** Track performance across different papers and topics.

## 📁 Project Structure

```
/home/obo/playground/examQ/
├── exam_server.py          # Flask backend & AI Orchestrator
├── official_exam_player.html # interactive Exam Interface
├── exam_generator_v2.html  # Custom Quiz Generator
├── admin_exams.html        # Library Management Console
├── admin_users.html        # User Management Console
├── results_dashboard.html  # Performance Tracking
├── start_servers.sh        # Startup Script
├── stop_servers.sh         # Shutdown Script
├── exam_data/              # Processed Exam JSONs
├── static/exams/           # Extracted Exam Images
└── resources/              # Raw PDF Repository
```

## 🛠 Setup Requirements

### 1. External Dependencies
- **Ollama:** Install from https://ollama.ai (Recommended model: `llama3`)
- **System Tools:** 
  - `poppler-utils` (for `pdftotext` and PDF conversion)
  - `tesseract-ocr` (for OCR fallback)

### 2. Python Environment
```bash
pip3 install -r requirements.txt
```

## 🎮 How to Use

1. **Student Access:**
   - Register/Login at `http://localhost:5001/login.html`
   - Browse the library and start an exam.
   - Use the "Submit & Grade" button for instant AI feedback.

2. **Admin Access:**
   - Log in with admin credentials.
   - Use **Exam Library Manager** to browse the `resources` folder and import new papers.
   - Use **User Management** to oversee student accounts.

## 📝 Configuration

- **Database:** Uses SQLite (`quizzes.db`) for all persistent data.
- **Port:** Default server runs on `5001`.
- **Logs:**
  - Quiz Server: `/tmp/quiz_server.log`
  - Ollama: `/tmp/ollama.log`

## ⚖️ License

Free to use and modify for educational purposes.
