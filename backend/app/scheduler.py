from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Client as ClientModel
import boto3
import os
from botocore.exceptions import ClientError

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
acm = boto3.client("acm", region_name=AWS_REGION)

scheduler = BackgroundScheduler()


def check_certificates():
    db: Session = SessionLocal()
    try:
        pending = db.query(ClientModel).filter(ClientModel.cert_status != "ISSUED").all()
        for rec in pending:
            if not rec.certificate_arn:
                continue
            try:
                desc = acm.describe_certificate(CertificateArn=rec.certificate_arn)
                status = desc["Certificate"]["Status"]
                if rec.cert_status != status:
                    rec.cert_status = status
                
                # Оновити валідаційні дані, якщо вони ще не готові
                if (not rec.dns_name or rec.dns_name == "Pending...") and status == "PENDING_VALIDATION":
                    domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
                    if domain_validation_options:
                        resource_record = domain_validation_options[0].get("ResourceRecord")
                        if resource_record:
                            rec.dns_name = resource_record["Name"]
                            rec.dns_value = resource_record["Value"]
                            print(f"Updated validation data for certificate {rec.certificate_arn}")
            except ClientError:
                pass
        db.commit()
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(check_certificates, IntervalTrigger(seconds=30), id="check_certs", replace_existing=True)
    scheduler.start()
