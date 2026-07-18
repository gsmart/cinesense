FROM python:3.12-slim
WORKDIR /app
COPY services/api /app/services/api
RUN pip install --no-cache-dir "/app/services/api[dev]"
WORKDIR /app/services/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
