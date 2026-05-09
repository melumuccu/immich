FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY docs ./docs
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "smart_ranker.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010"]
