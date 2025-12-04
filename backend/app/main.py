from fastapi import FastAPI, HTTPException, Depends, Request
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import os
import re
import base64
import time
import asyncio
import boto3
import httpx
from botocore.exceptions import ClientError
from kubernetes import client as k8s_client, config as k8s_config
import yaml
from dotenv import load_dotenv
from github import Github
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi import Body, Query
from .db import SessionLocal, engine
from .models import Client as ClientModel
import subprocess

load_dotenv()

app = FastAPI(title="Client Onboarding Service", version="0.2.0")

# Налаштування логування
def setup_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO")
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Створюємо директорію для логів
    log_dir = "/app/logs" if os.path.exists("/app") else "./logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # Налаштовуємо root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            # Консольний вивід
            logging.StreamHandler(sys.stdout),
            # Файловий логер з ротацією
            RotatingFileHandler(
                os.path.join(log_dir, "client-onboarding.log"),
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
        ]
    )
    
    # Логер для нашого додатку
    logger = logging.getLogger("client-onboarding")
    return logger

logger = setup_logging()

# CORS to allow local frontends on any port
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://18.220.173.169:8080", "http://3.14.236.248:8080",
        "http://localhost:8080", "http://127.0.0.1:8080", "http://0.0.0.0:8080",
        "http://localhost:3000", "http://127.0.0.1:3000", "http://0.0.0.0:3000"
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create DB tables
from .db import Base
Base.metadata.create_all(bind=engine)

# Start background scheduler
from .scheduler import start_scheduler
start_scheduler()

logger.info("Client Onboarding Service starting up...")


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Перевіряємо підключення до бази даних
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_status = "healthy"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_status = "unhealthy"
        finally:
            db.close()
        
        # Перевіряємо AWS підключення
        aws_status = "healthy"
        try:
            acm.list_certificates(MaxItems=1)
        except Exception as e:
            logger.warning(f"AWS health check failed: {e}")
            aws_status = "degraded"
        
        # Перевіряємо K8s підключення
        k8s_status = "healthy"
        try:
            ensure_k8s_config()
            if not _k8s_loaded:
                k8s_status = "unavailable"
        except Exception as e:
            logger.warning(f"K8s health check failed: {e}")
            k8s_status = "degraded"
        
        overall_status = "healthy"
        if db_status == "unhealthy":
            overall_status = "unhealthy"
        elif aws_status == "degraded" or k8s_status == "degraded":
            overall_status = "degraded"
        
        health_data = {
            "status": overall_status,
            "timestamp": time.time(),
            "services": {
                "database": db_status,
                "aws": aws_status,
                "kubernetes": k8s_status
            },
            "version": "0.2.0"
        }
        
        # Логуємо статус тільки при проблемах
        if overall_status != "healthy":
            logger.warning(f"Health check status: {overall_status}, services: {health_data['services']}")
        
        return health_data
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time()
        }

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

AWS_PROFILE = os.getenv("AWS_PROFILE")
AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
PATH_K8S_PROD_DIR = os.getenv("PATH_K8S_PROD_DIR")
ALB_GROUP_NAME_DEFAULT = os.getenv("ALB_GROUP_NAME", "telemd-public3")
MAX_CERTS_PER_GROUP = int(os.getenv("MAX_CERTS_PER_GROUP", "25"))

# Система множинних ALB груп з відповідними DNS іменами
# Формат: ALB_GROUP_MAPPINGS="group1:hostname1.elb.amazonaws.com,group2:hostname2.elb.amazonaws.com"
ALB_GROUP_MAPPINGS_RAW = os.getenv("ALB_GROUP_MAPPINGS", "")

# Стратегія створення нових ALB груп
ALB_CREATION_STRATEGY = os.getenv("ALB_CREATION_STRATEGY", "k8s-controller")  # k8s-controller, manual, notify-only

# Парсинг мапінгу груп до DNS імен
def parse_alb_group_mappings() -> Dict[str, str]:
    """Парсинг конфігурації ALB груп з їх DNS іменами"""
    mappings = {}
    if ALB_GROUP_MAPPINGS_RAW:
        for mapping in ALB_GROUP_MAPPINGS_RAW.split(","):
            if ":" in mapping:
                group, hostname = mapping.strip().split(":", 1)
                mappings[group.strip()] = hostname.strip()
    
    # Якщо є базова конфігурація з env
    legacy_hostname = os.getenv("ALB_PUBLIC_HOSTNAME")
    if legacy_hostname:
        mappings[ALB_GROUP_NAME_DEFAULT] = legacy_hostname
    
    return mappings

# Глобальна змінна з мапінгом груп до DNS імен
ALB_GROUP_MAPPINGS = parse_alb_group_mappings()

# Legacy змінна для сумісності
ALB_PUBLIC_HOSTNAME = os.getenv("ALB_PUBLIC_HOSTNAME")

# Cache для ALB DNS імені
_alb_dns_cache = {}
# Cache для DNS перевірок
_dns_check_cache = {}
# Git automation flags for ingress manifests
GIT_AUTOCOMMIT_INGRESS = os.getenv("GIT_AUTOCOMMIT_INGRESS", "false").lower() == "true"
GIT_AUTOPUSH_INGRESS = os.getenv("GIT_AUTOPUSH_INGRESS", "false").lower() == "true"
# Target branch to store ingress configs (will be created/checked-out automatically)
GIT_INGRESS_BRANCH = os.getenv("GIT_INGRESS_BRANCH", "patient-redirects")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_DEFAULT_BRANCH = os.getenv("GITHUB_DEFAULT_BRANCH", "main")

if AWS_PROFILE:
    os.environ["AWS_PROFILE"] = AWS_PROFILE

acm = boto3.client("acm", region_name=AWS_REGION)

gh = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None

# Translation helper
def get_user_language(request: Request) -> str:
    """Get user language from Accept-Language header or default to 'uk'"""
    accept_language = request.headers.get('accept-language', 'uk')
    # Parse Accept-Language header (e.g., "en-US,en;q=0.9,uk;q=0.8")
    if accept_language:
        # Get first language code
        lang = accept_language.split(',')[0].split('-')[0].lower()
        return 'en' if lang == 'en' else 'uk'
    return 'uk'

def translate(en_text: str, uk_text: str, lang: str = 'uk') -> str:
    """Return text in specified language"""
    return en_text if lang == 'en' else uk_text

class CreateClientReq(BaseModel):
    domain: str = Field(..., examples=["example.com"])
    subdomain: str = Field("patient", examples=["patient", "care"])
    affiliate: str
    namespace: str = Field("prod", examples=["prod"])  # наразі лише prod
    group_name: Optional[str] = Field(None, description="ALB group name, e.g., telemd-public3")
    create_pr: bool = Field(False, description="Create PR in frontend repo to update nginx/default.conf")
    auto_merge: bool = Field(False, description="Auto-merge PR if possible")

class ClientDNSResp(BaseModel):
    id: int
    certificate_arn: str
    dns_name: str
    dns_value: str
    ingress_path: str
    group_name: Optional[str] = None
    cert_status: Optional[str] = None
    # Extra fields for convenient rendering on the frontend
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    alb_dns_name: Optional[str] = None

class ApplyReq(BaseModel):
    # опційно можна передати override до шляху
    ingress_path: Optional[str] = None
    namespace: str = Field("prod")

class ReissueReq(BaseModel):
    domain: str

class ReissueFullReq(BaseModel):
    domain: str
    update_ingress: bool = Field(True, description="Update ingress file with new ARN / Оновити файл інгресу з новим ARN")
    update_database: bool = Field(True, description="Update ARN in database / Оновити ARN в базі даних")
    delete_old_cert: bool = Field(True, description="Delete old certificate immediately / Видалити старий сертифікат відразу")


def ensure_prod_dir():
    if not PATH_K8S_PROD_DIR:
        raise RuntimeError("PATH_K8S_PROD_DIR is not configured in env")
    os.makedirs(PATH_K8S_PROD_DIR, exist_ok=True)


def build_ingress_yaml(domain: str, subdomain: str, namespace: str, certificate_arn: str, group_name: Optional[str] = None) -> str:
    host = f"{subdomain}.{domain}"
    # Desired name format: {domain_root}-patient-frontend-public
    domain_root = (domain.split(".", 1)[0] if domain else "").replace("_", "-")
    name = f"{domain_root}-patient-frontend-public" if domain_root else host.replace(".", "-")
    group = group_name or ALB_GROUP_NAME_DEFAULT

    ssl_redirect_action = '{"Type": "redirect", "RedirectConfig": { "Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"}}'

    ing = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "annotations": {
                # Redirect HTTP to HTTPS
                "alb.ingress.kubernetes.io/actions.ssl-redirect": ssl_redirect_action,
                # ACM certificate
                "alb.ingress.kubernetes.io/certificate-arn": certificate_arn,
                # ALB group
                "alb.ingress.kubernetes.io/group.name": group,
                # Listeners and target settings
                "alb.ingress.kubernetes.io/listen-ports": '[{"HTTP": 80}, {"HTTPS":443}]',
                "alb.ingress.kubernetes.io/scheme": "internet-facing",
                "alb.ingress.kubernetes.io/target-type": "ip",
                # Ingress class via annotation (to match desired manifest shape)
                "kubernetes.io/ingress.class": "alb",
            },
        },
        "spec": {
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": "ssl-redirect",
                                        "port": {"name": "use-annotation"}
                                    }
                                }
                            }
                        ]
                    }
                },
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": "telemd-patient-frontend-svc",
                                        "port": {"number": 80}
                                    }
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
    return yaml.safe_dump(ing, sort_keys=False)


def write_ingress_file(domain: str, subdomain: str, namespace: str, certificate_arn: str, group_name: Optional[str] = None) -> str:
    ensure_prod_dir()
    filename = f"{subdomain}.{domain}.yaml"
    full_path = os.path.join(PATH_K8S_PROD_DIR, filename)
    content = build_ingress_yaml(domain, subdomain, namespace, certificate_arn, group_name)
    with open(full_path, "w") as f:
        f.write(content)
    return full_path


