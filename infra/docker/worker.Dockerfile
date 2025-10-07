FROM python:3.11-slim
WORKDIR /worker
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY apps/api/pyproject.toml apps/api/poetry.lock* ./
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi
COPY apps/api/ ./
CMD ["python", "-m", "app.worker.jobs"]
