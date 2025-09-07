#!/bin/bash

# =========================
# Config variables
# =========================
CONTAINER_NAME="llm-web"
IMAGE_NAME="llm-web"
PORT=8501
CHECK_INTERVAL=30   # health check interval (seconds)
HEALTH_URL="http://localhost:$PORT"

# =========================
# Functions
# =========================

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo "[ERROR] Docker is not installed. Please install Docker first."
        exit 1
    fi
}

build_image() {
    echo "[INFO] Building Docker image: $IMAGE_NAME ..."
    docker build -t $IMAGE_NAME . || { echo "[ERROR] Failed to build image"; exit 1; }
}

remove_old_container() {
    if [ "$(docker ps -aq -f name=^${CONTAINER_NAME}$)" ]; then
        echo "[INFO] Removing old container: $CONTAINER_NAME ..."
        docker rm -f $CONTAINER_NAME
    fi
}

start_container() {
    echo "[INFO] Starting container: $CONTAINER_NAME ..."
    docker run -d \
        --name $CONTAINER_NAME \
        -p $PORT:$PORT \
        --restart always \
        $IMAGE_NAME
    sleep 2
}

check_status() {
    if [ "$(docker ps -q -f name=^${CONTAINER_NAME}$)" ]; then
        echo "[SUCCESS] Container '$CONTAINER_NAME' is running."
    else
        echo "[ERROR] Container failed to start."
        exit 1
    fi
}

# =========================
# Main script
# =========================

check_docker
build_image
remove_old_container
start_container
check_status
