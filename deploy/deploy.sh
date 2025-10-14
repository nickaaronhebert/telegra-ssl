#!/bin/bash

# Client Onboarding Service Deployment Script
# This script deploys the service to a production server

set -euo pipefail

# Configuration
SERVICE_NAME="client-onboarding"
DEPLOY_USER="ubuntu"
DEPLOY_DIR="/opt/client-onboarding-service"
SERVICE_URL="http://localhost:8000"
BACKUP_DIR="/opt/backups/client-onboarding"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check if running as root or with sudo
check_privileges() {
    if [[ $EUID -eq 0 ]]; then
        log "Running as root"
    elif sudo -n true 2>/dev/null; then
        log "Running with sudo privileges"
        SUDO="sudo"
    else
        error "This script requires root privileges or passwordless sudo"
    fi
}

# Install dependencies
install_dependencies() {
    log "Installing system dependencies..."
    
    ${SUDO:-} apt-get update
    ${SUDO:-} apt-get install -y \
        docker.io \
        docker-compose-plugin \
        curl \
        git \
        nginx \
        certbot \
        python3-certbot-nginx
    
    # Add deploy user to docker group
    ${SUDO:-} usermod -aG docker $DEPLOY_USER
    
    # Enable and start services
    ${SUDO:-} systemctl enable docker
    ${SUDO:-} systemctl start docker
    
    success "Dependencies installed"
}

# Create directory structure
setup_directories() {
    log "Setting up directory structure..."
    
    ${SUDO:-} mkdir -p $DEPLOY_DIR
    ${SUDO:-} mkdir -p $BACKUP_DIR
    ${SUDO:-} mkdir -p /var/log/client-onboarding
    ${SUDO:-} mkdir -p /opt/k8s-configs
    
    # Set ownership
    ${SUDO:-} chown -R $DEPLOY_USER:$DEPLOY_USER $DEPLOY_DIR
    ${SUDO:-} chown -R $DEPLOY_USER:$DEPLOY_USER /var/log/client-onboarding
    ${SUDO:-} chown -R $DEPLOY_USER:$DEPLOY_USER /opt/k8s-configs
    
    success "Directory structure created"
}

# Deploy application
deploy_app() {
    log "Deploying application..."
    
    # Copy application files
    ${SUDO:-} cp -r . $DEPLOY_DIR/
    ${SUDO:-} chown -R $DEPLOY_USER:$DEPLOY_USER $DEPLOY_DIR
    
    # Copy environment file
    if [[ -f ".env.production" ]]; then
        ${SUDO:-} cp .env.production $DEPLOY_DIR/.env
        ${SUDO:-} chown $DEPLOY_USER:$DEPLOY_USER $DEPLOY_DIR/.env
        ${SUDO:-} chmod 600 $DEPLOY_DIR/.env
    else
        warn ".env.production file not found. Please create it manually."
    fi
    
    success "Application deployed"
}

# Setup systemd service
setup_systemd() {
    log "Setting up systemd service..."
    
    ${SUDO:-} cp deploy/client-onboarding.service /etc/systemd/system/
    ${SUDO:-} systemctl daemon-reload
    ${SUDO:-} systemctl enable $SERVICE_NAME
    
    success "Systemd service configured"
}

# Setup nginx reverse proxy
setup_nginx() {
    log "Setting up Nginx reverse proxy..."
    
    cat <<EOF | ${SUDO:-} tee /etc/nginx/sites-available/$SERVICE_NAME
server {
    listen 80;
    server_name client-onboarding.yourdomain.com;
    
    location / {
        proxy_pass $SERVICE_URL;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }
    
    location /health {
        access_log off;
        proxy_pass $SERVICE_URL/health;
        proxy_set_header Host \$host;
    }
}
EOF

    ${SUDO:-} ln -sf /etc/nginx/sites-available/$SERVICE_NAME /etc/nginx/sites-enabled/
    ${SUDO:-} nginx -t
    ${SUDO:-} systemctl reload nginx
    
    success "Nginx configured"
}

# Create backup
create_backup() {
    if systemctl is-active --quiet $SERVICE_NAME; then
        log "Creating backup..."
        
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.tar.gz"
        
        ${SUDO:-} tar -czf $BACKUP_FILE -C $DEPLOY_DIR .
        ${SUDO:-} chown $DEPLOY_USER:$DEPLOY_USER $BACKUP_FILE
        
        # Keep only last 5 backups
        ${SUDO:-} find $BACKUP_DIR -name "backup_*.tar.gz" -type f -printf '%T@ %p\n' | \
            sort -n | head -n -5 | cut -d' ' -f2- | xargs -r rm -f
        
        success "Backup created: $BACKUP_FILE"
    fi
}

# Start services
start_services() {
    log "Starting services..."
    
    # Change to deploy directory
    cd $DEPLOY_DIR
    
    # Stop service if running
    if systemctl is-active --quiet $SERVICE_NAME; then
        ${SUDO:-} systemctl stop $SERVICE_NAME
        sleep 5
    fi
    
    # Start service
    ${SUDO:-} systemctl start $SERVICE_NAME
    
    # Wait for health check
    log "Waiting for service to be healthy..."
    for i in {1..30}; do
        if curl -f $SERVICE_URL/health >/dev/null 2>&1; then
            success "Service is healthy"
            break
        fi
        if [[ $i -eq 30 ]]; then
            error "Service failed to start properly"
        fi
        sleep 2
    done
    
    success "Services started"
}

# Show status
show_status() {
    log "Service Status:"
    ${SUDO:-} systemctl status $SERVICE_NAME --no-pager
    
    log "Docker Containers:"
    ${SUDO:-} docker ps --filter "name=client-onboarding"
    
    log "Recent Logs:"
    ${SUDO:-} journalctl -u $SERVICE_NAME --no-pager -n 10
}

# Main deployment function
main() {
    log "Starting deployment of Client Onboarding Service..."
    
    check_privileges
    
    case "${1:-deploy}" in
        "install")
            install_dependencies
            setup_directories
            ;;
        "deploy")
            create_backup
            deploy_app
            setup_systemd
            start_services
            show_status
            ;;
        "nginx")
            setup_nginx
            ;;
        "status")
            show_status
            ;;
        "logs")
            ${SUDO:-} journalctl -u $SERVICE_NAME -f
            ;;
        "stop")
            ${SUDO:-} systemctl stop $SERVICE_NAME
            ;;
        "start")
            ${SUDO:-} systemctl start $SERVICE_NAME
            ;;
        "restart")
            ${SUDO:-} systemctl restart $SERVICE_NAME
            ;;
        *)
            echo "Usage: $0 {install|deploy|nginx|status|logs|start|stop|restart}"
            echo ""
            echo "Commands:"
            echo "  install - Install system dependencies and setup directories"
            echo "  deploy  - Deploy the application and start services"
            echo "  nginx   - Setup Nginx reverse proxy"
            echo "  status  - Show service status"
            echo "  logs    - Show real-time logs"
            echo "  start   - Start the service"
            echo "  stop    - Stop the service"
            echo "  restart - Restart the service"
            exit 1
            ;;
    esac
    
    success "Operation completed successfully"
}

# Run main function
main "$@"