FROM ghcr.io/astral-sh/uv:0.9.4 AS uv
FROM python:3.13.6-slim-bookworm
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && groupadd --gid 10001 odds \
    && useradd --uid 10001 --gid odds --create-home odds
COPY --chown=odds:odds odds_api ./odds_api
COPY --chown=odds:odds migrations ./migrations
COPY --chown=odds:odds alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "odds_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
