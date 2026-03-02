#!/bin/bash

# Stop Quiz Servers Script

echo "============================================"
echo "🛑 Stopping Quiz Servers"
echo "============================================"
echo ""

# Stop quiz server
if pgrep -f "exam_server.py" > /dev/null; then
    echo "📊 Stopping Quiz Server..."
    pkill -f "exam_server.py"
    echo "✓ Quiz Server stopped"
else
    echo "ℹ️  Quiz Server not running"
fi

# Stop Ollama (optional - comment out if you want Ollama to keep running)
# Uncomment the next lines to also stop Ollama
# if pgrep -f "ollama serve" > /dev/null; then
#     echo "📦 Stopping Ollama..."
#     pkill -f "ollama serve"
#     echo "✓ Ollama stopped"
# else
#     echo "ℹ️  Ollama not running"
# fi

echo ""
echo "✅ Done"
