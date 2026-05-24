FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required for ChromaDB / SQlModel compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements relative to the root build context
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all root project directories (backend, frontend, agent) into the container
COPY . .

EXPOSE 8000
EXPOSE 8501