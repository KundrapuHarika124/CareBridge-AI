# Implementation status

Date: 20 November 2026. Version 0.1.0.

## How to read this

- **Implemented, unverified**: the code is written for the whole path (database, API,
  screen) but has never been executed end to end. It should be treated as a first draft
  that has passed static checks only.
- **Partial**: some of the path exists; what is missing is stated.
- **Planned**: not built.

Nothing in this project is "verified working" except the items listed as executed in
[TESTING.md](TESTING.md).

## Implemented, unverified

| Feature | Backend | Frontend | Automated tests written |
|---|---|---|---|
| Registration, sign in, session renewal, sign out, change password | yes | yes | integration (not run) |
| Role and relationship based access control | yes | route guards for convenience | integration (not run) |
| Specialties, hospitals, doctors, free slots | yes | yes | integration (not run) |
| Department suggestion from a concern | yes | yes | unit (run), integration (not run) |
| Booking with idempotency and concurrency protection | yes | yes | integration incl. 20-thread race (not run) |
| Cancel, reschedule | yes | yes | integration (not run) |
| Waiting list with timed offers | yes | yes | integration (not run) |
| Caregiver request, approve, edit, revoke, history | yes | yes | integration (not run) |
| Pre-visit questions | yes | yes | integration (not run) |
| Doctor notes, follow-up, outcome | yes | yes | integration (not run) |
| Hospital admin: departments, doctors, hours, slots, cancel | yes | yes | integration (not run) |
| In-app notifications | yes | yes | partly, integration (not run) |
| Assistant: guided mode | yes | yes | unit for the state machine (run), integration (not run) |
| Telugu and English interface | assistant templates | all screens | key parity check (run) |
| Audit log | yes | no screen | integration touches it (not run) |

## Implemented, unverified, and needs external credentials

| Feature | Needs | State |
|---|---|---|
| Assistant understanding free sentences | Gemini API key | Client written from documentation. No call has ever been made |
| AI summary of intake answers | Gemini API key | Same. Tests use a stand-in model (not run) |
| Voice input and spoken replies | Azure Speech key and region | Token exchange and browser SDK calls written from documentation. Never exercised |
| Hosted deployment | Supabase, Render, Vercel accounts | Configuration files written. Never deployed |

## Partial

| Feature | What exists | What is missing |
|---|---|---|
| Reminders | In-app reminder about 24 hours before, from an in-process job | SMS, WhatsApp, email. Does not run while a free host is asleep |
| Migrations | One revision that creates all tables from the models | A frozen, hand-reviewed initial revision; downgrade drops everything |
| Accessibility | Labels, focus styles, status as text, large targets, skip link, dialog focus handling | No screen-reader testing, no contrast audit, no testing with older users |
| Telugu | All strings translated | Written by an AI model; not reviewed by a native-speaking editor |
| Rate limiting | Per-process, in memory | Shared store, persistence across restarts |
| CI | Workflow file | Never executed |
| Docker | Backend and frontend Dockerfiles, compose file | Never built |
| Frontend tests | Two unit test files | No component or end-to-end tests |
| Dependency pinning | Exact versions in `requirements.txt`, ranges in `package.json` | **No lockfiles.** `npm install` will create `package-lock.json`; commit it |

## Planned (not built)

- Super administrator screens (the role exists in the data model only)
- Doctor blocking their own time (admins can block slots)
- Password reset; phone or email verification; multi-factor sign-in
- SMS, WhatsApp and email notifications
- Data export and account deletion
- Admin audit log viewer and reports
- Payments, prescriptions, lab results, tele-consultation
- Integration with any real hospital system
- Automatic spoken-language detection
- Offline support, installable app

## Deviations from the approved Phase 1 plan

Listed with reasons in [ARCHITECTURE.md](ARCHITECTURE.md). In short: fewer frontend
libraries, string status columns, a create-all first migration, a unique index in place of
an exclusion constraint, and an in-memory rate limiter.

## Known limitations

1. **Never run.** The largest limitation. Budget time for a first-run debugging pass.
2. Provider facts (model names, free quotas, voice names) were read from documentation on
   20 November 2026 and partly could not be confirmed; see COST_AND_FREE_TIER.md.
3. Department suggestions, emergency phrases and intake questions are demonstration content
   and not clinically reviewed. The emergency phrase list will miss real emergencies.
4. Identity is not verified for anyone. Doctor credentials are not verified.
5. One time zone (Asia/Kolkata), one city, three simulated hospitals.
6. Single backend process assumed.
7. Not suitable for real patient data in any configuration delivered here.

## Suggested first steps on your machine

1. Follow README Quick start up to `alembic upgrade head`. Fix anything that fails.
2. `pytest tests/unit` (expected: 33 passed, as recorded in TESTING.md).
3. `pytest tests/integration` with `TEST_DATABASE_URL`. Failures here are the most useful
   list of real defects.
4. `npm install`, `npm run typecheck`, `npm test`, `npm run dev`.
5. Walk through DEMO.md.
