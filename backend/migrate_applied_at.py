#!/usr/bin/env python3
"""
Міграція: Встановлення applied_at для існуючих клієнтів з кластера.

Цей скрипт сканує всі YAML файли в кластері та встановлює applied_at
для тих клієнтів, які вже є в базі даних, але не мають applied_at.

Використання:
    python3 migrate_applied_at.py
    
    або з опцією dry-run (без збереження):
    python3 migrate_applied_at.py --dry-run
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Додаємо app до sys.path
sys.path.insert(0, str(Path(__file__).parent))

# Завантажуємо .env
from dotenv import load_dotenv
load_dotenv()

from app.db import SessionLocal
from app.models import Client as ClientModel
from sqlalchemy import and_, or_
import yaml

# Конфігурація
PATH_K8S_PROD_DIR = os.getenv("PATH_K8S_PROD_DIR")


def scan_cluster_clients():
    """Сканує YAML файли кластера та повертає список hosts."""
    if not PATH_K8S_PROD_DIR or not os.path.isdir(PATH_K8S_PROD_DIR):
        print(f"❌ PATH_K8S_PROD_DIR не налаштовано або не існує: {PATH_K8S_PROD_DIR}")
        return set()
    
    hosts = set()
    print(f"📂 Сканування директорії: {PATH_K8S_PROD_DIR}")
    
    for name in os.listdir(PATH_K8S_PROD_DIR):
        if not (name.endswith(".yaml") or name.endswith(".yml")):
            continue
        
        full_path = os.path.join(PATH_K8S_PROD_DIR, name)
        try:
            with open(full_path) as f:
                data = yaml.safe_load(f)
            
            spec = (data or {}).get("spec") or {}
            rules = spec.get("rules") or []
            host = (rules[0].get("host") if rules else None) or ""
            
            if host:
                hosts.add(host)
                parts = host.split(".", 1)
                sub = parts[0]
                dom = parts[1] if len(parts) > 1 else ""
                hosts.add((dom, sub, full_path))
        except Exception as e:
            print(f"⚠️  Помилка читання {name}: {e}")
            continue
    
    print(f"✅ Знайдено {len(hosts)} клієнтів в кластері")
    return hosts


def migrate_applied_at(dry_run=False):
    """
    Встановлює applied_at для існуючих клієнтів з кластера.
    
    Args:
        dry_run: Якщо True, тільки показує що буде зроблено без збереження
    """
    db = SessionLocal()
    try:
        # Отримуємо всіх клієнтів без applied_at
        clients_without_applied = db.query(ClientModel).filter(
            ClientModel.applied_at.is_(None)
        ).all()
        
        print(f"\n📊 Знайдено {len(clients_without_applied)} клієнтів без applied_at")
        
        if not clients_without_applied:
            print("✅ Всі клієнти вже мають applied_at")
            return
        
        # Скануємо кластер
        cluster_clients = scan_cluster_clients()
        
        if not cluster_clients:
            print("⚠️  Не знайдено клієнтів в кластері")
            return
        
        # Створюємо мапу для швидкого пошуку
        cluster_map = {}
        for item in cluster_clients:
            if isinstance(item, tuple):
                dom, sub, path = item
                cluster_map[(dom, sub)] = path
        
        # Обробляємо клієнтів
        updated_count = 0
        now = datetime.utcnow()
        
        print(f"\n{'🔍' if dry_run else '✏️ '} {'Перевірка' if dry_run else 'Оновлення'} клієнтів...\n")
        
        for client in clients_without_applied:
            # Перевіряємо чи клієнт є в кластері
            key = (client.domain, client.subdomain)
            
            if key in cluster_map or client.ingress_path in [p for _, _, p in cluster_clients if isinstance(p, str)]:
                host = f"{client.subdomain}.{client.domain}" if client.domain and client.subdomain else "???"
                
                if dry_run:
                    print(f"  🔄 [{client.id}] {host}")
                    print(f"      → Буде встановлено applied_at")
                else:
                    client.applied_at = now
                    print(f"  ✅ [{client.id}] {host}")
                    print(f"      → applied_at = {now}")
                
                updated_count += 1
        
        if not dry_run and updated_count > 0:
            db.commit()
            print(f"\n✅ Успішно оновлено {updated_count} клієнтів")
        elif dry_run and updated_count > 0:
            print(f"\n🔍 Буде оновлено {updated_count} клієнтів (dry-run режим)")
        else:
            print(f"\nℹ️  Немає клієнтів для оновлення")
        
        # Статистика
        print("\n" + "="*60)
        print("📊 Статистика:")
        print(f"  • Всього клієнтів без applied_at: {len(clients_without_applied)}")
        print(f"  • Знайдено в кластері: {updated_count}")
        print(f"  • Залишилось без applied_at: {len(clients_without_applied) - updated_count}")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"❌ Помилка: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Міграція applied_at для існуючих клієнтів з кластера"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати що буде зроблено без збереження змін"
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("🔧 Міграція applied_at")
    print("="*60)
    
    if args.dry_run:
        print("⚠️  Режим DRY-RUN (зміни НЕ будуть збережені)\n")
    else:
        print("✏️  Режим PRODUCTION (зміни БУДУТЬ збережені)\n")
        response = input("Продовжити? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("❌ Скасовано")
            return
        print()
    
    migrate_applied_at(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
