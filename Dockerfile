FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/data/diamond_zs.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# /data must be a persistent volume on the host, otherwise the database is lost on restart.
VOLUME ["/data"]
CMD ["python", "main.py"]
