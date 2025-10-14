#!/usr/bin/env python3
"""
Виправлення applied_at: Перевірка реального стану в Kubernetes кластері.

Цей скрипт перевіряє які клієнти РЕАЛЬНО є в кластері (не тільки YAML файли)
та коректно встановлює/видаляє applied_at.

Використання:
    python3 fix_applied_at.py
    
    або з опцією dry-run (без збереження):
    python3 fix_applied_at.py --dry-run
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
from kubernetes import client as k8s_client, config as k8s_config


def get_deployed_hosts_from_k8s():
    """
    Отримує список hosts, які РЕАЛЬНО задеплоєні в Kubernetes кластері.
    """
    try:
        # Завантажуємо K8s конфігурацію
        if os.getenv("KUBECONFIG"):
            k8s_config.load_kube_config(config_file=os.getenv("KUBECONFIG"))
        else:
            k8s_config.load_kube_config()
        
        api = k8s_client.NetworkingV1Api()
        
        # Отримуємо всі Ingress з усіх namespace
        all_ingresses = api.list_ingress_for_all_namespaces()
        
        deployed_hosts = {}
        
        for ing in all_ingresses.items:
            namespace = ing.metadata.namespace
            rules = getattr(ing.spec, 'rules', []) or []
            
            for rule in rules:
                host = getattr(rule, 'host', None)
                if host:
                    deployed_hosts[host] = namespace
        
        print(f"✅ Знайдено {len(deployed_hosts)} Ingress в кластері")
        return deployed_hosts
        
    except Exception as e:
        print(f"❌ Помилка підключення до Kubernetes: {e}")
        return None


def fix_applied_at(dry_run=False):
    """
    Виправляє applied_at на основі реального стану кластера.
    
    Args:
        dry_run: Якщо True, тільки показує що буде зроблено без збереження
    """
    db = SessionLocal()
    try:
        # Отримуємо реальний стан кластера
        print("\n🔍 Перевірка стану Kubernetes кластера...")
        deployed_hosts = get_deployed_hosts_from_k8s()
        
        if deployed_hosts is None:
            print("⚠️  Неможливо отримати стан кластера. Міграція скасована.")
            return
        
        # Отримуємо всіх клієнтів
        all_clients = db.query(ClientModel).all()
        print(f"\n📊 Знайдено {len(all_clients)} клієнтів в базі")
        
        to_set_applied = []
        to_clear_applied = []
        correct_clients = []
        
        for client in all_clients:
            if not client.domain or not client.subdomain:
                continue
            
            host = f"{client.subdomain}.{client.domain}"
            is_deployed = host in deployed_hosts
            has_applied_at = bool(client.applied_at)
            
            if is_deployed and not has_applied_at:
                # Є в кластері, але немає applied_at
                to_set_applied.append((client, host))
            elif not is_deployed and has_applied_at:
                # Немає в кластері, але є applied_at
                to_clear_applied.append((client, host))
            else:
                # Все правильно
                correct_clients.append((client, host, is_deployed))
        
        # Виводимо результати
        print("\n" + "="*60)
        print("📋 Результати аналізу:")
        print("="*60)
        
        print(f"\n✅ Коректні клієнти: {len(correct_clients)}")
        for client, host, is_deployed in correct_clients[:5]:
            status = "deployed" if is_deployed else "not deployed"
            print(f"  • [{client.id}] {host} - {status}")
        if len(correct_clients) > 5:
            print(f"  ... та ще {len(correct_clients) - 5}")
        
        if to_set_applied:
            print(f"\n⚠️  Потрібно встановити applied_at: {len(to_set_applied)}")
            for client, host in to_set_applied:
                print(f"  • [{client.id}] {host}")
                print(f"      → Є в кластері, але немає applied_at")
        
        if to_clear_applied:
            print(f"\n⚠️  Потрібно очистити applied_at: {len(to_clear_applied)}")
            for client, host in to_clear_applied:
                print(f"  • [{client.id}] {host}")
                print(f"      → Немає в кластері, але є applied_at")
        
        # Виконуємо зміни
        if not dry_run and (to_set_applied or to_clear_applied):
            print(f"\n{'✏️ ' if not dry_run else '🔍 '}Застосування змін...\n")
            
            now = datetime.utcnow()
            
            for client, host in to_set_applied:
                client.applied_at = now
                print(f"  ✅ Встановлено applied_at для [{client.id}] {host}")
            
            for client, host in to_clear_applied:
                client.applied_at = None
                print(f"  ✅ Очищено applied_at для [{client.id}] {host}")
            
            db.commit()
            print(f"\n✅ Зміни збережено")
        elif dry_run and (to_set_applied or to_clear_applied):
            print(f"\n🔍 Режим DRY-RUN: зміни НЕ збережено")
        
        # Підсумок
        print("\n" + "="*60)
        print("📊 Фінальна статистика:")
        print("="*60)
        print(f"  • Всього клієнтів: {len(all_clients)}")
        print(f"  • Задеплоєні в кластері: {len(deployed_hosts)}")
        print(f"  • Коректні (applied_at відповідає стану): {len(correct_clients)}")
        print(f"  • Встановлено applied_at: {len(to_set_applied)}")
        print(f"  • Очищено applied_at: {len(to_clear_applied)}")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Виправлення applied_at на основі реального стану кластера"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показати що буде зроблено без збереження змін"
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("🔧 Виправлення applied_at")
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
    
    fix_applied_at(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
