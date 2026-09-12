FROM python:3.14-slim

WORKDIR /app
COPY 00_uns_config /app/00_uns_config
COPY 15_uns_edge_agent /app/15_uns_edge_agent
COPY pyproject.toml uv.lock /app/

RUN pip install --no-cache-dir uv \
    && uv sync --package uns_edge_agent --frozen --no-dev

ENV UNS_EDGE_DATA_DIR=/var/lib/uns-edge-agent
VOLUME ["/var/lib/uns-edge-agent"]

ENTRYPOINT ["uv", "run", "--package", "uns_edge_agent", "uns_edge_agent"]
