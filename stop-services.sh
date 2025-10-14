#!/bin/bash

# Скрипт для зупинки всіх сервісів
echo "🛑 Зупиняю сервіси..."

# Зупинити backend
echo "  🔴 Зупиняю backend..."
pkill -f "uvicorn app.main:app" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  ✅ Backend зупинений"
else
    echo "  ℹ️ Backend не був запущений"
fi

# Зупинити frontend на порту 8080
echo "  🔴 Зупиняю frontend..."
FRONTEND_PID=$(lsof -ti:8080 2>/dev/null)
if [ ! -z "$FRONTEND_PID" ]; then
    kill -9 $FRONTEND_PID 2>/dev/null
    echo "  ✅ Frontend зупинений"
else
    echo "  ℹ️ Frontend не був запущений на порту 8080"
fi

# Зупинити будь-які інші HTTP сервери Python
pkill -f "python3 -m http.server" 2>/dev/null

echo "🏁 Всі сервіси зупинені"