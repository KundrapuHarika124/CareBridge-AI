# Demo walkthrough

A script for showing the system once it runs locally with seed data. About 10 minutes.
Passwords: the seed password (`Demo@12345` unless you changed `SEED_PASSWORD`).

These steps describe intended behaviour. They have not been performed against a running copy.

1. **Patient, Telugu, step-by-step booking.** Sign in as `9000000001`. The interface is in
   Telugu with larger text. Home shows the seeded appointment. Choose "Book step by step",
   pick "Knee, joint, back or bone pain", an area, a doctor and time, check the details, confirm.
2. **Assistant in guided mode.** Open the assistant. With no AI key, the banner says guided
   mode. Type `mokali noppi` or press the buttons. Choose area and time. Note that nothing is
   booked until the confirmation card is confirmed.
3. **Safety.** In the assistant type `chest pain`. Booking pauses and emergency numbers are
   shown. Start again and ask `which tablet should I take`: it declines and offers to book.
4. **Double booking.** In two browsers (patient 1 and `patient2@carebridge.demo`) reach the
   confirm step for the same time. Confirm in both. The second sees "That time has just been
   taken" and is sent back to choose another.
5. **Caregiver consent.** Sign in as `patient2@carebridge.demo`. Home shows a caregiver
   request. Open "My caregivers", review, untick some permissions, approve. Sign in as
   `caregiver@carebridge.demo`, open "People I help", act for each patient, and note that
   buttons you were not granted are absent. As the patient, remove access; the caregiver's
   next action fails.
6. **Before the visit.** As patient 1 open the seeded appointment, edit the answers, save.
   Without an AI key, "Create summary" reports that the AI summary is unavailable and that
   the answers are saved.
7. **Doctor.** Sign in as `doctor1@carebridge.demo`. Open the visit: patient-reported
   answers, private notes, follow-up instructions, mark completed. Back as the patient, the
   follow-up appears with a notification.
8. **Waiting list.** As admin of Hospital A, block a doctor's remaining slots for a day, or
   book them, so a doctor shows no free times. As patient 2 join the waiting list. As
   patient 1 cancel an appointment with that doctor. Patient 2 sees an offer held for 30 minutes.
9. **Hospital admin.** Sign in as `admin.a@carebridge.demo`: overview counts, add a
   department, add a doctor, add weekly hours, create times, block a slot, cancel an
   appointment with a reason. Note the appointment list shows no reasons for visits.
10. **Tenant isolation.** As `admin.a`, call
    `/api/v1/admin/hospitals/<hospital B id>/doctors` from the API docs page: 404.
11. **With keys (optional).** Set Gemini and Azure variables, restart. The guided banner
    disappears, free sentences such as "రేపు ఉదయం కూకట్‌పల్లిలో మోకాలి నొప్పికి డాక్టర్ కావాలి"
    are understood, the microphone button appears, and summaries can be created.