@app.post("/clients", response_model=ClientDNSResp)
def create_client(req: CreateClientReq, db: Session = Depends(get_db)):
    logger.info(f"Creating client: {req.subdomain}.{req.domain} (affiliate: {req.affiliate})")
    
    # 0) Idempotency: if a client with the same (domain, subdomain, namespace) exists, return it
    existing = db.query(ClientModel).filter(
        and_(
            ClientModel.domain == req.domain,
            ClientModel.subdomain == req.subdomain,
            ClientModel.namespace == (req.namespace or "prod"),
        )
    ).order_by(ClientModel.id.desc()).first()
    if existing:
        logger.info(f"Returning existing client: {existing.id} for {req.subdomain}.{req.domain}")
        return ClientDNSResp(
            id=existing.id,
            certificate_arn=existing.certificate_arn or "",
            dns_name=existing.dns_name or "",
            dns_value=existing.dns_value or "",
            ingress_path=existing.ingress_path or "",
            group_name=existing.group_name,
            cert_status=existing.cert_status,
            domain=existing.domain,
            subdomain=existing.subdomain,
            alb_dns_name=get_alb_dns_name(existing.group_name),
        )

    # 1) Request ACM wildcard cert
    try:
        logger.info(f"Requesting SSL certificate for *.{req.domain}")
        resp = acm.request_certificate(
            DomainName=f"*.{req.domain}",
            ValidationMethod="DNS",
            Options={"CertificateTransparencyLoggingPreference": "ENABLED"},
            KeyAlgorithm="RSA_2048",
        )
        arn = resp["CertificateArn"]
        
        # Чекаємо на валідаційні дані з retry-логікою
        dns_name = "Pending..."
        dns_value = "DNS validation records will be available shortly. Check /cert/validation/{arn} endpoint."
        
        # Спробуємо отримати валідаційні дані з невеликими затримками
        import time
        max_retries = 6  # максимум 30 секунд (6 * 5 секунд)
        retry_delay = 5  # секунд
        
        for attempt in range(max_retries):
            try:
                desc = acm.describe_certificate(CertificateArn=arn)
                domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
                if domain_validation_options:
                    resource_record = domain_validation_options[0].get("ResourceRecord")
                    if resource_record:
                        dns_name = resource_record["Name"]
                        dns_value = resource_record["Value"]
                        print(f"Got validation data on attempt {attempt + 1}")
                        break
                # Якщо даних немає, чекаємо перед наступною спробою
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
    except ClientError as e:
        # Log the specific AWS error for debugging
        logger.error(f"AWS ClientError for {req.subdomain}.{req.domain}: {e}")
        raise HTTPException(status_code=400, detail=f"AWS Certificate Manager error: {e}")
    except Exception as e:
        # Catch any other unexpected errors
        print(f"Unexpected error in create_client: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    # 2) Обрати робочу ALB group.name з урахуванням ліміту
    chosen_group = choose_group_name(req.group_name or ALB_GROUP_NAME_DEFAULT)

    # 3) Write ingress YAML (prod/<sub>.<domain>.yaml), з урахуванням group.name
    ingress_path = write_ingress_file(req.domain, req.subdomain, req.namespace, arn, chosen_group)

    # 4) Зберігаємо в БД
    client_rec = ClientModel(
        domain=req.domain,
        subdomain=req.subdomain,
        affiliate=req.affiliate,
        namespace=req.namespace,
        group_name=chosen_group,
        certificate_arn=arn,
        cert_status="PENDING_VALIDATION",
        dns_name=dns_name,
        dns_value=dns_value,
        ingress_path=ingress_path,
    )
    db.add(client_rec)
    db.commit()
    db.refresh(client_rec)

    # 4) Опціонально: створити PR у frontend-репозиторії для nginx/default.conf
    if req.create_pr:
        if not (gh and GITHUB_OWNER and GITHUB_REPO):
            raise HTTPException(status_code=400, detail="GitHub integration is not configured")
        try:
            pr_num = create_frontend_pr(domain=req.domain, subdomain=req.subdomain, affiliate=req.affiliate, auto_merge=req.auto_merge)
            client_rec.pr_number = pr_num
            db.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"GitHub PR failed: {e}")

    return ClientDNSResp(
        id=client_rec.id,
        certificate_arn=arn,
        dns_name=dns_name,
        dns_value=dns_value,
        ingress_path=ingress_path,
        group_name=client_rec.group_name,
        cert_status=client_rec.cert_status,
        domain=client_rec.domain,
        subdomain=client_rec.subdomain,
        alb_dns_name=get_alb_dns_name(client_rec.group_name),
    )


def apply_ingress_file(path: str, namespace: str):
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Ingress file not found: {path}")
    with open(path) as f:
        manifest_yaml = f.read()
    try:
        # Використовуємо kubeconfig з оточення
        if os.getenv("KUBECONFIG"):
            k8s_config.load_kube_config(config_file=os.getenv("KUBECONFIG"))
        else:
            k8s_config.load_kube_config()
        obj = yaml.safe_load(manifest_yaml)
        api = k8s_client.NetworkingV1Api()
        name = obj["metadata"]["name"]
        ns = namespace
        try:
            existing = api.read_namespaced_ingress(name, ns)
            obj["metadata"]["resourceVersion"] = existing.metadata.resource_version
            api.replace_namespaced_ingress(name=name, namespace=ns, body=obj)
        except k8s_client.exceptions.ApiException as e:
            if e.status == 404:
                api.create_namespaced_ingress(namespace=ns, body=obj)
            else:
                raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "applied", "namespace": namespace, "path": path}


def _git_commit_and_maybe_push(file_path: str, message: str) -> dict:
    """Stages file_path, commits with message, and optionally pushes current branch.
    Returns a dict with committed/pushed flags and branch/repo info.
    """
    if not file_path:
        return {"committed": False, "pushed": False, "reason": "no file"}
    repo_dir = os.path.dirname(file_path)
    # Ensure we're inside a git work tree
    try:
        proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_dir, capture_output=True, text=True)
        if proc.returncode != 0 or proc.stdout.strip() != "true":
            return {"committed": False, "pushed": False, "reason": "not a git repo"}
    except Exception as e:
        return {"committed": False, "pushed": False, "error": str(e)}

    committed = False
    pushed = False
    branch = None
    repo_top = None
    try:
        # Top-level
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo_dir, capture_output=True, text=True)
        if top.returncode == 0:
            repo_top = top.stdout.strip()
        # Ensure we are on the desired branch
        desired = GIT_INGRESS_BRANCH
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
        current_branch = cur.stdout.strip() if cur.returncode == 0 else None
        if desired and desired != current_branch:
            # Check if local branch exists
            have_local = subprocess.run(["git", "show-ref", "--verify", f"refs/heads/{desired}"], cwd=repo_dir)
            if have_local.returncode == 0:
                co = subprocess.run(["git", "checkout", desired], cwd=repo_dir, capture_output=True, text=True)
                if co.returncode == 0:
                    current_branch = desired
                else:
                    # Try remote branch
                    ls = subprocess.run(["git", "ls-remote", "--heads", "origin", desired], cwd=repo_dir, capture_output=True, text=True)
                    if ls.returncode == 0 and ls.stdout.strip():
                        subprocess.run(["git", "fetch", "origin", desired], cwd=repo_dir, capture_output=True, text=True)
                        cob = subprocess.run(["git", "checkout", "-b", desired, f"origin/{desired}"], cwd=repo_dir, capture_output=True, text=True)
                        if cob.returncode == 0:
                            current_branch = desired
                    else:
                        # Create new local branch
                        cob2 = subprocess.run(["git", "checkout", "-b", desired], cwd=repo_dir, capture_output=True, text=True)
                        if cob2.returncode == 0:
                            current_branch = desired
        branch = current_branch

        # Stage file
        add = subprocess.run(["git", "add", file_path], cwd=repo_dir, capture_output=True, text=True)
        if add.returncode != 0:
            return {"committed": False, "pushed": False, "error": add.stderr.strip(), "repo": repo_top, "branch": branch}
        # Any staged changes?
        diff = subprocess.run(["git", "diff", "--cached", "--quiet", "--", file_path], cwd=repo_dir)
        if diff.returncode == 0:
            # no changes
            return {"committed": False, "pushed": False, "repo": repo_top, "branch": branch}
        # Commit
        commit = subprocess.run(["git", "commit", "-m", message, "--", file_path], cwd=repo_dir, capture_output=True, text=True)
        committed = (commit.returncode == 0)
        if not committed:
            return {"committed": False, "pushed": False, "error": commit.stderr.strip(), "repo": repo_top, "branch": branch}
        # Push if enabled
        if GIT_AUTOPUSH_INGRESS:
            # Check upstream
            upstream = subprocess.run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=repo_dir, capture_output=True, text=True)
            if upstream.returncode != 0 and branch:
                push = subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_dir, capture_output=True, text=True)
            else:
                push = subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, text=True)
            pushed = (push.returncode == 0)
        return {"committed": committed, "pushed": pushed, "branch": branch, "repo": repo_top}
    except Exception as e:
        return {"committed": committed, "pushed": pushed, "error": str(e), "branch": branch, "repo": repo_top}


@app.post("/clients/apply")
def apply_ingress(req: ApplyReq, db: Session = Depends(get_db)):
    path = req.ingress_path or None
    if not path:
        raise HTTPException(status_code=400, detail="ingress_path is required if not managed in DB")

    result = apply_ingress_file(path, req.namespace)

    # Позначимо застосування у БД, якщо запис існує
    rec = db.query(ClientModel).filter(ClientModel.ingress_path == path).first()
    if rec:
        from datetime import datetime
        rec.applied_at = datetime.utcnow()
        db.commit()

    return result


