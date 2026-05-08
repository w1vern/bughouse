.PHONY: back

back:
	uvicorn run -m services.backend

back_install:
	uv sync

gen_migration:
	uv run -m alembic -c services/alembic/alembic.ini revision --autogenerate

migration:
	uv run -m alembic -c services/alembic/alembic.ini upgrade head

down_migration:
	alembic -c services/alembic/alembic.ini downgrade -1

docker:
	docker compose up -d

docker_down:
	docker compose down --volumes

docker_build:
	docker compose up -d --build

docker_test:
	docker compose -f compose.yml -f compose.test.yml up -d --build

docker_test-down:
	docker compose -f compose.yml -f compose.test.yml down -v

add_frontend:
	git submodule add --name frontend https://github.com/ImmortalAI/bugchess-vue services/frontend

install_submodules:
	git submodule update --init --recursive

update_submodules:
	git submodule update --remote --recursive

proto:
	uv run -m grpc_tools.protoc \
		--proto_path=. \
		--python_out=. \
		--pyi_out=. \
		--grpc_python_out=. \
		--mypy_grpc_out=. \
		shared/protobuf/core.proto

cd:
	curl -i -X POST http(s)://<DOMAIN>/deploy/ -H "Authorization: Bearer <SECRET>"

staging:
	git checkout staging && \
	git merge dev && \
	git push && \
	git checkout dev

main: 
	git checkout main && \
	git merge dev && \
	git push && \
	git checkout dev