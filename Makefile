.PHONY: back

back:
	uvicorn services.backend.main:app --reload

back_install:
	uv sync

gen_migration:
	alembic -c services/alembic/alembic.ini revision --autogenerate -m "first migration"

migration:
	alembic -c services/alembic/alembic.ini upgrade head

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
	git submodule add --name frontend https://github.com/ImmortalAI/Bughouse-Chess-Front services/frontend

install_submodules:
	git submodule update --init --recursive

update_submodules:
	git submodule update --remote --recursive
