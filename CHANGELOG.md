# Changelog

## 0.1.0 (20 November 2026), first delivery, unverified

Written in one pass and delivered as a ZIP archive. No commits, deployments or releases
have been made.

Added
- Backend: authentication with rotating refresh tokens, role and relationship based access
  control, hospital directory, slot generation, booking with idempotency and row locking,
  cancel, reschedule, waiting list with timed offers, caregiver consent and permissions,
  pre-visit questions, AI summary with patient release gate, doctor notes and follow-up,
  in-app notifications, audit log, assistant state machine with guided fallback, speech
  token endpoint, hospital administration, background jobs, seed script, one migration.
- Frontend: sign in and registration, patient and caregiver home, assistant, step-by-step
  booking, appointments, appointment detail, caregiver management, doctor day view,
  hospital administration, notifications, settings, Telugu and English text.
- Tests: 33 unit tests (executed, passing), 51 integration tests (not executed),
  2 frontend test files (not executed under Vitest).
- Documentation set under `docs/`.

Not done
- The application has not been run. See docs/TESTING.md and docs/STATUS.md.
- No dependency lockfiles (`package-lock.json`, pinned transitive Python hashes).
