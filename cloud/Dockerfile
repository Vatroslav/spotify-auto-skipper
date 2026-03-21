FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directory
RUN groupadd -r skipper && useradd -r -g skipper -d /app skipper \
    && mkdir -p /app/data && chown -R skipper:skipper /app

COPY --chown=skipper:skipper app/ ./app/

USER skipper

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
