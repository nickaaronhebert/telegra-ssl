from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from .db import Base

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, index=True, nullable=False)
    subdomain = Column(String, nullable=False)
    affiliate = Column(String, nullable=False)
    namespace = Column(String, default="prod")
    group_name = Column(String, nullable=True)

    certificate_arn = Column(String, nullable=True)
    cert_status = Column(String, nullable=True)
    dns_name = Column(String, nullable=True)
    dns_value = Column(String, nullable=True)

    ingress_path = Column(Text, nullable=True)

    pr_number = Column(Integer, nullable=True)

    applied_at = Column(DateTime, nullable=True)
    
    # DNS check results (client domain -> ALB)
    dns_check_status = Column(String, nullable=True)  # correct, incorrect, missing, error, not_checked
    dns_check_resolved_to = Column(String, nullable=True)  # CNAME target
    dns_check_resolved_ips = Column(Text, nullable=True)  # JSON array of IPs
    dns_check_error = Column(Text, nullable=True)  # Error message if any
    dns_check_last_checked = Column(DateTime, nullable=True)  # When was it last checked
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
