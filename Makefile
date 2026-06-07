.PHONY: up down build logs test load clean scale

# ── Start the full stack ──────────────────────────────────────────────────────
up:
	docker compose up --build -d
	@echo ""
	@echo "  Dashboard : http://localhost:3000"
	@echo "  API docs  : http://localhost:8000/docs"
	@echo "  API       : http://localhost:8000"
	@echo ""

# ── Stop everything ───────────────────────────────────────────────────────────
down:
	docker compose down

# ── Stop and wipe volumes (fresh start) ───────────────────────────────────────
clean:
	docker compose down -v

# ── Build images only ─────────────────────────────────────────────────────────
build:
	docker compose build

# ── Tail logs ─────────────────────────────────────────────────────────────────
logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-workers:
	docker compose logs -f worker

# ── Scale workers up/down ─────────────────────────────────────────────────────
scale:
	@read -p "Number of workers: " n; docker compose up -d --scale worker=$$n

scale-3:
	docker compose up -d --scale worker=3

scale-6:
	docker compose up -d --scale worker=6

# ── Run tests ─────────────────────────────────────────────────────────────────
test:
	pip install -r backend/requirements.txt fakeredis aiosqlite pytest-cov > /dev/null 2>&1
	pip install -r worker/requirements.txt > /dev/null 2>&1
	PYTHONPATH=. pytest tests/ -v --tb=short

test-cov:
	PYTHONPATH=. pytest tests/ -v --cov=backend/app --cov-report=term-missing

# ── Load test ─────────────────────────────────────────────────────────────────
load:
	python scripts/load_test.py --jobs 200 --concurrency 30 --type noop --wait

load-heavy:
	python scripts/load_test.py --jobs 1000 --concurrency 100 --type noop

load-realistic:
	python scripts/load_test.py --jobs 200 --concurrency 20 --type process_image --wait

# ── Submit a quick test job ───────────────────────────────────────────────────
smoke:
	curl -s -X POST http://localhost:8000/api/jobs/submit \
	  -H 'Content-Type: application/json' \
	  -d '{"type":"noop","payload":{},"priority":"high"}' | python -m json.tool

# ── Check worker status ───────────────────────────────────────────────────────
workers:
	curl -s http://localhost:8000/api/workers | python -m json.tool

# ── Queue metrics ─────────────────────────────────────────────────────────────
metrics:
	curl -s http://localhost:8000/api/metrics | python -m json.tool
