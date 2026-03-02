#!/bin/bash

# Start Quiz Servers Script
# This script ensures Ollama and the Quiz Server are running

echo "============================================"
echo "🚀 Starting Quiz Servers"
echo "============================================"

# Change to script directory
cd "$(dirname "$0")"

# Check if Ollama is running
echo ""
echo "📦 Checking Ollama..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Ollama is already running"
else
    echo "✗ Ollama not running, starting it..."
    OLLAMA_ORIGINS="*" ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3

    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "✓ Ollama started successfully"
    else
        echo "✗ Failed to start Ollama"
        echo "  Please install Ollama from: https://ollama.ai"
        exit 1
    fi
fi

# Check available models
echo ""
echo "🤖 Checking available models..."
MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | head -5)
if [ -n "$MODELS" ]; then
    echo "✓ Available models:"
    echo "$MODELS" | sed 's/^/  - /'
else
    echo "⚠️  No models found. Pull one with: ollama pull llama3"
fi

# Kill existing quiz server on port 5001
echo ""
echo "📊 Checking Quiz Server..."
if lsof -ti:5001 > /dev/null 2>&1; then
    echo "  Stopping old server..."
    pkill -f "email_server.py" 2>/dev/null
    sleep 1
fi

# Start the quiz server
echo "  Starting Quiz Server..."
nohup python3 -u email_server.py > /tmp/quiz_server.log 2>&1 < /dev/null &
sleep 2

# Verify server is running
if curl -s http://localhost:5001/health > /dev/null 2>&1; then
    echo "✓ Quiz Server started successfully"
else
    echo "✗ Failed to start Quiz Server"
    echo "  Check log: tail -f /tmp/quiz_server.log"
    exit 1
fi

echo ""
echo "============================================"
echo "✅ All servers running!"
echo "============================================"
echo ""
echo "🌐 Open in your browser:"
echo "   http://localhost:5001/"
echo ""
echo "📝 Logs:"
echo "   Ollama:    tail -f /tmp/ollama.log"
echo "   Quiz:      tail -f /tmp/quiz_server.log"
echo ""
echo "🛑 To stop servers:"
echo "   pkill -f email_server.py"
echo "   pkill -f 'ollama serve'"
echo ""
