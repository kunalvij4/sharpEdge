FROM ghcr.io/astral-sh/uv:0.9.4 AS uv
FROM python:3.13.6-slim-bookworm
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && groupadd --gid 10001 odds \
    && useradd --uid 10001 --gid odds --create-home odds \
    && mkdir -p /app/artifacts \
    && chown odds:odds /app/artifacts
COPY --chown=odds:odds odds_api ./odds_api
COPY --chown=odds:odds migrations ./migrations
COPY --chown=odds:odds alembic.ini ./
COPY --chown=odds:odds scripts ./scripts
ENV PATH="/app/.venv/bin:$PATH" TZ="America/New_York"
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "odds_api.runtime"]
