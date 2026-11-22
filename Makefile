# Convenience targets. Each one is a plain command you can also run by hand (see README).
.PHONY: db backend-install frontend-install migrate seed backend frontend test-unit test-integration test-frontend check-i18n zip

db:
	docker compose up -d db

backend-install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt

frontend-install:
	cd frontend && npm install

migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

seed:
	cd backend && . .venv/bin/activate && python -m scripts.seed

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test-unit:
	cd backend && . .venv/bin/activate && pytest tests/unit

test-integration:
	cd backend && . .venv/bin/activate && TEST_DATABASE_URL=postgresql+psycopg://carebridge:carebridge@localhost:5432/carebridge_test pytest tests/integration

test-frontend:
	cd frontend && npm run typecheck && npm test

check-i18n:
	python tools/check_i18n.py