@app.get("/cert/status/{arn:path}")
def cert_status(arn: str):
    try:
        desc = acm.describe_certificate(CertificateArn=arn)
        status = desc["Certificate"]["Status"]
        return {"arn": arn, "status": status}
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/cert/validation/{arn:path}")
def cert_validation(arn: str):
    """Отримати DNS валідаційні дані для сертифіката"""
    try:
        desc = acm.describe_certificate(CertificateArn=arn)
        status = desc["Certificate"]["Status"]
        
        domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
        if not domain_validation_options:
            return {
                "arn": arn,
                "status": status,
                "validation_ready": False,
                "dns_name": None,
                "dns_value": None,
                "message": "DNS validation records are not ready yet. Please wait a few minutes and try again."
            }
        
        resource_record = domain_validation_options[0].get("ResourceRecord")
        if not resource_record:
            return {
                "arn": arn,
                "status": status,
                "validation_ready": False,
                "dns_name": None,
                "dns_value": None,
                "message": "DNS validation records are not ready yet. Please wait a few minutes and try again."
            }
        
        return {
            "arn": arn,
            "status": status,
            "validation_ready": True,
            "dns_name": resource_record["Name"],
            "dns_value": resource_record["Value"],
            "message": "DNS validation records are ready. Add these to your DNS provider."
        }
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/clients")
def list_clients(db: Session = Depends(get_db)):
    recs = db.query(ClientModel).order_by(ClientModel.id.desc()).all()
    out = []
    seen = set()
    for r in recs:
        key = (r.domain or "", r.subdomain or "", r.namespace or "prod")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": r.id,
            "domain": r.domain,
            "subdomain": r.subdomain,
            "affiliate": r.affiliate,
            "namespace": r.namespace,
            "group_name": r.group_name,
            "certificate_arn": r.certificate_arn,
            "cert_status": r.cert_status,
            "dns_name": r.dns_name,
            "dns_value": r.dns_value,
            "ingress_path": r.ingress_path,
            "pr_number": r.pr_number,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


def _scan_prod_files(domain: Optional[str] = None, db: Session = None):
    items = []
    if not PATH_K8S_PROD_DIR or not os.path.isdir(PATH_K8S_PROD_DIR):
        raise HTTPException(status_code=400, detail="PATH_K8S_PROD_DIR is not configured or does not exist")
    for name in os.listdir(PATH_K8S_PROD_DIR):
        if not (name.endswith(".yaml") or name.endswith(".yml")):
            continue
        full_path = os.path.join(PATH_K8S_PROD_DIR, name)
        try:
            with open(full_path) as f:
                data = yaml.safe_load(f)
            meta = (data or {}).get("metadata") or {}
            ann = meta.get("annotations") or {}
            spec = (data or {}).get("spec") or {}
            rules = spec.get("rules") or []
            host = (rules[0].get("host") if rules else None) or ""
            if not host:
                continue
            if domain and (not host.endswith(domain)):
                continue
            certificate_arn = ann.get("alb.ingress.kubernetes.io/certificate-arn")
            group_name = ann.get("alb.ingress.kubernetes.io/group.name")
            namespace = meta.get("namespace") or "prod"
            parts = host.split(".", 1)
            sub = parts[0]
            dom = parts[1] if len(parts) > 1 else ""
            # cert status
            cert_status = None
            if certificate_arn:
                try:
                    desc = acm.describe_certificate(CertificateArn=certificate_arn)
                    cert_status = desc["Certificate"]["Status"]
                except ClientError:
                    cert_status = None
            # existence in DB
            existing_id = None
            exists = False
            if db is not None:
                rec = db.query(ClientModel).filter(
                    or_(ClientModel.ingress_path == full_path,
                        and_(ClientModel.domain == dom, ClientModel.subdomain == sub))
                ).first()
                if rec:
                    exists = True
                    existing_id = rec.id
            items.append({
                "host": host,
                "domain": dom,
                "subdomain": sub,
                "group_name": group_name,
                "certificate_arn": certificate_arn,
                "cert_status": cert_status,
                "namespace": namespace,
                "file": name,
                "path": full_path,
                "exists": exists,
                "existing_id": existing_id,
            })
        except Exception as e:
            items.append({"file": name, "error": str(e)})
    return items


def _upsert_item(item: dict, db: Session):
    """
    Імпортує клієнта з YAML файлу кластера.
    Автоматично встановлює applied_at, оскільки якщо клієнт є в кластері - він задеплоєний.
    """
    from datetime import datetime
    
    dom = item.get("domain")
    sub = item.get("subdomain")
    full_path = item.get("path")
    certificate_arn = item.get("certificate_arn")
    cert_status = item.get("cert_status") or "UNKNOWN"
    namespace = item.get("namespace") or "prod"
    group_name = item.get("group_name") or ALB_GROUP_NAME_DEFAULT
    rec = db.query(ClientModel).filter(
        or_(ClientModel.ingress_path == full_path,
            and_(ClientModel.domain == dom, ClientModel.subdomain == sub))
    ).first()
    created = False
    if not rec:
        # Новий клієнт з кластера - одразу позначаємо як deployed
        rec = ClientModel(
            domain=dom,
            subdomain=sub,
            affiliate="",
            namespace=namespace,
            group_name=group_name,
            certificate_arn=certificate_arn,
            cert_status=cert_status,
            dns_name=None,
            dns_value=None,
            ingress_path=full_path,
            applied_at=datetime.utcnow(),  # Встановлюємо applied_at
        )
        db.add(rec)
        created = True
    else:
        # Оновлюємо існуючого клієнта
        rec.namespace = namespace
        rec.group_name = group_name or rec.group_name
        rec.certificate_arn = certificate_arn or rec.certificate_arn
        rec.cert_status = cert_status or rec.cert_status
        rec.ingress_path = full_path
        
        # Якщо ще не має applied_at - встановлюємо (він є в кластері, значить deployed)
        if not rec.applied_at:
            rec.applied_at = datetime.utcnow()
    
    db.commit()
    db.refresh(rec)
    return rec, created


@app.get("/clients/import/preview")
def import_preview(domain: Optional[str] = None, db: Session = Depends(get_db)):
    items = _scan_prod_files(domain, db)
    return {"count": len(items), "items": items}


@app.post("/clients/import/apply")
def import_apply(payload: dict = Body(...), db: Session = Depends(get_db)):
    files = payload.get("files") or []
    hosts = payload.get("hosts") or []
    domain = payload.get("domain")
    scanned = _scan_prod_files(domain, db)
    selected = []
    if files:
        sel_files = set(files)
        selected = [i for i in scanned if i.get("file") in sel_files or i.get("path") in sel_files]
    elif hosts:
        sel_hosts = set(hosts)
        selected = [i for i in scanned if i.get("host") in sel_hosts]
    else:
        selected = scanned
    results = []
    for item in selected:
        rec, created = _upsert_item(item, db)
        results.append({
            "id": rec.id,
            "host": item.get("host"),
            "file": item.get("file"),
            "created": created,
        })
    return {"count": len(results), "items": results}


@app.post("/clients/import")
def import_clients(domain: Optional[str] = None, db: Session = Depends(get_db)):
    scanned = _scan_prod_files(domain, db)
    results = []
    for item in scanned:
        rec, created = _upsert_item(item, db)
        results.append({
            "id": rec.id,
            "host": item.get("host"),
            "domain": item.get("domain"),
            "subdomain": item.get("subdomain"),
            "group_name": rec.group_name,
            "certificate_arn": rec.certificate_arn,
            "cert_status": rec.cert_status,
            "ingress_path": rec.ingress_path,
            "created": created,
            "file": item.get("file"),
        })
    return {"count": len(results), "items": results}


@app.get("/k8s/snapshot")
def get_snapshot():
    return {
        "namespaces": list(_k8s_snapshot_data.keys()),
        "counts": {ns: len(hs) for ns, hs in _k8s_snapshot_data.items()},
        "ts": _k8s_snapshot_ts,
    }


@app.post("/k8s/snapshot/refresh")
def refresh_snapshot(db: Session = Depends(get_db)):
    namespaces = sorted({r.namespace or "prod" for r in db.query(ClientModel).all()})
    data = get_k8s_snapshot(namespaces, force=True)
    return {
        "namespaces": list(data.keys()),
        "counts": {ns: len(hs) for ns, hs in data.items()},
        "ts": _k8s_snapshot_ts,
    }


