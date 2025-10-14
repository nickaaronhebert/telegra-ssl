#!/bin/bash

# Скрипт для запуску всіх сервісів
echo "🚀 Запускаю Client Onboarding Service..."

# Перейти до папки проекту
cd "$(dirname "$0")"

# Зупинити поточні процеси
echo "🛑 Зупиняю попередні процеси..."
./stop-services.sh

echo ""
echo "⏳ Чекаю 2 секунди..."
sleep 2

# Запустити backend
echo "🔧 Запускаю backend..."
./start-backend.sh

echo ""
echo "⏳ Чекаю запуску backend (3 секунди)..."
sleep 3

# Запустити frontend
echo "🌐 Запускаю frontend..."
./start-frontend.sh

echo ""
echo "🎉 Всі сервіси запущені!"
echo "📊 Backend API: http://localhost:8000"
echo "🌐 Frontend:    http://localhost:8080"
echo "📖 API Docs:    http://localhost:8000/docs"
echo ""
echo "📝 Логи:"
echo "  - Backend:  logs/backend.log"
echo "  - Frontend: logs/frontend.log"
echo ""
echo "🔍 Для перегляду логів:"
echo "  tail -f logs/backend.log"
echo "  tail -f logs/frontend.log"