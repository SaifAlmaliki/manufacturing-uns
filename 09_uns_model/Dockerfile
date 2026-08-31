###############################################################################
# Copyright (c) 2021 Ashwin Krishnan
#
# All rights reserved. This program and the accompanying materials
# are made available under the terms of MIT and  is provided "as is",
# without warranty of any kind, express or implied, including but
# not limited to the warranties of merchantability, fitness for a
# particular purpose and noninfringement. In no event shall the
# authors, contributors or copyright holders be liable for any claim,
# damages or other liability, whether in an action of contract,
# tort or otherwise, arising from, out of or in connection with the software
# or the use or other dealings in the software.
#
# Contributors:
#    -
###############################################################################

# Runs the Asset Model migrations and seed. Short-lived: it exits when the schema
# is up to date, which is why docker-compose depends on it with
# `service_completed_successfully` rather than a healthcheck.
#
# The command for building this image is
#       docker build -t uns/model:<version> --build-arg GIT_HASH=<git hash or local> -f ./Dockerfile ..
# Run the build command from the repository root (context is `..` from 09_uns_model)
# Mount the repository-root conf/ folder at /app/conf.

FROM python:3.14-alpine3.22

# spell-checker:disable
ENV UNS_MODULE="09_uns_model"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"
# spell-checker:enable
LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/09_uns_model
LABEL org.opencontainers.image.description="Creates and seeds the authored Asset Model used to enrich UNS data"
LABEL org.opencontainers.image.licenses=MIT

WORKDIR /app

COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
COPY ./${UNS_MODULE}/src ./src/
# Migrations are not part of the wheel, so they are copied alongside it.
COPY ./${UNS_MODULE}/alembic.ini ./
COPY ./${UNS_MODULE}/migrations ./migrations/
COPY ./conf/settings.yaml /app/conf/settings.yaml

# install minimalistic missing packages & security fixes
RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

RUN  pip install  --no-cache-dir --upgrade pip uv && \
    adduser --no-create-home --home /app --disabled-password uns_user && \
    chown -R uns_user /app && \
    su uns_user -c "uv lock && uv sync --no-group test --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

VOLUME /app/conf

# Migrates, then seeds. Both are idempotent, so restarting this container is how the
# Asset Model is updated after conf/settings.yaml changes.
ENTRYPOINT ["uv", "run", "uns_model_setup"]