@app.get("/clients/health")
async def clients_health(
    domain: Optional[str] = None,
    include_http: bool = Query(False),
    include_dns: bool = Query(False),
    check_deployed: bool = Query(False),
    db: Session = Depends(get_db),
):
    """
    Отримати стан клієнтів.
    
    Параметри:
    - domain: Фільтр за доменом
    - include_http: Виконати HTTP перевірку доступності (тільки для ручного запуску)
    - include_dns: Виконати перевірку DNS записів клієнтів на правильність націлювання на ALB
    - check_deployed: Якщо True і include_http=True, перевіряти тільки задеплоєні клієнти
                     Якщо False і include_http=True, перевіряти всі клієнти
    
    За замовчуванням перевірка кластера K8s, HTTP та DNS НЕ виконується.
    Статус deployed визначається з поля applied_at в базі даних.
    """
    recs = db.query(ClientModel).order_by(ClientModel.id.desc()).all()

    rows: List[Dict] = []
    seen = set()
    for r in recs:
        key = (r.domain or "", r.subdomain or "", r.namespace or "prod")
        if key in seen:
            continue
        host = f"{r.subdomain}.{r.domain}" if r.domain and r.subdomain else (r.domain or r.subdomain)
        if domain and host and (not host.endswith(domain)):
            continue
        rows.append({"rec": r, "host": host})
        seen.add(key)

    out: List[Dict] = []
    to_probe: List[str] = []
    
    for item in rows:
        r: ClientModel = item["rec"]
        host: Optional[str] = item["host"]
        incomplete = not (r.domain and r.subdomain)

        # Статус deployed визначається тільки з бази (applied_at)
        applied = bool(r.applied_at) and host and not incomplete

        status = "not_applied"
        http_status = None
        scheme = None
        error = None
        
        # HTTP перевірка тільки при явному запиті
        if include_http and host:
            # Якщо check_deployed=True - перевіряємо тільки deployed клієнтів
            # Якщо check_deployed=False - перевіряємо всі
            if (check_deployed and applied) or not check_deployed:
                to_probe.append(host)

        # Перевіряємо статус ALB групи
        alb_status = "unknown"
        if r.group_name:
            try:
                alb_dns = get_alb_dns_name(r.group_name)
                alb_status = "ready" if alb_dns and not alb_dns.startswith("<<") else "missing"
            except Exception:
                alb_status = "error"
        
        # Перевіряємо статус DNS записів для сертифіката
        dns_records_status = "unknown"
        if r.certificate_arn and r.cert_status:
            if r.cert_status == "ISSUED":
                dns_records_status = "validated"
            elif r.cert_status == "PENDING_VALIDATION":
                if r.dns_name and r.dns_value and r.dns_name != "Pending...":
                    dns_records_status = "ready"  # DNS записи готові для додавання
                else:
                    dns_records_status = "pending"  # DNS записи ще не готові
            elif r.cert_status in ["FAILED", "EXPIRED", "INACTIVE"]:
                dns_records_status = "failed"
            else:
                dns_records_status = "unknown"

        # DNS перевірка - завантажуємо з бази, оновлюємо тільки при явному запиті
        dns_check_status = r.dns_check_status or "not_checked"
        dns_check_details = None
        
        # Завантажуємо деталі з бази
        if r.dns_check_status and r.dns_check_status != "not_checked":
            import json
            dns_check_details = {
                "resolved_to": r.dns_check_resolved_to,
                "resolved_ips": json.loads(r.dns_check_resolved_ips) if r.dns_check_resolved_ips else [],
                "error": r.dns_check_error,
                "expected_alb": get_alb_dns_name(r.group_name) if r.group_name else None,
                "last_checked": r.dns_check_last_checked.isoformat() if r.dns_check_last_checked else None
            }
        
        # Оновлюємо DNS перевірку тільки при явному запиті (для всіх клієнтів з host і group_name)
        if include_dns and host and r.group_name:
            try:
                expected_alb_dns = get_alb_dns_name(r.group_name)
                if expected_alb_dns and not expected_alb_dns.startswith("<<"):
                    dns_result = check_dns_record(host, expected_alb_dns)
                    dns_check_status = dns_result.get("status", "unknown")
                    
                    # Зберігаємо результат в базу
                    import json
                    from datetime import datetime
                    r.dns_check_status = dns_check_status
                    r.dns_check_resolved_to = dns_result.get("resolved_to")
                    r.dns_check_resolved_ips = json.dumps(dns_result.get("resolved_ips", []))
                    r.dns_check_error = dns_result.get("error")
                    r.dns_check_last_checked = datetime.utcnow()
                    db.commit()
                    
                    dns_check_details = {
                        "resolved_to": dns_result.get("resolved_to"),
                        "resolved_ips": dns_result.get("resolved_ips"),
                        "error": dns_result.get("error"),
                        "expected_alb": expected_alb_dns,
                        "last_checked": r.dns_check_last_checked.isoformat()
                    }
            except Exception as e:
                dns_check_status = "error"
                dns_check_details = {"error": str(e)[:200]}
                # Зберігаємо помилку в базу
                from datetime import datetime
                r.dns_check_status = "error"
                r.dns_check_error = str(e)[:200]
                r.dns_check_last_checked = datetime.utcnow()
                db.commit()

        out.append({
            "id": r.id,
            "host": host,
            "domain": r.domain,
            "subdomain": r.subdomain,
            "incomplete": incomplete,
            "applied": bool(applied),
            "status": status,
            "http_status": http_status,
            "scheme": scheme,
            "error": error,
            "group_name": r.group_name,
            "certificate_arn": r.certificate_arn,
            "cert_status": r.cert_status,
            "ingress_path": r.ingress_path,
            "can_deploy": (not bool(applied)) and (r.cert_status == "ISSUED") and (not incomplete),
            # Нові статуси
            "alb_status": alb_status,
            "dns_records_status": dns_records_status,
            "dns_name": r.dns_name,
            "dns_value": r.dns_value,
            # DNS перевірка
            "dns_check_status": dns_check_status,
            "dns_check_details": dns_check_details
        })

    # HTTP перевірка виконується тільки при явному запиті (include_http=True)
    if include_http and to_probe:
        # Зменшуємо concurrency для слабших систем
        concurrency_level = 2  # макс 2 одночасно
        probed = await probe_many_hosts(list(set(to_probe)), concurrency=concurrency_level)
        by_host = {row["host"]: row for row in out if row.get("host")}
        for h, data in probed.items():
            row = by_host.get(h)
            if row:
                row["status"] = data.get("status")
                row["http_status"] = data.get("http_status")
                row["scheme"] = data.get("scheme")
                row["error"] = data.get("error")

    return out


# ALB group helpers

_k8s_loaded = False


def ensure_k8s_config():
    global _k8s_loaded
    if _k8s_loaded:
        return
    try:
        if os.getenv("KUBECONFIG"):
            k8s_config.load_kube_config(config_file=os.getenv("KUBECONFIG"))
        else:
            k8s_config.load_kube_config()
        _k8s_loaded = True
    except Exception:
        # K8s might be unavailable locally; fallback will be used
        _k8s_loaded = False


# --------- Lightweight TTL caches for performance ---------
class TTLCache:
    def __init__(self, ttl_sec: int):
        self.ttl = ttl_sec
        self.store: Dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        v = self.store.get(key)
        if not v:
            return None
        ts, data = v
        if time.time() - ts > self.ttl:
            self.store.pop(key, None)
            return None
        return data

    def set(self, key: str, data: object):
        self.store[key] = (time.time(), data)


# Cache of hosts present in cluster per namespace (snapshot-style)
_k8s_hosts_cache = TTLCache(ttl_sec=20)
# Cache of HTTP probe results per host
_http_probe_cache = TTLCache(ttl_sec=30)
# Cache of DNS check results per host (30 min TTL)
_dns_check_cache_ttl = TTLCache(ttl_sec=1800)

# One-shot snapshot (persist for process lifetime until manual refresh)
_k8s_snapshot_data: Dict[str, set] = {}
_k8s_snapshot_ts: Optional[float] = None


def _build_k8s_snapshot(namespaces: List[str]) -> Dict[str, set]:
    ensure_k8s_config()
    result: Dict[str, set] = {}
    if not _k8s_loaded:
        for ns in namespaces:
            result[ns] = set()
        return result
    api = k8s_client.NetworkingV1Api()
    for ns in namespaces:
        try:
            ings = api.list_namespaced_ingress(namespace=ns).items
            hosts = set()
            for ing in ings:
                rules = getattr(ing.spec, 'rules', []) or []
                for r in rules:
                    h = getattr(r, 'host', None)
                    if h:
                        hosts.add(h)
            result[ns] = hosts
        except Exception:
            result[ns] = set()
    return result


def get_k8s_snapshot(namespaces: List[str], force: bool = False) -> Dict[str, set]:
    global _k8s_snapshot_data, _k8s_snapshot_ts
    if not _k8s_snapshot_data or force:
        _k8s_snapshot_data = _build_k8s_snapshot(namespaces)
        _k8s_snapshot_ts = time.time()
    # Повертаємо тільки ті namespace, що запитали; не дозавантажуємо нові автоматично
    return {ns: _k8s_snapshot_data.get(ns, set()) for ns in namespaces}


def list_hosts_by_namespace(namespaces: List[str]) -> Dict[str, set]:
    """Backwards-compatible обгортка: використовує фіксований snapshot без додаткових k8s-запитів."""
    return get_k8s_snapshot(namespaces, force=False)


async def _probe_host(client: httpx.AsyncClient, host: str) -> Dict:
    cached = _http_probe_cache.get(host)
    if cached is not None:
        return cached
    last_error = None
    for scheme in ("https", "http"):
        try:
            # Оптимізований timeout для слабших систем
            timeout_config = httpx.Timeout(connect=2.0, read=3.0, write=2.0, pool=5.0)
            r = await client.head(f"{scheme}://{host}", timeout=timeout_config, follow_redirects=True)
            status = "up" if 200 <= r.status_code < 400 else "down"
            data = {"status": status, "http_status": r.status_code, "scheme": scheme, "error": None}
            _http_probe_cache.set(host, data)
            return data
        except Exception as e:
            last_error = str(e)[:200]
            continue
    data = {"status": "down", "http_status": None, "scheme": None, "error": last_error}
    _http_probe_cache.set(host, data)
    return data


async def probe_many_hosts(hosts: List[str], concurrency: int = 2) -> Dict[str, Dict]:
    if not hosts:
        return {}
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as client:
        async def worker(h):
            async with sem:
                return h, await _probe_host(client, h)
        results = await asyncio.gather(*[worker(h) for h in hosts])
    return {h: meta for h, meta in results}


