
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

RUN uv sync --locked --no-dev

COPY . .

RUN uv run --no-dev -m grpc_tools.protoc \
		--proto_path=. \
		--python_out=. \
		--pyi_out=. \
		--grpc_python_out=. \
		--mypy_grpc_out=. \
		shared/protobuf/core.proto

ENV PYTHONUNBUFFERED=1

ENV PATH="/app/.venv/bin:$PATH"
