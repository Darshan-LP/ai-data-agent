.PHONY: up down logs seed health test eval shell

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

seed:
	docker compose exec app python -m db.seed

health:
	curl -s http://localhost:8000/health | python -m json.tool

test:
	docker compose exec app pytest -v

eval:
	docker compose exec app python -m eval.run_eval

shell:
	docker compose exec app bash