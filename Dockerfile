FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN mkdir -p uploads data thumbnails

ENV HOST=0.0.0.0
ENV PORT=8000
ENV OLLAMA_HOST=http://host.docker.internal:11434

EXPOSE 8000

CMD ["python", "backend/main.py"]
