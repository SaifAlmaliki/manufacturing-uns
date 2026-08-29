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
#       docker build -t uns/simulator:<version> --build-arg GIT_HASH=<git hash or local> -f ./Dockerfile ..
#       e.g.
#       docker build -t uns/simulator:0.5.0 --build-arg GIT_HASH=local -f ./Dockerfile ..
#       docker build -t uns/simulator:local --build-arg GIT_HASH=local -f ./Dockerfile ..
# Run the build command from the repository root (context is `..` from 99_simulator)
# Mount the repository-root conf/ folder at /app/conf.
# Provide network if you are connecting to other services
#       e.g.
#       docker run --name uns_simulator -v <repo-root>/conf:/app/conf --network=host uns/simulator:<version>

# Use the official Python image
FROM python:3.14-alpine3.22

# Set the environment variable for the entrypoint command
# spell-checker:disable
ENV UNS_MODULE="99_simulator" \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UNS_CONF_DIR="/app/conf"
# spell-checker:enable
LABEL org.opencontainers.image.source=https://github.com/mkashwin/unifiednamespace/tree/main/99_simulator
LABEL org.opencontainers.image.description="Publishes synthetic ISA-95 MQTT device data for local UNS testing. Not for production."
LABEL org.opencontainers.image.licenses=MIT

# Set the working directory in the container to /
WORKDIR /app

# Copy the contents of the project into the container
COPY ./${UNS_MODULE}/pyproject.toml ./${UNS_MODULE}/uv.lock ./${UNS_MODULE}/README.md ./LICENSE* ./
COPY ./00_uns_config/pyproject.toml ./00_uns_config/README.md /00_uns_config/
COPY ./00_uns_config/src /00_uns_config/src
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
    # Install runtime dependencies only (skip the default test extra group)
    su uns_user -c "uv lock  \
    && uv sync --no-default-groups --compile-bytecode"

USER uns_user

# Keep ENTRYPOINT as ["uv", "run", "uns_simulator"] (CI checks that shape).
# Prevent `uv run` from installing the default test extra group at container start.
ENV UV_NO_DEFAULT_GROUPS=true \
    UV_FROZEN=true

ARG GIT_HASH
ENV GIT_HASH=${GIT_HASH:-dev}

# Mount the volume /conf
VOLUME /app/conf
# Set the Entrypoint script to run the uns_simulator module
ENTRYPOINT ["uv", "run", "uns_simulator"]
