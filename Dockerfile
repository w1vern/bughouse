
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Fairy-Stockfish — engine used by bots (crazyhouse per board). Bots fall back
# to random moves if ENGINE_PATH is unset, so this is only needed in prod.
ARG FAIRY_SF_URL=https://github.com/fairy-stockfish/Fairy-Stockfish/releases/download/fairy_sf_14/fairy-stockfish_x86-64
RUN curl -fsSL "$FAIRY_SF_URL" -o /usr/local/bin/fairy-stockfish \
    && chmod +x /usr/local/bin/fairy-stockfish

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

COPY shared/protobuf/*.proto shared/protobuf/

RUN uv run --no-dev -m grpc_tools.protoc \
		--proto_path=. \
		--python_out=. \
		--pyi_out=. \
		--grpc_python_out=. \
		--mypy_grpc_out=. \
		shared/protobuf/*.proto

COPY . .

ENV PYTHONUNBUFFERED=1

ENV PATH="/app/.venv/bin:$PATH"
