FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m app && mkdir -p /data /models && chown -R app:app /data /models
COPY app ./app
USER app
ENV DATA_DIR=/data EMBEDDING_CACHE=/models
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