async def check_dns_record_async(host: str, expected_alb_dns: str) -> Dict[str, any]:
    """
    Async версія DNS перевірки з використанням asyncio.to_thread для безпеки.
    Перевіряє CNAME та A записи використовуючи subprocess dig команду.
    
    Args:
        host: доменне ім'я клієнта (наприклад patient.example.com)
        expected_alb_dns: очікуване ALB DNS ім'я
    
    Returns:
        Dict з ключами:
        - status: 'correct' | 'incorrect' | 'missing' | 'error'
        - resolved_to: CNAME target (якщо є)
        - resolved_ips: список IP адрес
        - error: опис помилки
    """
    # Перевіряємо кеш
    cache_key = f"{host}:{expected_alb_dns}"
    cached = _dns_check_cache_ttl.get(cache_key)
    if cached is not None:
        return cached
    
    result = {
        "status": "unknown",
        "resolved_to": None,
        "resolved_ips": [],
        "error": None
    }
    
    try:
        # Використовуємо dig для CNAME перевірки (не викликає fork проблем)
        import subprocess
        
        # Перевіряємо CNAME
        try:
            proc = await asyncio.create_subprocess_exec(
                'dig', '+short', 'CNAME', host,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode == 0 and stdout:
                cname = stdout.decode().strip().rstrip('.')
                if cname and not cname.startswith(';'):
                    result["resolved_to"] = cname
                    
                    # Порівнюємо з очікуваним ALB (ігноруючи регістр)
                    if cname.lower() == expected_alb_dns.lower():
                        result["status"] = "correct"
                        _dns_check_cache_ttl.set(cache_key, result)
                        return result
                    else:
                        result["status"] = "incorrect"
                        result["error"] = f"CNAME points to {cname}, expected {expected_alb_dns}"
                        _dns_check_cache_ttl.set(cache_key, result)
                        return result
        except Exception as e:
            # Якщо dig не працює, пробуємо socket
            pass
        
        # Якщо CNAME немає, перевіряємо A записи через socket (в thread pool)
        import socket
        loop = asyncio.get_event_loop()
        
        try:
            host_ips = await loop.run_in_executor(None, lambda: socket.gethostbyname_ex(host)[2])
            result["resolved_ips"] = host_ips
            
            # Розв'язуємо ALB DNS
            try:
                alb_ips = await loop.run_in_executor(None, lambda: socket.gethostbyname_ex(expected_alb_dns)[2])
                
                if set(host_ips) & set(alb_ips):
                    result["status"] = "correct"
                else:
                    result["status"] = "incorrect"
                    result["error"] = f"Host IPs {host_ips} don't match ALB IPs {alb_ips}"
            except socket.gaierror:
                result["status"] = "error"
                result["error"] = "Cannot resolve ALB DNS"
        except socket.gaierror as e:
            result["status"] = "missing"
            result["error"] = f"DNS lookup failed: {str(e)}"
    
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
    
    # Кешуємо результат
    _dns_check_cache_ttl.set(cache_key, result)
    return result


def check_dns_record(host: str, expected_alb_dns: str) -> Dict[str, any]:
    """
    Sync wrapper для async DNS перевірки.
    Використовується в sync контексті.
    """
    # Перевіряємо кеш
    cache_key = f"{host}:{expected_alb_dns}"
    cached = _dns_check_cache_ttl.get(cache_key)
    if cached is not None:
        return cached
    
    # Якщо є поточний event loop, використовуємо його
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # В async контексті - викликаємо напряму async функцію
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, check_dns_record_async(host, expected_alb_dns))
                return future.result(timeout=10)
        else:
            return asyncio.run(check_dns_record_async(host, expected_alb_dns))
    except Exception:
        # Fallback до простої sync версії
        return _check_dns_simple(host, expected_alb_dns)


def _check_dns_simple(host: str, expected_alb_dns: str) -> Dict[str, any]:
    """Проста sync версія без CNAME перевірки (fallback)"""
    result = {
        "status": "unknown",
        "resolved_to": None,
        "resolved_ips": [],
        "error": None
    }
    
    try:
        import socket
        host_ips = socket.gethostbyname_ex(host)[2]
        result["resolved_ips"] = host_ips
        
        try:
            alb_ips = socket.gethostbyname_ex(expected_alb_dns)[2]
            if set(host_ips) & set(alb_ips):
                result["status"] = "correct"
            else:
                result["status"] = "incorrect"
        except socket.gaierror:
            result["status"] = "error"
            result["error"] = "Cannot resolve ALB DNS"
    except socket.gaierror as e:
        result["status"] = "missing"
        result["error"] = str(e)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
    
    return result


def ingress_exists_for_host(host: str, namespace: str = "prod") -> Optional[bool]:
    """Returns True if an Ingress with this host exists in the cluster, False if checked and not found, None if k8s unavailable."""
    ensure_k8s_config()
    if not _k8s_loaded:
        return None
    api = k8s_client.NetworkingV1Api()
    try:
        ings = api.list_namespaced_ingress(namespace=namespace).items
    except Exception:
        return None
    for ing in ings:
        rules = (ing.spec.rules or [])
        for r in rules:
            if getattr(r, 'host', None) == host:
                return True
    return False


def count_ingresses_in_group_k8s(group: str) -> Optional[int]:
    ensure_k8s_config()
    if not _k8s_loaded:
        return None
    api = k8s_client.NetworkingV1Api()
    try:
        ings = api.list_ingress_for_all_namespaces().items
    except Exception:
        return None
    cnt = 0
    for ing in ings:
        ann = (ing.metadata.annotations or {})
        if ann.get("alb.ingress.kubernetes.io/group.name") == group:
            # Count only those with a cert annotation too (safety)
            if ann.get("alb.ingress.kubernetes.io/certificate-arn"):
                cnt += 1
    return cnt


def count_ingresses_in_group_files(group: str) -> int:
    if not PATH_K8S_PROD_DIR or not os.path.isdir(PATH_K8S_PROD_DIR):
        return 0
    cnt = 0
    for name in os.listdir(PATH_K8S_PROD_DIR):
        if not name.endswith(".yaml") and not name.endswith(".yml"):
            continue
        try:
            with open(os.path.join(PATH_K8S_PROD_DIR, name)) as f:
                data = yaml.safe_load(f)
            ann = ((data or {}).get("metadata") or {}).get("annotations") or {}
            if ann.get("alb.ingress.kubernetes.io/group.name") == group and ann.get("alb.ingress.kubernetes.io/certificate-arn"):
                cnt += 1
        except Exception:
            continue
    return cnt


def choose_group_name(base_group: str) -> str:
    """Обирає найкращу ALB групу, приоритизуючи ті, що мають конфігурацію DNS"""
    # Спочатку пробуємо сконфігуровані групи
    available_groups = list(ALB_GROUP_MAPPINGS.keys())
    if available_groups:
        for group in available_groups:
            cnt = count_ingresses_in_group_k8s(group)
            if cnt is None:
                cnt = count_ingresses_in_group_files(group)
            logger.info(f"Group {group} has {cnt} certificates (limit: {MAX_CERTS_PER_GROUP})")
            if cnt < MAX_CERTS_PER_GROUP:
                return group
    
    # Коли всі сконфігуровані групи повні, створюємо нову
    group = base_group
    for i in range(10):
        cnt = count_ingresses_in_group_k8s(group)
        if cnt is None:
            cnt = count_ingresses_in_group_files(group)
        logger.info(f"Checking group {group}: {cnt} certificates (limit: {MAX_CERTS_PER_GROUP})")
        if cnt < MAX_CERTS_PER_GROUP:
            return group
        group = next_group_name(group)
    
    logger.warning(f"All groups are full, using {group} as fallback")
    return group  # fallback: return last tried


def next_group_name(current: str) -> str:
    m = re.match(r"^(.*?)(\d+)$", current)
    if not m:
        return current + "2"
    prefix, num = m.group(1), int(m.group(2))
    return f"{prefix}{num+1}"


def get_alb_dns_name_from_k8s(group_name: str) -> Optional[str]:
    """Отримати ALB DNS ім'я з Kubernetes Ingress анотації status"""
    ensure_k8s_config()
    if not _k8s_loaded:
        return None
    
    api = k8s_client.NetworkingV1Api()
    try:
        ings = api.list_ingress_for_all_namespaces().items
        for ing in ings:
            ann = (ing.metadata.annotations or {})
            if ann.get("alb.ingress.kubernetes.io/group.name") == group_name:
                # Перевіряємо status для отримання ALB DNS імені
                if hasattr(ing.status, 'load_balancer') and ing.status.load_balancer:
                    if hasattr(ing.status.load_balancer, 'ingress') and ing.status.load_balancer.ingress:
                        for lb_ing in ing.status.load_balancer.ingress:
                            if hasattr(lb_ing, 'hostname') and lb_ing.hostname:
                                return lb_ing.hostname
        return None
    except Exception as e:
        print(f"Error getting ALB DNS name from K8s: {e}")
        return None


def get_alb_dns_name_from_aws(group_name: str) -> Optional[str]:
    """Отримати ALB DNS ім'я з AWS ELB API"""
    try:
        import boto3
        elb = boto3.client("elbv2", region_name=AWS_REGION)
        
        # Отримати всі ALB
        paginator = elb.get_paginator('describe_load_balancers')
        for page in paginator.paginate():
            for lb in page['LoadBalancers']:
                if lb['Type'] == 'application':  # Тільки Application Load Balancers
                    # Перевіряємо теги, щоб знайти потрібний ALB
                    try:
                        tags_resp = elb.describe_tags(ResourceArns=[lb['LoadBalancerArn']])
                        for tag_desc in tags_resp['TagDescriptions']:
                            for tag in tag_desc['Tags']:
                                # Пошук за ingress.k8s.aws/cluster або ingress.k8s.aws/stack
                                if (tag['Key'] == 'ingress.k8s.aws/stack' and group_name in tag['Value']) or \
                                   (tag['Key'] == 'kubernetes.io/ingress-name' and group_name in tag['Value']):
                                    return lb['DNSName']
                    except Exception:
                        continue
        return None
    except Exception as e:
        print(f"Error getting ALB DNS name from AWS: {e}")
        return None


