FROM python:3.12-slim

# tesseract reads label photos at intake; curl fetches the password blocklist
# and serves the health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The common-password blocklist lives in the image, outside the data volume,
# so every container has it. The script pins the source and checks its sha256.
ENV PASSWORD_BLOCKLIST_PATH=/app/security/password-blocklist.txt
COPY scripts/fetch_password_blocklist.sh scripts/
RUN bash scripts/fetch_password_blocklist.sh

COPY . .

# Proxies whose X-Forwarded-For is believed: localhost and the Docker bridge
# networks, where a reverse proxy on the host or in Compose connects from.
# Never "*": then any client could claim any address. Override in .env.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,172.16.0.0/12"

# The schema builds itself on first start (app/schema.py), under an advisory
# lock, so the workers starting together build it once.
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8081", \
     "--graceful-timeout", "30", \
     "--timeout", "120", \
     "--keep-alive", "5"]
