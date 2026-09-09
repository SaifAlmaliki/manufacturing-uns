###############################################################################
# Copyright (c) 2021 Ashwin Krishnan
#
# Build from repository root:
#   docker build -t uns/datalake:<version> -f ./14_uns_datalake/Dockerfile .
###############################################################################

FROM python:3.14-slim-bookworm

ENV UNS_MODULE="14_uns_datalake"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"

LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/14_uns_datalake
LABEL org.opencontainers.image.description="Consumes uns.historic-events and writes Parquet to S3 or ADLS"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

RUN apt-get update && \
    apt-get install -y --no-install-recommends librdkafka1 ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip uv && \
    useradd --create-home --home-dir /app --uid 1000 uns_user && \
    chown -R uns_user /app /00_uns_config && \
    su uns_user -c "uv sync --frozen --no-group test --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

VOLUME /app/conf
ENTRYPOINT ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uns_datalake"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uns_datalake_health"]
