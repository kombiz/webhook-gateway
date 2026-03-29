FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY services/ services/

EXPOSE 4100

CMD ["python", "-m", "uvicorn", "services.webhook_gateway.main:app", "--host", "0.0.0.0", "--port", "4100"]
