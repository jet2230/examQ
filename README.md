# Exam Question Generator

Generate multiple-choice quizzes using LLaMA (Ollama).

## Quick Start

### Start Everything (One Command)
```bash
./start_servers.sh
```

Then open your browser to:
```
http://localhost:5001/
```

## What This Does

1. **Checks Ollama** - Ensures Ollama is running (starts it if not)
2. **Starts Quiz Server** - Starts the Flask server on port 5001
3. **Auto-Saves Quizzes** - Generated quizzes save to the project directory

## Features

- ✅ Generate quiz questions from any topic using LLaMA
- ✅ Multiple choice questions (A, B, C, D)
- ✅ Beautiful, styled interface
- ✅ Auto-save to project directory
- ✅ Take quizzes offline
- ✅ Email results (optional setup required)
- ✅ Smart autocomplete for common topics

## File Structure

```
/home/obo/playground/examQ/
├── exam_generator_v2.html    # Main quiz generator web interface
├── quiz_template.html         # Template for standalone quizzes
├── email_server.py            # Flask server for saving & email
├── start_servers.sh           # Start all servers
├── stop_servers.sh            # Stop quiz server
└── *_quiz.html                # Generated quizzes (auto-created)
```

## Commands

### Start Servers
```bash
./start_servers.sh
```

### Stop Servers
```bash
./stop_servers.sh
```

### View Logs
```bash
# Ollama logs
tail -f /tmp/ollama.log

# Quiz server logs
tail -f /tmp/quiz_server.log
```

### Check Status
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Check if quiz server is running
curl http://localhost:5001/health
```

## Setup Requirements

1. **Ollama** - Install from https://ollama.ai
2. **Python 3** - For Flask server
3. **Dependencies:**
   ```bash
   pip3 install Flask flask-cors
   ```

## How to Use

1. **Start servers:** `./start_servers.sh`
2. **Open browser:** http://localhost:5001/
3. **Enter topic:** e.g., "Biology IGCSE blood cells"
4. **Select number of questions:** 1-20
5. **Click "Generate Quiz"**
6. **Quiz auto-saves** to project directory!
7. **Open saved quiz** to take it offline

## Email Setup (Optional)

To email quiz results to `jet2230@gmail.com`:

1. Go to https://myaccount.google.com/security
2. Enable 2-Step Verification
3. Generate App Password
4. Update `SMTP_PASSWORD` in `email_server.py`
5. Restart server: `./stop_servers.sh && ./start_servers.sh`

## Troubleshooting

### Port 5001 already in use
```bash
pkill -f email_server.py
./start_servers.sh
```

### Ollama not responding
```bash
pkill -f ollama
OLLAMA_ORIGINS="*" ollama serve
```

### Quiz not saving
- Check server is running: `curl http://localhost:5001/health`
- Check logs: `tail -f /tmp/quiz_server.log`

## Model Information

Default model: `llama3`

To pull more models:
```bash
ollama pull llama2
ollama pull mistral
ollama pull codellama
```

## License

Free to use and modify.
