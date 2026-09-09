FROM python:3.14-slim-bookworm

ENV UNS_MODULE="14_uns_datalake"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"

LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/14_uns_datalake
LABEL org.opencontainers.image.description="Consumes uns.historic-events and archives bounded Parquet objects"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
COPY ./02_mqtt-cluster/pyproject.toml ./02_mqtt-cluster/uv.lock ./02_mqtt-cluster/README.md /02_mqtt-cluster/
COPY ./02_mqtt-cluster/src /02_mqtt-cluster/src
COPY ./06_uns_kafka/pyproject.toml ./06_uns_kafka/uv.lock ./06_uns_kafka/README.md /06_uns_kafka/
COPY ./06_uns_kafka/src /06_uns_kafka/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates librdkafka1 && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip uv && \
    useradd --no-create-home --home-dir /app --shell /bin/sh uns_user && \
    chown -R uns_user /app && \
    su uns_user -c "uv sync --frozen --no-group test --compile-bytecode"

USER uns_user

ENTRYPOINT ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uns_datalake"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "--frozen", "--no-sync", "--no-group", "test", "uns_datalake_healthcheck"]
