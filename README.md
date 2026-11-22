# CareBridge AI

A Telugu and English healthcare appointment coordination platform for patients, family
caregivers, doctors and hospital administrators. It books, changes and cancels appointments
in three simulated Hyderabad hospitals, by voice, by typing, or step by step with buttons.

> **Verification status: UNVERIFIED BUILD.** This project was written in an environment
> that could not install FastAPI, SQLAlchemy, PostgreSQL drivers, React or Vite. The
> application has therefore **never been started**, the database migrations have never been
> applied, and the integration tests have never been run. What was and was not executed is
> listed exactly in [docs/TESTING.md](docs/TESTING.md). Expect to fix some defects on first
> run. Feature-by-feature status is in [docs/STATUS.md](docs/STATUS.md).

> **Demonstration only.** All hospitals, doctors and patients are synthetic. The
> symptom-to-department suggestions and intake questions have not been reviewed by a
> clinician. Do not enter real patient information and do not use this to make care decisions.

## What it does

| Area | Summary |
|---|---|
| Patient | Book by assistant or step by step, view, change, cancel, waiting list, pre-visit questions, optional AI summary of own answers, follow-up instructions, manage caregivers |
| Caregiver | Request access to a patient, act only within the permissions that patient granted |
| Doctor | Day list, patient's answers, patient-approved AI summary, private notes, follow-up, mark completed or not attended |
| Hospital admin | Departments, doctors, weekly hours, slot generation, block and unblock, appointment list, cancel with reason |
| Assistant | Telugu and English conversation that collects what is needed and books only after explicit confirmation. Works without any AI key in "guided mode" |
| Voice | Azure Speech in the browser when configured. Without it the microphone is hidden and typing is used |

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg 3, Pydantic 2, Argon2id, PyJWT, httpx
- **Frontend:** React 18, TypeScript, Vite 5, Tailwind CSS 3, React Router 6, i18next
- **Optional providers:** Google Gemini API (assistant language understanding, summaries), Azure Speech (voice)
- **Hosting target (free plans):** Supabase Postgres, Render web service, Vercel static hosting

## Quick start

Prerequisites: Python 3.12, Node.js 20, Docker (for PostgreSQL), Git.

```bash
# 1. Database
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                 # Windows: copy .env.example .env
# edit .env and set JWT_SECRET_KEY (the file tells you how to generate one)
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload --port 8000

# 3. Frontend (second terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API documentation is at http://localhost:8000/api/docs.

To run everything in containers instead: `cp .env.example .env`, set `JWT_SECRET_KEY`, then
`docker compose --profile app up --build`, and seed with
`docker compose exec backend python -m scripts.seed`.

## Demo accounts

Created by `python -m scripts.seed`. All are synthetic. The shared demo password is
`Demo@12345` unless you set `SEED_PASSWORD` before seeding. Never seed a public deployment
with the default password.

| Role | Sign in with | Notes |
|---|---|---|
| Patient | `9000000001` | Lakshmi Devi (Demo), Telugu, has one booked appointment |
| Patient | `patient2@carebridge.demo` | Ramesh Kumar (Demo), has one caregiver request waiting |
| Caregiver | `caregiver@carebridge.demo` | Sita Devi (Demo), approved for Lakshmi with view, book, reminders |
| Doctor | `doctor1@carebridge.demo` to `doctor17@carebridge.demo` | doctor1 has the seeded appointment |
| Hospital admin | `admin.a@carebridge.demo`, `admin.b@…`, `admin.c@…` | One per simulated hospital |

## Tests

```bash
cd backend
pytest tests/unit                                    # no database needed
TEST_DATABASE_URL=postgresql+psycopg://carebridge:carebridge@localhost:5432/carebridge_test pytest tests/integration
cd ../frontend && npm run typecheck && npm test
python ../tools/check_i18n.py
```

The integration tests need PostgreSQL and delete everything in the database they are
pointed at. `docker compose up -d db` creates `carebridge_test` for this purpose.

## Folder structure

```
CareBridge-AI/
├── README.md, CHANGELOG.md, Makefile, docker-compose.yml, render.yaml, .env.example, .gitignore
├── .github/workflows/ci.yml        CI definition (not yet executed)
├── docker/init-test-db.sql         creates the disposable test database
├── tools/                          build_locales.py, check_i18n.py
├── docs/                           SRS, architecture, database, API, AI and voice, security,
│                                   cost, testing, deployment, troubleshooting, status, demo
├── backend/
│   ├── app/
│   │   ├── main.py                 application, middleware, error handling
│   │   ├── constants.py, models.py, schemas.py, serializers.py
│   │   ├── core/                   config, database, security, errors, rate limits, time, deps
│   │   ├── api/                    auth, care, directory, appointments, assistant, admin, health
│   │   ├── services/               access, booking, waitlist, care, clinical, navigation,
│   │   │                           safety, assistant_core, assistant, directory, jobs
│   │   ├── integrations/           llm.py (none, gemini, mock), speech.py (none, azure, mock)
│   │   └── i18n/templates.py       assistant wording in Telugu and English
│   ├── alembic/                    migration environment and versions/0001_initial_schema.py
│   ├── scripts/                    seed.py, supabase_enable_rls.sql
│   ├── tests/unit/                 pure logic tests (executed, see docs/TESTING.md)
│   ├── tests/integration/          PostgreSQL-backed API tests (written, not executed)
│   ├── requirements.txt, requirements-dev.txt, Dockerfile, alembic.ini, pytest.ini, .env.example
└── frontend/
    ├── src/
    │   ├── main.tsx, App.tsx, Layout.tsx, api.ts, auth.tsx, ui.tsx, i18n.ts, index.css
    │   ├── lib/                    format.ts, speech.ts
    │   ├── locales/                en.json, te.json
    │   └── pages/                  Login, Home, Assistant, Book, Appointments, AppointmentDetail,
    │                               CareCircle, CaregiverPatients, DoctorToday, Admin,
    │                               Notifications, Settings
    ├── package.json, vite.config.ts, tsconfig.json, tailwind.config.js, postcss.config.js
    ├── index.html, vercel.json, Dockerfile, .env.example
```

## Documentation

| Document | Contents |
|---|---|
| [docs/STATUS.md](docs/STATUS.md) | What is implemented, partial, planned, and known limitations |
| [docs/TESTING.md](docs/TESTING.md) | Exactly which checks were run and their results |
| [docs/SRS.md](docs/SRS.md) | Requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components and request flows |
| [docs/DATABASE.md](docs/DATABASE.md) | Tables, constraints, ER diagram |
| [docs/API.md](docs/API.md) | Endpoints, envelope, error codes |
| [docs/AI_AND_VOICE.md](docs/AI_AND_VOICE.md) | Assistant design, safety rules, voice |
| [docs/SECURITY_AND_PRIVACY.md](docs/SECURITY_AND_PRIVACY.md) | Controls, data handling, gaps |
| [docs/COST_AND_FREE_TIER.md](docs/COST_AND_FREE_TIER.md) | Free plan limits and credentials needed |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Supabase, Render, Vercel steps |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common failures and fixes |
| [docs/DEMO.md](docs/DEMO.md) | A walkthrough script |

## Licence and use

No licence file is included; the author has not chosen one. The Vercel free plan permits
personal, non-commercial use only.
