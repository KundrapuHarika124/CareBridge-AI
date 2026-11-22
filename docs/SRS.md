# Software Requirements Specification

Version 0.1, 20 November 2026. Scope: a demonstration system using synthetic data only.

## 1. Purpose

Help a person, or a family member acting for them, arrange an outpatient appointment in
Telugu or English without needing to read dense screens or know which department to ask for.

## 2. Users

| User | Goal | Constraints assumed |
|---|---|---|
| Patient | Book and manage own appointments | May be older, may prefer Telugu, may prefer speaking to typing, small phone screen |
| Caregiver | Arrange appointments for a relative | Acts only with the patient's recorded consent |
| Doctor | See the day's patients and what they reported | Little time per patient |
| Hospital administrator | Keep doctors, hours and slots current | Works at one hospital |
| Super administrator | Platform oversight | Role exists in the data model; no screens (planned) |

## 3. Functional requirements

Status values: **I** implemented in code but unverified, **P** partial, **N** not built.

| ID | Requirement | Status |
|---|---|---|
| F1 | Register and sign in with a 10-digit Indian mobile number or an email, and a password | I |
| F2 | Sessions renew without re-entering the password; sign out; change password | I |
| F3 | Role-based access for patient, caregiver, doctor, hospital admin | I |
| F4 | List specialties, hospitals, localities and doctors with next free times | I |
| F5 | Suggest a department from a described concern, labelled as not a diagnosis | I |
| F6 | Book a free slot; two people can never hold the same slot | I |
| F7 | Cancel and reschedule; the old slot becomes free again | I |
| F8 | Join a waiting list; a freed slot is offered to the first person for 30 minutes | I |
| F9 | Caregiver requests access; patient approves chosen permissions, edits, revokes; every step recorded | I |
| F10 | Pre-visit questions answered by the patient | I |
| F11 | AI summary of the patient's own answers, shown to others only after the patient approves it | I, needs a Gemini key |
| F12 | Doctor's private notes and patient-visible follow-up instructions | I |
| F13 | Doctor marks an appointment completed or not attended | I |
| F14 | Admin manages departments, doctors, weekly hours, slots; cancels with a reason | I |
| F15 | In-app notifications for bookings, changes, reminders, caregiver events, offers | I |
| F16 | Conversational assistant in Telugu and English that books only after explicit confirmation | I |
| F17 | Voice input and spoken replies | I, needs an Azure Speech key |
| F18 | Every assistant function has a typed or button alternative | I |
| F19 | Reminder about 24 hours before an appointment | P, in-app only and only while the server is awake |
| F20 | SMS, WhatsApp or email notifications | N |
| F21 | Password reset by email or SMS | N |
| F22 | Doctor blocks own time | N (admin can block slots) |
| F23 | Super administrator screens | N |
| F24 | Payments, prescriptions, lab results, tele-consultation, real hospital system integration | N, out of scope |

## 4. Non-functional requirements

| ID | Requirement | How it is addressed |
|---|---|---|
| N1 | Zero mandatory cost | Runs with no external account; optional providers have free tiers; no automatic paid fallback |
| N2 | Works when AI or voice is down | Guided mode and manual booking need neither |
| N3 | No double booking under concurrency | Row lock on the slot plus a partial unique index |
| N4 | Privacy by default | Out-of-scope records return "not found"; admins never see clinical text; caregivers see only what was granted |
| N5 | Accessibility | Labels on every field, visible focus, status shown as words, 48 px targets, larger text for patients. Not audited (see STATUS) |
| N6 | Bilingual | Every UI string exists in Telugu and English; a check enforces identical keys |
| N7 | Time zones | Stored in UTC, shown in Asia/Kolkata |
| N8 | Observability | JSON logs with a request id returned to the user on errors |
| N9 | No secrets in the repository | Example env files contain placeholders only |

## 5. Safety requirements

- The assistant never diagnoses, never recommends medicine, and says so when asked.
- Phrases that suggest an emergency stop the booking flow and show emergency numbers (112, 108).
- All clinical-adjacent content (department suggestions, intake questions) is labelled as
  demonstration content not reviewed by a clinician.
- The assistant never states that an appointment is booked unless the booking transaction committed.

## 6. Assumptions

- One time zone (India). One city (Hyderabad). Three simulated hospitals.
- A caregiver is an adult known to the patient; identity is not verified.
- Doctor credentials are not verified; seeded doctors are marked `SYNTHETIC`.
