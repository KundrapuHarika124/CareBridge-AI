# Security and privacy

This is a demonstration system for synthetic data. The controls below are written in the
code but have **not been tested by execution or reviewed by a security professional**.
Do not put real patient data in it.

## Controls

| Area | Control |
|---|---|
| Passwords | Argon2id. 8 to 128 characters, not all digits or all letters |
| Sessions | 15-minute access token in memory. Refresh token in an HttpOnly, SameSite=Lax cookie scoped to `/api/v1/auth`, `Secure` in production, stored hashed, rotated every use, family revoked on reuse |
| Cross-site requests | Bearer token for API calls; the cookie-only refresh endpoint also requires a custom header |
| Authorization | Checked in the service layer for every patient-scoped read and write. Caregiver permissions are read from the database on every request, so revocation is immediate |
| Tenant isolation | Admin endpoints carry a hospital id and verify membership; appointments are joined through the hospital |
| Enumeration | Out-of-scope records return 404. Caregiver requests always return 202. Login errors do not say which part was wrong |
| Rate limits | Login: 5 failures per identifier and 30 per address in 15 minutes. Registration, assistant turns, speech tokens and caregiver requests are limited per hour |
| Input | Pydantic validation with length limits on every body |
| Data minimisation | Admins never receive reason text, answers, summaries or notes. Caregivers receive reason text and answers only with the matching permission |
| Audit | Bookings, changes, consent events, caregiver reads of intake and follow-up, password changes |
| Secrets | Environment variables only. The backend refuses to start with a short JWT secret, or with mock providers in production |
| Headers | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on API responses |
| Logs | JSON, with request id. No passwords, tokens, prompts or message bodies |
| Third parties | Audio goes only to Azure Speech. Text goes to Gemini only if configured. No analytics or trackers |

## Known gaps

- Rate limits are in memory: they reset on restart and are per process.
- No account lockout notification, no multi-factor sign-in, no email or phone verification.
  Anyone can register with any unused phone number or email.
- No password reset flow.
- No Content-Security-Policy is configured on the static host.
- No encryption beyond what the database host provides at rest and TLS in transit.
- No data export or account deletion feature.
- Free-plan Supabase has no automatic backups.
- Dependencies are pinned in `requirements.txt` but there are no lockfiles and no
  vulnerability scan has been run.
- The seed creates accounts with a shared, published demo password.

## Privacy position

- Synthetic data only. The UI says so on every screen and at registration.
- India's Digital Personal Data Protection Act 2023 and Rules 2025 would apply to any real
  use. Consent records here are a design aid, not a compliance claim. Legal review would be
  needed before handling real personal data, as would paid provider tiers with
  no-training terms, verified identity, and clinical review of all health-related content.

## Before publishing the repository

```bash
git grep -nIE "(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{12,}" -- . ':!docs' ':!*.example'
```

Confirm `.env` files are not tracked (`git status --ignored`). A scan run before delivery is
recorded in TESTING.md.
