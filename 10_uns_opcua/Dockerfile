FROM python:3.14-alpine3.22

ARG UNS_MODULE=10_uns_opcua
ENV UNS_MODULE=${UNS_MODULE}
ENV UNS_CONF_DIR=/app/conf

LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/10_uns_opcua
LABEL org.opencontainers.image.description="Read-only OPC UA edge connector. Subscribes to PLC/SCADA nodes and publishes them into the Unified Namespace with disk-backed store-and-forward"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/README.md ./LICENSE* ./
# 00_uns_config and 09_uns_model land at the paths this module's `../` uv sources expect.
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
# uns_model provides the Asset Model tables the mapping is validated against. alembic.ini
# and migrations/ are part of its build config, so they are copied even though this
# connector never migrates - the Asset Model image does that.
COPY ./09_uns_model/pyproject.toml ./09_uns_model/README.md ./09_uns_model/alembic.ini /09_uns_model/
COPY ./09_uns_model/migrations /09_uns_model/migrations
COPY ./09_uns_model/src /09_uns_model/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

# install minimalistic missing packages & security fixes
RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

RUN pip install --no-cache-dir --upgrade pip uv && \
    adduser --no-create-home --home /app --disabled-password uns_user && \
    # The spool lives on a volume; uns_user must own its mount point.
    mkdir -p /var/lib/uns_opcua && \
    chown -R uns_user /app /var/lib/uns_opcua && \
    su uns_user -c "uv lock && uv sync --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

VOLUME /app/conf
VOLUME /var/lib/uns_opcua
ENTRYPOINT ["uv", "run", "uns_opcua"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "uns_opcua_healthcheck"]