def get_alb_dns_name(group_name: Optional[str] = None) -> str:
    """Отримати ALB DNS ім'я з мапінгу або автоматично"""
    target_group = group_name or ALB_GROUP_NAME_DEFAULT
    
    # 1. Пріоритет: сконфігурований мапінг груп
    if target_group in ALB_GROUP_MAPPINGS:
        logger.debug(f"Using configured DNS name for group {target_group}")
        return ALB_GROUP_MAPPINGS[target_group]
    
    # 2. Legacy: мануальне значення з env (тільки для базової групи)
    if ALB_PUBLIC_HOSTNAME and target_group == ALB_GROUP_NAME_DEFAULT:
        return ALB_PUBLIC_HOSTNAME
    
    # 3. Перевіряємо cache
    if target_group in _alb_dns_cache:
        cached_value, cached_time = _alb_dns_cache[target_group]
        # Cache на 5 хвилин
        if time.time() - cached_time < 300:
            return cached_value
    
    # 4. Пробуємо отримати з K8s Ingress status
    dns_name = get_alb_dns_name_from_k8s(target_group)
    if dns_name:
        _alb_dns_cache[target_group] = (dns_name, time.time())
        logger.info(f"Auto-detected ALB DNS for {target_group}: {dns_name}")
        return dns_name
    
    # 5. Пробуємо отримати з AWS ELB API
    dns_name = get_alb_dns_name_from_aws(target_group)
    if dns_name:
        _alb_dns_cache[target_group] = (dns_name, time.time())
        logger.info(f"Found ALB DNS from AWS API for {target_group}: {dns_name}")
        return dns_name
    
    # 6. Fallback: повертаємо placeholder
    logger.warning(f"ALB DNS name not found for group {target_group}")
    return f"<< ALB DNS for {target_group} not found - configure ALB_GROUP_MAPPINGS in env >>"


def check_alb_existence(group_name: str) -> bool:
    """Перевірка, чи існує фізичний ALB для цієї групи"""
    # 1. Перевіряємо чи є сконфігурований мапінг
    if group_name in ALB_GROUP_MAPPINGS:
        logger.debug(f"ALB group {group_name} is configured in mappings")
        return True
    
    # 2. Перевіряємо чи є у K8s Ingress status
    dns_from_k8s = get_alb_dns_name_from_k8s(group_name)
    if dns_from_k8s:
        logger.debug(f"ALB for group {group_name} found in K8s: {dns_from_k8s}")
        return True
    
    # 3. Перевіряємо через AWS ELB API
    dns_from_aws = get_alb_dns_name_from_aws(group_name)
    if dns_from_aws:
        logger.debug(f"ALB for group {group_name} found in AWS: {dns_from_aws}")
        return True
    
    logger.info(f"ALB for group {group_name} not found - may need to be created")
    return False


def handle_new_alb_creation(group_name: str) -> dict:
    """Обробка створення нового ALB залежно від стратегії"""
    action_result = {
        "strategy": ALB_CREATION_STRATEGY,
        "group_name": group_name,
        "action_taken": None,
        "success": False,
        "message": None,
        "next_steps": None
    }
    
    logger.info(f"Handling new ALB creation for group {group_name} using strategy {ALB_CREATION_STRATEGY}")
    
    if ALB_CREATION_STRATEGY == "k8s-controller":
        # Основний підхід: AWS Load Balancer Controller створить ALB автоматично
        action_result.update({
            "action_taken": "k8s_controller_delegation",
            "success": True,
            "message": f"ALB for group '{group_name}' will be created automatically by AWS Load Balancer Controller when first Ingress is deployed.",
            "next_steps": "Deploy the first client in this group, and the ALB will be created automatically."
        })
        
    elif ALB_CREATION_STRATEGY == "manual":
        # Мануальне створення
        terraform_config = generate_alb_terraform_config(group_name)
        action_result.update({
            "action_taken": "manual_instructions",
            "success": True,
            "message": f"Manual creation required for ALB group '{group_name}'. Instructions provided.",
            "next_steps": "Use provided Terraform configuration or create ALB manually in AWS Console.",
            "terraform_config": terraform_config,
            "aws_console_instructions": generate_aws_console_instructions(group_name)
        })
        
    elif ALB_CREATION_STRATEGY == "notify-only":
        # Тільки сповіщення
        action_result.update({
            "action_taken": "notification_only",
            "success": True,
            "message": f"New ALB group '{group_name}' detected. No automatic action taken.",
            "next_steps": "Admin notification sent. Manual ALB creation may be required."
        })
        
        # Можна відправити нотифікацію через Slack/email
        send_alb_notification(group_name)
    
    else:
        action_result.update({
            "action_taken": "unknown_strategy",
            "success": False,
            "message": f"Unknown ALB creation strategy: {ALB_CREATION_STRATEGY}",
            "next_steps": "Check ALB_CREATION_STRATEGY configuration."
        })
    
    return action_result


def generate_alb_terraform_config(group_name: str) -> str:
    """Генерація Terraform конфіга для створення ALB"""
    # Поки простий приклад, можна розширити
    return f"""
# Terraform configuration for ALB group: {group_name}
# Generated automatically by Client Onboarding Service

resource "aws_lb" "alb_{group_name.replace('-', '_')}" {{
  name               = "{group_name}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false

  tags = {{
    Name = "{group_name}"
    "ingress.k8s.aws/stack" = "{group_name}"
    "ingress.k8s.aws/cluster" = var.cluster_name
  }}
}}

resource "aws_lb_listener" "alb_{group_name.replace('-', '_')}_http" {{
  load_balancer_arn = aws_lb.alb_{group_name.replace('-', '_')}.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {{
    type = "redirect"

    redirect {{
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }}
  }}
}}

resource "aws_lb_listener" "alb_{group_name.replace('-', '_')}_https" {{
  load_balancer_arn = aws_lb.alb_{group_name.replace('-', '_')}.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
  certificate_arn   = var.default_certificate_arn

  default_action {{
    type = "fixed-response"

    fixed_response {{
      content_type = "text/plain"
      message_body = "Default response from {group_name}"
      status_code  = "200"
    }}
  }}
}}

output "alb_{group_name.replace('-', '_')}_dns_name" {{
  value = aws_lb.alb_{group_name.replace('-', '_')}.dns_name
  description = "DNS name of the {group_name} ALB"
}}
"""


def generate_aws_console_instructions(group_name: str) -> dict:
    """Інструкції для ручного створення ALB через AWS Console"""
    return {
        "title": f"Manual ALB Creation for {group_name}",
        "steps": [
            "Go to AWS Console > EC2 > Load Balancers",
            "Click 'Create Load Balancer' > 'Application Load Balancer'",
            f"Name: {group_name}",
            "Scheme: Internet-facing",
            "IP address type: IPv4",
            "Select VPC and public subnets",
            "Security groups: Allow HTTP (80) and HTTPS (443)",
            "Listeners: HTTP:80 (redirect to HTTPS) and HTTPS:443",
            "Add tags:",
            f"  - Name: {group_name}",
            f"  - ingress.k8s.aws/stack: {group_name}",
            "  - ingress.k8s.aws/cluster: <your-cluster-name>",
            "Review and create",
            f"After creation, add the DNS name to ALB_GROUP_MAPPINGS: {group_name}:<dns-name>"
        ],
        "required_tags": {
            "Name": group_name,
            "ingress.k8s.aws/stack": group_name,
            "ingress.k8s.aws/cluster": "<your-cluster-name>"
        }
    }


def send_alb_notification(group_name: str):
    """Надсилання нотифікації про нову ALB групу"""
    logger.warning(f"New ALB group '{group_name}' detected - admin notification required")
    # Тут можна додати інтеграцію з Slack, email, тощо


