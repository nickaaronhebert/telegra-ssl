#!/bin/bash

# Скрипт для запуску backend сервісу
echo "🚀 Запускаю backend сервіс..."

# Зупинити поточний процес, якщо він запущений
pkill -f "uvicorn app.main:app" 2>/dev/null

# Перейти до папки проекту та завантажити .env
cd "$(dirname "$0")"
source .env

# Запустити backend з логами у файл
mkdir -p logs
nohup .venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --app-dir backend \
  > logs/backend.log 2>&1 &

echo "✅ Backend запущений на http://localhost:8000"
echo "📝 Логи зберігаються в logs/backend.log"
echo "🔍 Щоб переглянути логи в реальному часі: tail -f logs/backend.log"