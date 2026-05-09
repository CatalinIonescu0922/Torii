#!/bin/bash
#
# Torii Environment Launcher
# Manages Docker Compose lifecycle for the Torii project
#
# Usage:
#   ./launch -s, --start      Start fresh environment (cleans volumes)
#   ./launch -d, --delete     Stop and remove volumes
#   ./launch -r, --restart    Restart without cleaning
#   ./launch -h, --help       Show this help message
#

set -e

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$COMPOSE_DIR/logs"

log_info() {
    echo "[INFO] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
    exit 1
}

cleanup_volumes() {
    log_info "Stopping containers..."
    docker compose down --volumes 2>/dev/null || true

    if [ -d "$LOGS_DIR" ]; then
        log_info "Removing log volumes at $LOGS_DIR"
        sudo rm -rf "$LOGS_DIR"
    fi
}

create_volumes() {
    log_info "Creating fresh log directories..."
    mkdir -p "$LOGS_DIR/merger"
    mkdir -p "$LOGS_DIR/scheduler"
    chmod 777 "$LOGS_DIR" "$LOGS_DIR/merger" "$LOGS_DIR/scheduler"
}

start_environment() {
    cleanup_volumes
    create_volumes
    log_info "Starting Docker Compose..."
    docker compose up -d
    log_info "Environment started successfully"
}

stop_environment() {
    log_info "Stopping Docker Compose..."
    docker compose down
    log_info "Environment stopped"
}

stop_and_clean() {
    stop_environment
    cleanup_volumes
    log_info "Volumes removed"
}

restart_environment() {
    log_info "Restarting Docker Compose..."
    docker compose restart
    log_info "Environment restarted"
}

show_help() {
    sed -n '2,11p' "$0" | sed 's/^# //'
}

main() {
    case "${1:-}" in
        -s|--start)
            start_environment
            ;;
        -d|--delete)
            stop_and_clean
            ;;
        -r|--restart)
            restart_environment
            ;;
        -h|--help)
            show_help
            ;;
        "")
            log_error "No command specified. Use './launch --help' for usage."
            ;;
        *)
            log_error "Unknown option: $1. Use './launch --help' for usage."
            ;;
    esac
}

main "$@"
