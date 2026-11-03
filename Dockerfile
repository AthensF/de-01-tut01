# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    python -m pip install --no-cache-dir uv==0.13.4 && useradd --create-home appuser
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
COPY --chown=appuser:appuser src ./src
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev
USER appuser
ENV ROADSAFETY_DATA_DIR=/tmp/roadsafety
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync uvicorn roadsafety.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
