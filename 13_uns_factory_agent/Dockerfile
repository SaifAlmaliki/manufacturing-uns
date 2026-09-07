###############################################################################
# Factory Copilot agent — read-only plant colleague for the UNS console.
###############################################################################

FROM python:3.14-alpine3.22

ENV UNS_MODULE="13_uns_factory_agent"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"

LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/13_uns_factory_agent
LABEL org.opencontainers.image.description="Read-only Factory Copilot agent for the UNS console"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
COPY ./09_uns_model/pyproject.toml ./09_uns_model/uv.lock ./09_uns_model/README.md ./09_uns_model/alembic.ini /09_uns_model/
COPY ./09_uns_model/migrations /09_uns_model/migrations
COPY ./09_uns_model/src /09_uns_model/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

RUN pip install --no-cache-dir --upgrade pip uv && \
    adduser --no-create-home --home /app --disabled-password uns_user && \
    chown -R uns_user /app && \
    su uns_user -c "uv sync --frozen --no-group test --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

VOLUME /app/conf
EXPOSE 8010
ENTRYPOINT ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uvicorn", "uns_factory_agent.app:app", "--host", "0.0.0.0", "--port", "8010"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uns_factory_agent_health"]
