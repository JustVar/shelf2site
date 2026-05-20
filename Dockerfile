FROM python:3.12-slim

RUN apt-get update && apt-get install -y     gcc     libpq-dev     nmap     tesseract-ocr     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "app.main:app",      "--worker-class", "uvicorn.workers.UvicornWorker",      "--workers", "6",      "--bind", "0.0.0.0:8081",      "--forwarded-allow-ips=*",      "--graceful-timeout", "30",      "--timeout", "120",      "--keep-alive", "5"]
