# Dockerfile

FROM python:3.10-slim

# Working directory
WORKDIR /app

# Copy dependencies and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy main code
COPY app.py ./

# Configure Streamlit default port
EXPOSE 8501

# Start Streamlit
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

# AK SK for TOS
ENV TOS_AK=<your ak>
ENV TOS_SK=<your sk>

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8501/ || exit 1
