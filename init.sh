#!/bin/bash

CONTAINER_NAME="llm-web"
IMAGE_NAME="llm-web"
PORT=8501
WATCH_DIR="."  # 监听的目录，可改为你的项目根目录

# Check if Docker is installed
if ! command -v docker &> /dev/null
then
    echo "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if inotifywait is installed
if ! command -v inotifywait &> /dev/null
then
    echo "inotifywait is not installed. Please install inotify-tools."
    exit 1
fi

build_and_run() {
    if [ ! -f Dockerfile ]; then
        echo "Dockerfile not found. Cannot build image!"
        exit 1
    fi

    echo "Building Docker image ${IMAGE_NAME}..."
    docker build -t ${IMAGE_NAME} .
    if [ $? -ne 0 ]; then
        echo "Failed to build Docker image!"
        exit 1
    fi

    RUNNING_CONTAINER=$(docker ps -q --filter "name=^/${CONTAINER_NAME}$")
    if [ -n "$RUNNING_CONTAINER" ]; then
        echo "Stopping existing container ${CONTAINER_NAME}..."
        docker stop ${CONTAINER_NAME}
    fi

    echo "Starting Docker container ${CONTAINER_NAME}..."
    docker run -d --rm --name ${CONTAINER_NAME} -p ${PORT}:8501 ${IMAGE_NAME}
    if [ $? -eq 0 ]; then
        echo "Docker container is running. Access the service at http://localhost:${PORT}"
    else
        echo "Failed to start Docker container!"
        exit 1
    fi
}

# Initial build and run
build_and_run

echo "Watching ${WATCH_DIR} for changes. Press Ctrl+C to stop."
# Watch for Dockerfile or code changes
while true; do
    inotifywait -e modify,create,delete -r ${WATCH_DIR} --exclude '.*\.swp|.*\.tmp'
    echo "Changes detected. Rebuilding and restarting container..."
    build_and_run
done
