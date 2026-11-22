# Troubleshooting

This build has not been run, so the first thing to expect is ordinary first-run defects:
an import error, a wrong field name, a type error from `tsc`. Read the first error in the
terminal; most will be one-line fixes. If you report one, include the `Reference` id shown
in the UI or the `request_id` from the JSON response and the matching backend log line.

## Backend

| Symptom | Likely cause | Fix |
|---|---|---|
| `RuntimeError: JWT_SECRET_KEY must be at least 32 characters long` | `.env` missing or placeholder too short | Generate one: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `connection refused` on start or migrate | PostgreSQL not running | `docker compose up -d db`, then `docker compose ps` |
| `password authentication failed` | An old Docker volume with different credentials | `docker compose down -v` (deletes local data), then up again |
| `ModuleNotFoundError: app` | Command run from the wrong folder | Run `alembic`, `uvicorn`, `pytest` and the seed from `backend/` |
| `pip install` fails on `psycopg[binary]` or `argon2-cffi` | Python version without prebuilt wheels | Use Python 3.12 |
| Seed says data already exists | Database was seeded before | `python -m scripts.seed --reset` (deletes all application data) |
| Integration tests are "NOT COLLECTED" | `TEST_DATABASE_URL` not set | See README, Tests |
| 503 `DATABASE_UNAVAILABLE` on a hosted copy | Supabase project paused | Unpause in the Supabase dashboard |
| `prepared statement already exists` | Transaction pooler with prepared statements | Already disabled in `core/database.py`; if seen, use the Session pooler URI |
| Startup error mentioning mock providers | `APP_ENV=production` with `LLM_PROVIDER=mock` or `SPEECH_PROVIDER=mock` | Use `none` or a real provider |

## Frontend

| Symptom | Likely cause | Fix |
|---|---|---|
| "Could not reach the server" | Backend not running on port 8000 | Start it; or set `VITE_DEV_BACKEND` before `npm run dev` |
| Signed out after refreshing the page | Refresh cookie not sent | Open the app at `http://localhost:5173`, not via `127.0.0.1` in one place and `localhost` in another; in production the frontend and `/api` must share an origin |
| `npm run build` fails with type errors | Code was never compiled before delivery | Fix the reported lines; `npm run dev` still serves the app while you do |
| Telugu text shows as boxes | No Telugu font on the device | Install Noto Sans Telugu, or add a web font |
| Hosted: API calls return the HTML page | `vercel.json` rewrite still has the placeholder host | Edit it, redeploy |
| Hosted: first action takes a minute | Render free service waking | Wait and press "Try again" |

## Assistant and voice

| Symptom | Likely cause | Fix |
|---|---|---|
| Banner says guided mode | `LLM_PROVIDER=none`, or Gemini failing | Expected without a key. With a key, check `/api/v1/health/ready` and backend logs for `llm_call_failed` |
| `llm_call_failed` with status 404 | Model name not available to the key | Set `GEMINI_MODEL` to a model listed in AI Studio |
| `llm_call_failed` quota | Free quota used up | Wait for reset; the assistant keeps working in guided mode |
| No microphone button | `SPEECH_PROVIDER=none` | Expected. Configure Azure Speech to enable |
| "The microphone is blocked" | Browser permission denied, or page not on HTTPS or localhost | Allow the microphone; browsers require a secure origin |
| Speech token 503 | Wrong key or region | Check `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION` match the resource |
| No spoken reply | Voice name not available in the region | Set `VITE_TTS_VOICE_TE` and `VITE_TTS_VOICE_EN` to voices listed for your region |

## Resetting local state

```bash
docker compose down -v && docker compose up -d db
cd backend && alembic upgrade head && python -m scripts.seed
```
