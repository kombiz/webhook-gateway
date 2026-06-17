FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY services/ services/

EXPOSE 4100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import httpx, sys; sys.exit(0 if httpx.get('http://localhost:4100/health').status_code == 200 else 1)"

CMD ["python", "-m", "uvicorn", "services.webhook_gateway.main:app", "--host", "0.0.0.0", "--port", "4100"]
