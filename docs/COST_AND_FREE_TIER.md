# Cost and free plans

Target spend: ₹0. The application runs with **no external account at all** (local
PostgreSQL, guided assistant, typing). Each provider below is optional and off by default.
There is no automatic fallback to anything paid.

Provider limits were checked on 20 November 2026 unless marked otherwise. They change; check
each provider's pricing page before relying on them.

## Credentials needed, and for what

| Feature | Needs | Environment variables | Without it |
|---|---|---|---|
| Core app | Nothing external | `DATABASE_URL`, `JWT_SECRET_KEY` (you generate it) | n/a |
| Free-sentence understanding and AI summaries | Google AI Studio API key | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL` | Guided mode; summaries unavailable |
| Voice | Azure Speech resource (F0) | `SPEECH_PROVIDER=azure`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Typing and buttons |
| Hosted database | Supabase project | `DATABASE_URL` | Local PostgreSQL |
| Hosted backend | Render account | set in dashboard | Run locally |
| Hosted frontend | Vercel account | none (edit `vercel.json`) | Run locally |

Put keys in `backend/.env` or the host's dashboard. Never in the frontend, the repository,
or a chat.

## Free plan facts and risks

| Service | Free allowance | Risk and what happens here |
|---|---|---|
| Gemini API | Free tier on Flash and Flash-Lite models. Requests per minute and per day: **not verified, check AI Studio** | Free-tier content may be used to improve Google products: synthetic data only. On 429 the assistant falls back to guided mode for that turn |
| Azure Speech F0 | 5 audio hours of speech to text and 0.5 million neural text-to-speech characters per month | Whether a card is required at sign-up: **not verified**. When the quota ends, token or recognition calls fail and the UI falls back to typing |
| Supabase Free | 500 MB database, 2 projects | Project pauses after about a week without activity; no automatic backups. Unpause in the dashboard |
| Render Free web service | 750 hours per month | Sleeps after 15 idle minutes; first request then takes about a minute. Background jobs do not run while asleep, so reminders and offer expiry are delayed |
| Vercel Hobby | Static hosting and rewrites | Personal, non-commercial use only |

Render's free PostgreSQL was not chosen because it expires after 30 days.

## Keeping it at zero

- Leave `LLM_PROVIDER` and `SPEECH_PROVIDER` as `none` unless demonstrating those features.
- Do not attach a payment method where a provider lets you avoid it. If one is required, set
  a budget alert at the lowest value and use the free SKU explicitly (Azure Speech **F0**).
- Assistant turns are limited to 30 per user per hour and speech tokens to 20 per hour.
- Do not add an uptime pinger to keep Render awake: it uses the monthly hours faster and may
  breach the provider's terms.
