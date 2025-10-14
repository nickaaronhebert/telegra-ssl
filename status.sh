#!/bin/bash

# Скрипт для перевірки статусу сервісів
echo "📊 Статус Client Onboarding Service"
echo "======================================"

# Перевірити backend
echo "🔧 Backend (Port 8000):"
BACKEND_PID=$(pgrep -f "uvicorn app.main:app")
if [ ! -z "$BACKEND_PID" ]; then
    echo "  ✅ Запущений (PID: $BACKEND_PID)"
    
    # Перевірити чи відповідає HTTP
    if curl -s http://localhost:8000/docs > /dev/null 2>&1; then
        echo "  🌐 HTTP відповідає"
    else
        echo "  ⚠️ HTTP не відповідає"
    fi
else
    echo "  ❌ Не запущений"
fi

echo ""

# Перевірити frontend
echo "🌐 Frontend (Port 8080):"
FRONTEND_PID=$(lsof -ti:8080 2>/dev/null)
if [ ! -z "$FRONTEND_PID" ]; then
    echo "  ✅ Запущений (PID: $FRONTEND_PID)"
    
    # Перевірити чи відповідає HTTP
    if curl -s http://localhost:8080 > /dev/null 2>&1; then
        echo "  🌐 HTTP відповідає"
    else
        echo "  ⚠️ HTTP не відповідає"
    fi
else
    echo "  ❌ Не запущений"
fi

echo ""

# Показати останні логи, якщо файли існують
if [ -f "logs/backend.log" ]; then
    echo "📝 Останні 3 рядки backend логів:"
    tail -n 3 logs/backend.log | sed 's/^/  /'
fi

echo ""

if [ -f "logs/frontend.log" ]; then
    echo "📝 Останні 3 рядки frontend логів:"
    tail -n 3 logs/frontend.log | sed 's/^/  /'
fi

echo ""
echo "🔗 Корисні посилання:"
echo "  Frontend:  http://localhost:8080"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"