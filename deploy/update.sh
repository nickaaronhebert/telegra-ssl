#!/bin/bash

# Client Onboarding Service Update Script
# This script pulls latest changes and updates the running service

set -euo pipefail

# Configuration
SERVICE_NAME="client-onboarding"
DEPLOY_DIR="/opt/client-onboarding-service"
SERVICE_URL="http://localhost:8000"
GIT_BRANCH="${GIT_BRANCH:-main}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if service is running
check_service() {
    if ! systemctl is-active --quiet $SERVICE_NAME; then
        error "Service $SERVICE_NAME is not running"
    fi
}

# Get current version/commit
get_current_version() {
    if [[ -d "$DEPLOY_DIR/.git" ]]; then
        cd $DEPLOY_DIR
        CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        echo "Current version: $CURRENT_COMMIT"
    else
        echo "Git repository not found in $DEPLOY_DIR"
    fi
}

# Pull latest changes
update_code() {
    log "Updating code from git repository..."
    
    cd $DEPLOY_DIR
    
    # Stash any local changes
    if git diff-index --quiet HEAD --; then
        log "No local changes to stash"
    else
        warn "Stashing local changes..."
        sudo -u ubuntu git stash
    fi
    
    # Fetch and pull latest changes
    sudo -u ubuntu git fetch origin
    sudo -u ubuntu git checkout $GIT_BRANCH
    sudo -u ubuntu git pull origin $GIT_BRANCH
    
    NEW_COMMIT=$(git rev-parse --short HEAD)
    success "Updated to version: $NEW_COMMIT"
    
    # Check if there were any changes
    if [[ "$CURRENT_COMMIT" == "$NEW_COMMIT" ]]; then
        log "No new changes to deploy"
        return 1
    fi
    
    return 0
}

# Update Docker images
update_images() {
    log "Updating Docker images..."
    
    cd $DEPLOY_DIR
    sudo docker compose pull
    
    success "Docker images updated"
}

# Restart service with zero-downtime
restart_service() {
    log "Restarting service..."
    
    # Create temporary backup
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="/tmp/client-onboarding-backup-$TIMESTAMP.tar.gz"
    sudo tar -czf $BACKUP_FILE -C $DEPLOY_DIR .env docker-compose.yml
    
    # Restart service
    sudo systemctl restart $SERVICE_NAME
    
    # Wait for service to be healthy
    log "Waiting for service to be healthy..."
    for i in {1..30}; do
        if curl -f $SERVICE_URL/health >/dev/null 2>&1; then
            success "Service is healthy after restart"
            # Remove temporary backup
            rm -f $BACKUP_FILE
            return 0
        fi
        if [[ $i -eq 30 ]]; then
            error "Service failed to start after restart"
        fi
        sleep 2
    done
}

# Rollback to previous version
rollback() {
    log "Rolling back to previous version..."
    
    cd $DEPLOY_DIR
    
    # Get previous commit
    PREV_COMMIT=$(sudo -u ubuntu git log --oneline -2 --format="%H" | tail -1)
    
    if [[ -n "$PREV_COMMIT" ]]; then
        sudo -u ubuntu git checkout $PREV_COMMIT
        sudo systemctl restart $SERVICE_NAME
        
        # Wait for health check
        for i in {1..30}; do
            if curl -f $SERVICE_URL/health >/dev/null 2>&1; then
                success "Rollback successful"
                return 0
            fi
            sleep 2
        done
        
        error "Rollback failed - service not healthy"
    else
        error "Cannot find previous commit for rollback"
    fi
}

# Run database migrations (if needed)
run_migrations() {
    log "Running database migrations..."
    
    cd $DEPLOY_DIR
    
    # Check if migration script exists
    if [[ -f "migrate.py" ]]; then
        sudo docker compose exec app python migrate.py
        success "Migrations completed"
    else
        log "No migration script found, skipping..."
    fi
}

# Show deployment status
show_status() {
    log "=== Deployment Status ==="
    
    # Service status
    echo "Service Status:"
    sudo systemctl status $SERVICE_NAME --no-pager -l
    echo ""
    
    # Docker containers
    echo "Docker Containers:"
    sudo docker ps --filter "name=client-onboarding"
    echo ""
    
    # Health check
    echo "Health Check:"
    if curl -f $SERVICE_URL/health 2>/dev/null; then
        echo "✅ Service is healthy"
    else
        echo "❌ Service is not healthy"
    fi
    echo ""
    
    # Version info
    get_current_version
    echo ""
    
    # Recent logs
    echo "Recent Logs:"
    sudo journalctl -u $SERVICE_NAME --no-pager -n 5
}

# Main function
main() {
    log "Starting Client Onboarding Service update..."
    
    # Check permissions
    if [[ $EUID -eq 0 ]]; then
        log "Running as root"
    elif sudo -n true 2>/dev/null; then
        log "Running with sudo privileges"
    else
        error "This script requires root privileges or passwordless sudo"
    fi
    
    case "${1:-update}" in
        "update")
            check_service
            get_current_version
            
            if update_code; then
                update_images
                run_migrations
                restart_service
                show_status
            else
                log "No updates needed"
            fi
            ;;
        "force-update")
            get_current_version
            update_images
            run_migrations
            restart_service
            show_status
            ;;
        "rollback")
            rollback
            ;;
        "status")
            show_status
            ;;
        "migrate")
            run_migrations
            ;;
        *)
            echo "Usage: $0 {update|force-update|rollback|status|migrate}"
            echo ""
            echo "Commands:"
            echo "  update       - Pull latest changes and update if needed"
            echo "  force-update - Force update even without code changes"
            echo "  rollback     - Rollback to previous version"
            echo "  status       - Show current deployment status"
            echo "  migrate      - Run database migrations only"
            exit 1
            ;;
    esac
    
    success "Operation completed successfully"
}

# Run main function
main "$@"