@app.post("/clients/{client_id}/check-http")
async def check_client_http(client_id: int, db: Session = Depends(get_db)):
    """Перевірка HTTP для одного клієнта"""
    # Знайти клієнта
    rec = db.query(ClientModel).filter(ClientModel.id == client_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    
    if not rec.domain or not rec.subdomain:
        raise HTTPException(status_code=400, detail="Client is missing domain/subdomain")
    
    host = f"{rec.subdomain}.{rec.domain}"
    
    try:
        # Виконуємо HTTP перевірку
        probed = await probe_many_hosts([host], concurrency=1)
        http_data = probed.get(host, {})
        
        return {
            "client_id": rec.id,
            "host": host,
            "status": http_data.get("status", "unknown"),
            "http_status": http_data.get("http_status"),
            "scheme": http_data.get("scheme"),
            "error": http_data.get("error")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clients/{client_id}/check-dns")
async def check_client_dns(client_id: int, db: Session = Depends(get_db)):
    """Перевірка DNS для одного клієнта"""
    # Знайти клієнта
    rec = db.query(ClientModel).filter(ClientModel.id == client_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    
    if not rec.domain or not rec.subdomain:
        raise HTTPException(status_code=400, detail="Client is missing domain/subdomain")
    
    if not rec.group_name:
        raise HTTPException(status_code=400, detail="Client is missing group_name")
    
    host = f"{rec.subdomain}.{rec.domain}"
    
    try:
        expected_alb_dns = get_alb_dns_name(rec.group_name)
        if not expected_alb_dns or expected_alb_dns.startswith("<<"):
            raise HTTPException(status_code=400, detail="ALB DNS name not available")
        
        # Виконуємо DNS перевірку (async версія)
        dns_result = await check_dns_record_async(host, expected_alb_dns)
        dns_check_status = dns_result.get("status", "unknown")
        
        # Зберігаємо результат в базу
        import json
        from datetime import datetime
        rec.dns_check_status = dns_check_status
        rec.dns_check_resolved_to = dns_result.get("resolved_to")
        rec.dns_check_resolved_ips = json.dumps(dns_result.get("resolved_ips", []))
        rec.dns_check_error = dns_result.get("error")
        rec.dns_check_last_checked = datetime.utcnow()
        db.commit()
        
        return {
            "client_id": rec.id,
            "host": host,
            "dns_check_status": dns_check_status,
            "dns_check_details": {
                "resolved_to": dns_result.get("resolved_to"),
                "resolved_ips": dns_result.get("resolved_ips"),
                "error": dns_result.get("error"),
                "expected_alb": expected_alb_dns,
                "last_checked": rec.dns_check_last_checked.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        # Зберігаємо помилку в базу
        from datetime import datetime
        rec.dns_check_status = "error"
        rec.dns_check_error = str(e)[:200]
        rec.dns_check_last_checked = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clients/{client_id}/deploy")
def deploy_client_ingress(client_id: int, db: Session = Depends(get_db)):
    # Знайти клієнта
    rec = db.query(ClientModel).filter(ClientModel.id == client_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Client not found")
    if not rec.domain or not rec.subdomain:
        raise HTTPException(status_code=400, detail="Client is missing domain/subdomain")
    host = f"{rec.subdomain}.{rec.domain}"

    # Перевірити чи вже застосовано
    applied = ingress_exists_for_host(host, rec.namespace or "prod")
    if applied:
        raise HTTPException(status_code=400, detail="Ingress already exists for this host")

    # Перевірити сертифікат
    if rec.cert_status != "ISSUED":
        raise HTTPException(status_code=400, detail=f"Certificate is not ISSUED (current: {rec.cert_status})")
    if not rec.certificate_arn:
        raise HTTPException(status_code=400, detail="certificate_arn is missing")

    # Забезпечити наявність YAML маніфесту
    if not rec.ingress_path or not os.path.isfile(rec.ingress_path):
        path = write_ingress_file(rec.domain, rec.subdomain, rec.namespace or "prod", rec.certificate_arn, rec.group_name)
        rec.ingress_path = path
        db.commit()
    path = rec.ingress_path

    # Застосувати маніфест
    result = apply_ingress_file(path, rec.namespace or "prod")

    # Git add/commit/push if enabled
    git_info = None
    if GIT_AUTOCOMMIT_INGRESS:
        msg = f"Deployed {host}"
        git_info = _git_commit_and_maybe_push(path, msg)

    # Оновити applied_at
    from datetime import datetime
    rec.applied_at = datetime.utcnow()
    db.commit()

    response = {**result, "client_id": rec.id, "host": host}
    if git_info is not None:
        response["git"] = git_info
    return response


@app.get("/alb/next-group")
def alb_next_group(current: Optional[str] = None):
    curr = current or ALB_GROUP_NAME_DEFAULT
    nxt = choose_group_name(curr)
    # Якщо базова група переповнена, nxt буде наступною; якщо ні — залишиться поточною
    if nxt == curr:
        # Для UI підказати наступну теж
        return {"current": curr, "next": next_group_name(curr), "usable": curr}
    else:
        return {"current": curr, "next": next_group_name(nxt), "usable": nxt}


@app.get("/alb/dns-name")
def get_alb_dns_endpoint(group_name: Optional[str] = None):
    """Отримати ALB DNS ім'я для тестування"""
    target_group = group_name or ALB_GROUP_NAME_DEFAULT
    dns_name = get_alb_dns_name(target_group)
    
    return {
        "group_name": target_group,
        "alb_dns_name": dns_name,
        "source": "manual" if ALB_PUBLIC_HOSTNAME else "auto-detected",
        "cached": target_group in _alb_dns_cache
    }


@app.get("/alb/group-recommendations")
def get_alb_group_recommendations():
    """Повертає рекомендації щодо найкращої ALB групи для нового клієнта"""
    recommended_group = choose_group_name(ALB_GROUP_NAME_DEFAULT)
    recommended_dns = get_alb_dns_name(recommended_group)
    
    # Перевірка, чи потрібно створити новий ALB
    alb_exists = check_alb_existence(recommended_group)
    need_new_alb = not alb_exists
    
    # Якщо потрібен новий ALB, запускаємо процес створення
    new_alb_action = None
    if need_new_alb:
        new_alb_action = handle_new_alb_creation(recommended_group)
    
    # Статистика всіх доступних груп
    group_stats = []
    
    # Сконфігуровані групи
    for group_name in ALB_GROUP_MAPPINGS.keys():
        cert_count = count_ingresses_in_group_k8s(group_name)
        if cert_count is None:
            cert_count = count_ingresses_in_group_files(group_name)
        
        available_slots = MAX_CERTS_PER_GROUP - cert_count
        status = "available" if available_slots > 0 else "full"
        
        group_stats.append({
            "group_name": group_name,
            "certificate_count": cert_count,
            "max_certificates": MAX_CERTS_PER_GROUP,
            "available_slots": available_slots,
            "status": status,
            "dns_hostname": ALB_GROUP_MAPPINGS.get(group_name),
            "configured": True
        })
    
    # Перевіряємо також базову групу якщо вона не в мапінгу
    if ALB_GROUP_NAME_DEFAULT not in ALB_GROUP_MAPPINGS:
        cert_count = count_ingresses_in_group_k8s(ALB_GROUP_NAME_DEFAULT)
        if cert_count is None:
            cert_count = count_ingresses_in_group_files(ALB_GROUP_NAME_DEFAULT)
        
        available_slots = MAX_CERTS_PER_GROUP - cert_count
        status = "available" if available_slots > 0 else "full"
        
        group_stats.append({
            "group_name": ALB_GROUP_NAME_DEFAULT,
            "certificate_count": cert_count,
            "max_certificates": MAX_CERTS_PER_GROUP,
            "available_slots": available_slots,
            "status": status,
            "dns_hostname": get_alb_dns_name(ALB_GROUP_NAME_DEFAULT),
            "configured": False
        })
    
    response_data = {
        "recommended_group": recommended_group,
        "recommended_dns_hostname": recommended_dns,
        "group_statistics": group_stats,
        "total_configured_groups": len(ALB_GROUP_MAPPINGS),
        "certificate_limit_per_group": MAX_CERTS_PER_GROUP,
        "alb_creation_strategy": ALB_CREATION_STRATEGY
    }
    
    # Додаємо інформацію про створення нового ALB якщо потрібно
    if need_new_alb and new_alb_action:
        response_data["new_alb_required"] = True
        response_data["alb_creation_info"] = new_alb_action
    else:
        response_data["new_alb_required"] = False
    
    return response_data


@app.get("/alb/creation-instructions/{group_name}")
def get_alb_creation_instructions(group_name: str):
    """Отримати інструкції для створення ALB групи"""
    # Перевірка чи ALB вже існує
    alb_exists = check_alb_existence(group_name)
    
    if alb_exists:
        return {
            "group_name": group_name,
            "alb_exists": True,
            "message": f"ALB for group '{group_name}' already exists.",
            "dns_hostname": get_alb_dns_name(group_name)
        }
    
    # Генерація інструкцій
    creation_info = handle_new_alb_creation(group_name)
    
    return {
        "group_name": group_name,
        "alb_exists": False,
        "creation_strategy": ALB_CREATION_STRATEGY,
        "instructions": creation_info
    }


@app.post("/alb/notify-created")
def notify_alb_created(group_name: str = Body(...), dns_hostname: str = Body(...)):
    """Повідомлення про створення нового ALB"""
    logger.info(f"Received notification: ALB created for group {group_name} with DNS {dns_hostname}")
    
    # Оновлюємо кеш
    _alb_dns_cache[group_name] = (dns_hostname, time.time())
    
    # Можна додати автоматичне оновлення ALB_GROUP_MAPPINGS
    # або збереження в базі даних
    
    return {
        "success": True,
        "message": f"ALB creation notification processed for {group_name}",
        "group_name": group_name,
        "dns_hostname": dns_hostname
    }


@app.get("/alb/current-stats")
def alb_current_stats():
    """Повертає статистику поточного ALB з .env файлу (legacy ендпоінт)"""
    current_group = ALB_GROUP_NAME_DEFAULT
    
    # Підраховуємо сертифікати в поточній групі
    cert_count = count_ingresses_in_group_k8s(current_group)
    if cert_count is None:
        cert_count = count_ingresses_in_group_files(current_group)
    
    # Визначаємо статус на основі кількості сертифікатів
    if cert_count <= 20:
        status = "good"  # зелений
    elif cert_count <= 23:
        status = "warning"  # жовтий
    else:
        status = "critical"  # червоний (24-25)
    
    return {
        "group_name": current_group,
        "certificate_count": cert_count,
        "max_certificates": 25,  # AWS ALB ліміт
        "status": status,
        "remaining": 25 - cert_count
    }


@app.post("/cert/reissue")
def reissue_cert(req: ReissueReq):
    try:
        resp = acm.request_certificate(
            DomainName=f"*.{req.domain}",
            ValidationMethod="DNS",
            Options={"CertificateTransparencyLoggingPreference": "ENABLED"},
            KeyAlgorithm="RSA_2048",
        )
        arn = resp["CertificateArn"]
        desc = acm.describe_certificate(CertificateArn=arn)
        
        # Check for DomainValidationOptions and ResourceRecord
        domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
        if not domain_validation_options:
            return {
                "certificate_arn": arn,
                "dns_name": "Pending... / Очікування...",
                "dns_value": "DNS records are not ready yet. Please wait a few minutes and check the certificate. / DNS записи ще не готові. Зачекайте кілька хвилин і перевірте сертифікат.",
                "status": "PENDING_VALIDATION"
            }
        
        # Check for ResourceRecord
        resource_record = domain_validation_options[0].get("ResourceRecord")
        if not resource_record:
            return {
                "certificate_arn": arn,
                "dns_name": "Pending... / Очікування...",
                "dns_value": "DNS records are not ready yet. Please wait a few minutes and check the certificate. / DNS записи ще не готові. Зачекайте кілька хвилин і перевірте сертифікат.",
                "status": "PENDING_VALIDATION"
            }
        
        return {
            "certificate_arn": arn,
            "dns_name": resource_record["Name"],
            "dns_value": resource_record["Value"],
            "status": desc["Certificate"].get("Status", "UNKNOWN")
        }
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.post("/cert/reissue-full")
def reissue_cert_full(req: ReissueFullReq, request: Request, db: Session = Depends(get_db)):
    """Повнофункціональний reissue: створити новий сертифікат, оновити інгрес і БД"""
    
    # Get user language
    lang = get_user_language(request)
    
    # 1. Find clients with this domain
    clients = db.query(ClientModel).filter(ClientModel.domain == req.domain).all()
    if not clients:
        error_msg = translate(
            f"No clients found with domain {req.domain}",
            f"Клієнтів з доменом {req.domain} не знайдено",
            lang
        )
        raise HTTPException(status_code=404, detail=error_msg)
    
    # Беремо першого клієнта як основний (для wildcard сертифіката)
    main_client = clients[0]
    old_certificate_arn = main_client.certificate_arn
    
    try:
        # 2. Створити новий сертифікат
        resp = acm.request_certificate(
            DomainName=f"*.{req.domain}",
            ValidationMethod="DNS",
            Options={"CertificateTransparencyLoggingPreference": "ENABLED"},
            KeyAlgorithm="RSA_2048",
        )
        new_arn = resp["CertificateArn"]
        desc = acm.describe_certificate(CertificateArn=new_arn)
        
        # Check for DomainValidationOptions and ResourceRecord
        domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
        dns_name = translate("Pending...", "Очікування...", lang)
        dns_value = translate(
            "DNS records are not ready yet...",
            "DNS записи ще не готові...",
            lang
        )
        
        if domain_validation_options:
            resource_record = domain_validation_options[0].get("ResourceRecord")
            if resource_record:
                dns_name = resource_record["Name"]
                dns_value = resource_record["Value"]
        
        # 3. Оновити базу даних (якщо потрібно)
        updated_clients = []
        if req.update_database:
            for client in clients:
                client.certificate_arn = new_arn
                client.cert_status = "PENDING_VALIDATION"
                client.dns_name = dns_name
                client.dns_value = dns_value
                updated_clients.append({"id": client.id, "host": f"{client.subdomain}.{client.domain}"})
            db.commit()
        
        # 4. Оновити файли інгресу (якщо потрібно)
        updated_files = []
        if req.update_ingress:
            for client in clients:
                if client.ingress_path and os.path.exists(client.ingress_path):
                    # Читаємо і оновлюємо файл
                    with open(client.ingress_path, 'r') as f:
                        content = f.read()
                    
                    # Замінюємо старий ARN на новий
                    if old_certificate_arn and old_certificate_arn in content:
                        updated_content = content.replace(old_certificate_arn, new_arn)
                        with open(client.ingress_path, 'w') as f:
                            f.write(updated_content)
                        updated_files.append(client.ingress_path)
        
        # 5. Підготувати відповідь
        result = {
            "success": True,
            "old_certificate_arn": old_certificate_arn,
            "new_certificate_arn": new_arn,
            "dns_name": dns_name,
            "dns_value": dns_value,
            "status": desc["Certificate"].get("Status", "UNKNOWN"),
            "clients_updated": len(updated_clients) if req.update_database else 0,
            "files_updated": len(updated_files) if req.update_ingress else 0,
            "updated_clients": updated_clients,
            "updated_files": updated_files,
            "next_steps": [
                translate(
                    "Add DNS record for validation",
                    "Додайте DNS запис для валідації",
                    lang
                ),
                translate(
                    "Wait for certificate validation",
                    "Очікайте валідацію сертифіката",
                    lang
                ),
                translate(
                    "Reapply ingress manifests",
                    "Перезастосуйте інгрес маніфести",
                    lang
                ) if req.update_ingress else translate(
                    "Update ingress manifests manually",
                    "Оновіть інгрес маніфести вручну",
                    lang
                ),
            ]
        }
        
        # Delete old certificate immediately if requested
        if req.delete_old_cert and old_certificate_arn:
            try:
                acm.delete_certificate(CertificateArn=old_certificate_arn)
                result["old_certificate_deleted"] = True
                result["message"] = translate(
                    "Old certificate deleted successfully",
                    "Старий сертифікат успішно видалено",
                    lang
                )
                logger.info(f"Deleted old certificate {old_certificate_arn} for domain {req.domain}")
            except ClientError as e:
                # If certificate is in use, schedule for deletion
                if "ResourceInUseException" in str(e) or "CertificateInUse" in str(e):
                    result["warning"] = translate(
                        "Old certificate is in use and cannot be deleted now. Please remove it from resources first.",
                        "Старий сертифікат використовується і не може бути видалений зараз. Спочатку видаліть його з ресурсів.",
                        lang
                    )
                    result["old_certificate_deleted"] = False
                    logger.warning(f"Failed to delete old certificate {old_certificate_arn}: {e}")
                else:
                    result["warning"] = translate(
                        f"Failed to delete old certificate: {str(e)}",
                        f"Помилка при видаленні старого сертифіката: {str(e)}",
                        lang
                    )
                    result["old_certificate_deleted"] = False
                    logger.error(f"Error deleting old certificate {old_certificate_arn}: {e}")
        
        return result
        
    except ClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# ---------- Certificate inventory ----------

@app.get("/cert/inventory")
def cert_inventory(domain: Optional[str] = None):
    # Aggregates certificate ARNs from YAML files and reports ACM status
    arns: Dict[str, Dict[str, str]] = {}
    if PATH_K8S_PROD_DIR and os.path.isdir(PATH_K8S_PROD_DIR):
        for name in os.listdir(PATH_K8S_PROD_DIR):
            if not name.endswith(".yaml") and not name.endswith(".yml"):
                continue
            try:
                with open(os.path.join(PATH_K8S_PROD_DIR, name)) as f:
                    data = yaml.safe_load(f)
                ann = ((data or {}).get("metadata") or {}).get("annotations") or {}
                arn = ann.get("alb.ingress.kubernetes.io/certificate-arn")
                host = ((data or {}).get("spec") or {}).get("rules", [{}])[0].get("host")
                if not arn:
                    continue
                if domain and (not host or not host.endswith(domain)):
                    continue
                arns[arn] = {"host": host or "", "file": name}
            except Exception:
                continue
    # Describe each ARN in ACM
    out = []
    for arn, meta in arns.items():
        try:
            desc = acm.describe_certificate(CertificateArn=arn)
            status = desc["Certificate"]["Status"]
            out.append({"arn": arn, "status": status, **meta})
        except ClientError as e:
            out.append({"arn": arn, "status": "UNKNOWN", **meta, "error": str(e)})
    return out


@app.get("/cert/list")
def cert_list_acm(domain: Optional[str] = None, max_items: int = 100):
    # Lists ACM certificates; filters by domain substring if provided
    paginator = acm.get_paginator('list_certificates')
    certs = []
    for page in paginator.paginate(CertificateStatuses=['ISSUED','PENDING_VALIDATION','INACTIVE','EXPIRED'], PaginationConfig={'MaxItems': max_items}):
        for summary in page.get('CertificateSummaryList', []):
            dname = summary.get('DomainName')
            if domain and (domain not in dname):
                continue
            certs.append(summary)
    return certs


# ---------- GitHub integration ----------

def build_server_block(host: str, affiliate: str) -> str:
    return f"""
server {{
    listen       80;
    server_name  {host};
    gzip on;
    gzip_min_length 1024;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/javascript application/json image/svg+xml;
    gzip_vary on;
    location / {{
        if ($has_params = '0') {{
            set $additional_param "affiliate=aff::{affiliate}";
            return 301 https://$host$request_uri?$additional_param;
        }}
        root   /usr/share/nginx/build;
        index  index.html index.htm;
        try_files $uri $uri/ /index.html =404;
        expires $expires;
        add_header Cache-Control "public, immutable";
        add_header Pragma "public";
    }}
    location = /index.html {{
        root /usr/share/nginx/build;
        expires 1d;
        add_header Cache-Control "public, max-age=86400, must-revalidate";
        add_header Pragma "public";
    }}
    error_page   500 502 503 504  /50x.html;
    location = /50x.html {{
        root   /usr/share/nginx/html;
    }}
}}
""".strip() + "\n"


def create_frontend_pr(domain: str, subdomain: str, affiliate: str, auto_merge: bool = False) -> int:
    if not gh:
        raise RuntimeError("GitHub client not configured")
    repo = gh.get_repo(f"{GITHUB_OWNER}/{GITHUB_REPO}")

    # 1) Create branch from default branch
    base_ref = repo.get_git_ref(f"heads/{GITHUB_DEFAULT_BRANCH}")
    base_sha = base_ref.object.sha
    branch_name = domain
    new_ref_name = f"refs/heads/{branch_name}"
    # Create ref if not exists
    try:
        repo.create_git_ref(new_ref_name, base_sha)
    except Exception:
        # Already exists
        pass

    # 2) Get nginx/default.conf from base branch
    path = "nginx/default.conf"
    contents = repo.get_contents(path, ref=GITHUB_DEFAULT_BRANCH)
    original = contents.decoded_content.decode("utf-8")

    # 3) Insert new server block right before the first existing "server {" block
    #    (i.e., after any map sections), and avoid duplicates based on server_name.
    host = f"{subdomain}.{domain}"
    block = build_server_block(host, affiliate)

    # Duplicate detection by server_name
    import re as _re
    if _re.search(rf"server_name\s+{_re.escape(host)}\s*;", original):
        updated = original
    else:
        m = _re.search(r"(?m)^\s*server\s*\{", original)
        if m:
            insert_idx = m.start()
            prefix = original[:insert_idx]
            suffix = original[insert_idx:]
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            updated = prefix + block + "\n" + suffix
        else:
            sep = "" if original.endswith("\n") else "\n"
            updated = original + sep + block + "\n"

    # 4) Update file on branch
    repo.update_file(path=path,
                     message=f"adding {host}",
                     content=updated,
                     sha=contents.sha,
                     branch=branch_name)

    # 5) Create PR
    pr = repo.create_pull(title=f"Added {host}", body=f"Automated PR for {host}", head=branch_name, base=GITHUB_DEFAULT_BRANCH)

    # 6) Optionally auto-merge
    if auto_merge:
        try:
            pr.merge(merge_method="merge")
        except Exception:
            pass

    return pr.number
