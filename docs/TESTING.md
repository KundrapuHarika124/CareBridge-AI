# Testing

## Summary

| | Count |
|---|---|
| Automated tests written | 90 (33 backend unit, 51 backend integration, 6 frontend unit) |
| Executed with the real test runner, passed | **33** (backend unit, pytest) |
| Executed with the real test runner, failed | **0** |
| Executed only under a stand-in harness, passed | 6 (frontend unit; see below) |
| **Not executed** | **51** backend integration tests, plus the 6 frontend tests under Vitest |

The application itself was **not started**. No HTTP request was served, no SQL was run, no
page was rendered in a browser, no migration was applied, no container was built, and no
call was made to Gemini, Azure, Supabase, Render or Vercel.

## Why

The delivery environment had no network access for package installs. FastAPI, SQLAlchemy,
Alembic, psycopg, argon2-cffi, httpx, pydantic-settings, React, Vite, Vitest and Tailwind
were not available, and there was no PostgreSQL server. The project owner chose to receive
the agreed stack untested rather than a different stack that could be run there.

## What was executed (20 November 2026)

All of the following were run on a clean extraction of the delivered ZIP.

| # | Check | Command | Result |
|---|---|---|---|
| 1 | Backend unit tests | `pytest tests/unit` (Python 3, pytest) | 33 passed, 0 failed |
| 2 | Python syntax | `python -m py_compile` on every `.py` file | all compiled |
| 3 | Translation keys | `python tools/check_i18n.py` | 338 keys in each language, identical keys and placeholders, every key used in the code is defined |
| 4 | Frontend syntax and import resolution | esbuild bundle of `src/main.tsx` with third-party packages marked external | bundled without errors |
| 5 | Frontend types, limited | TypeScript 6 compiler with hand-written stand-in declarations for React, React Router, i18next and the Speech SDK | no errors. This checks the project's own types (API shapes, props between its own components). It does **not** check correct use of the libraries, and the project targets TypeScript 5.5 |
| 6 | Frontend unit test logic | The two test files bundled with a 20-line stand-in for `describe/it/expect` and run in Node | 6 passed, 0 failed. **Not a Vitest run** |
| 7 | ER diagram | Mermaid CLI render of the diagram in DATABASE.md | rendered to `docs/er-diagram.svg` |
| 8 | Configuration files | JSON and YAML parsed | all parsed |
| 9 | Secret scan | Pattern search for provider key formats, private keys, JWTs and assigned literals | no secrets. Matches were test fixtures and the documented demo seed password only |
| 10 | Archive | `unzip -t`, extraction to an empty folder, check for excluded files | passed; see the delivery message |

What the 33 unit tests cover: the rate limiter, IST date and time helpers and date
phrases, assistant template parity between Telugu and English, identifier normalisation
(phone and email), registration role and password rules, emergency and medical-advice
detection in English, Telugu and romanised Telugu, concern matching, sanitising of model
output, the rule-based extractor, yes/no detection, and the assistant state machine driven
through a fake data port (full booking conversation, one-sentence requests, confirmation
rules, corrections, no-slot handling, unclear-turn hand-off, and caregiver patient
selection and permission checks).

## What was not executed

| Area | Tests written | To run |
|---|---|---|
| Authentication, refresh rotation and reuse detection, rate limits | `tests/integration/test_auth.py` (10) | PostgreSQL |
| Booking, idempotency, cancel, reschedule, **20 concurrent bookings of one slot** | `test_booking.py` (8) | PostgreSQL |
| Access control across roles and hospitals, 404 for out-of-scope records | `test_authorization.py` (9) | PostgreSQL |
| Caregiver consent lifecycle | `test_care.py` (5) | PostgreSQL |
| Assistant over HTTP in guided mode and with a stand-in model | `test_assistant.py` (12) | PostgreSQL |
| Intake, summary release gate, notes, follow-up, admin, waiting list | `test_clinical_admin_waitlist.py` (7) | PostgreSQL |
| Frontend unit tests under Vitest | `src/lib/format.test.ts`, `src/i18n.test.ts` | `npm install` |
| Type check against real library types | n/a | `npm run typecheck` |
| Production build | n/a | `npm run build` |
| Migration | n/a | `alembic upgrade head` |
| Seed | n/a | `python -m scripts.seed` |
| Docker images, compose, CI workflow | n/a | Docker, GitHub |

Not written at all: component tests, end-to-end browser tests, accessibility tests, load
tests, tests against the real Gemini or Azure services.

## Running everything

```bash
docker compose up -d db

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/unit
TEST_DATABASE_URL=postgresql+psycopg://carebridge:carebridge@localhost:5432/carebridge_test pytest tests/integration

cd ../frontend
npm install
npm run typecheck
npm test
npm run build

cd .. && python tools/check_i18n.py
```

Notes:
- The integration tests **drop and recreate every table** in the database named by
  `TEST_DATABASE_URL`. Point it only at a disposable database.
- Without `TEST_DATABASE_URL`, the integration tests are not collected and the pytest header
  says so. A plain `pytest` therefore reports 33 passed; that does not mean the integration
  tests passed.
- The concurrency test starts 20 threads; it needs the default connection pool or larger.

## Manual test checklist

See [DEMO.md](DEMO.md). None of it has been performed.
