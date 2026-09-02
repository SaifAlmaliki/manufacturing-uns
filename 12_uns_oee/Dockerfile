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

# The command for building this image is
#       docker build -t uns/oee:<version> --build-arg GIT_HASH=<git hash or local> -f ./Dockerfile ..
#       e.g.
#       docker build -t uns/oee:0.9.38 --build-arg GIT_HASH=local -f ./Dockerfile ..
# Run the build command from the repository root (context is `..` from 12_uns_oee)
# Mount the repository-root conf/ folder at /app/conf.
#       e.g.
#       docker run --name uns_oee -v <repo-root>/conf:/app/conf --network=host uns/oee:0.9.38

# Use the official Python image
FROM python:3.14-alpine3.22

# Set the environment variable for the entrypoint command
# spell-checker:disable
ENV UNS_MODULE="12_uns_oee"\
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"
# spell-checker:enable
LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/12_uns_oee
LABEL org.opencontainers.image.description="Computes shift OEE from historised UNS data and publishes it back to MQTT"
LABEL org.opencontainers.image.licenses=MIT

# Set the working directory in the container to /
WORKDIR /app

# Copy the contents of the project into the container
COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
# The Asset Model: this module's ORM tables, its engine and its result repository all live
# there. alembic.ini and migrations/ are part of its build config, so they are copied even
# though the engine never migrates - the Asset Model image does that.
COPY ./09_uns_model/pyproject.toml ./09_uns_model/uv.lock ./09_uns_model/README.md ./09_uns_model/alembic.ini /09_uns_model/
COPY ./09_uns_model/migrations /09_uns_model/migrations
COPY ./09_uns_model/src /09_uns_model/src
COPY ./${UNS_MODULE}/src ./src/
COPY ./conf/settings.yaml /app/conf/settings.yaml

# install minimalistic missing packages & security fixes
RUN apk update && \
    apk add --no-cache libffi-dev libc-dev gcc && \
    apk upgrade --no-cache libexpat libcrypto3 libssl3 busybox ssl_client && \
    rm -rf /var/cache/apk/*

# Install pip & uv
RUN  pip install  --no-cache-dir --upgrade pip uv && \
    # create application user
    adduser --no-create-home --home /app --disabled-password uns_user && \
    chown -R uns_user /app && \
    # Install the required dependencies for the project using uv as that user
    su uns_user -c "uv lock && uv sync --no-group test --compile-bytecode"

USER uns_user

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

# Mount the volume /conf
VOLUME /app/conf
# Set the Entrypoint script to run the uns_oee module
ENTRYPOINT ["uv", "run", "--no-group", "test", "uns_oee"]
HEALTHCHECK --interval=60s --timeout=10s CMD ["uv", "run", "--no-group", "test", "uns_oee_health"]
