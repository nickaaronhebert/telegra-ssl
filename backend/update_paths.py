import sys
sys.path.insert(0, '/home/ubuntu/client-onboarding-service/backend')
from app.db import SessionLocal
from sqlalchemy import text
db = SessionLocal()
result = db.execute(text("UPDATE clients SET ingress_path = REPLACE(ingress_path, '/Users/andriisverlovych/Work/TeleMD/telemdnow-k8s', '/home/ubuntu/telemdnow-k8s') WHERE ingress_path LIKE '/Users/%'"))
print(f"Updated {result.rowcount} records")
db.commit()
db.close()
