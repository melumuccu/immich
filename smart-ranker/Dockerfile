FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY docs ./docs
COPY src ./src

RUN python -m pip install "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"

FROM base AS dev

RUN python -m pip install -e .

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "smart_ranker.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010", "--reload", "--reload-dir", "/app/src"]

FROM base AS runtime

RUN python -m pip install .

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "smart_ranker.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010"]
