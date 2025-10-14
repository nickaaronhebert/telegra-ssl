#!/bin/bash

# Скрипт для запуску frontend сервісу
echo "🌐 Запускаю frontend сервіс..."

# Зупинити поточний процес на порту 8080, якщо він запущений
lsof -ti:8080 | xargs kill -9 2>/dev/null

# Перейти до папки проекту
cd "$(dirname "$0")"

# Запустити frontend з логами у файл
mkdir -p logs
cd frontend
nohup python3 -m http.server 8080 > ../logs/frontend.log 2>&1 &

echo "✅ Frontend запущений на http://localhost:8080"
echo "📝 Логи зберігаються в logs/frontend.log"
echo "🔗 Відкрити в браузері: open http://localhost:8080"