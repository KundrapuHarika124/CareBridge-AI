"""Background jobs run inside the single backend process.

On free hosting the process sleeps when idle, so these jobs are best effort: reminders
and offer expiry can run late. See docs/STATUS.md (known limitations).
"""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from app.constants import APPT_CONFIRMED, PERM_RECEIVE_REMINDERS, REL_ACTIVE
from app.core.database import SessionLocal
from app.core.timeutil import to_utc_iso, utcnow
from app.models import (
    Appointment,
    AppointmentSlot,
    CaregiverPermission,
    CareRelationship,
    ConversationMessage,
    ConversationSession,
    RefreshToken,
)
from app.services import waitlist
from app.services.common import notify

log = logging.getLogger("carebridge.jobs")
TRANSCRIPT_RETENTION_DAYS = 30


def send_reminders(db) -> int:
    """One in-app reminder per confirmed appointment starting within the next 24 hours."""
    now = utcnow()
    due = db.scalars(
        select(Appointment)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .where(
            Appointment.status == APPT_CONFIRMED,
            Appointment.reminder_sent_at.is_(None),
            AppointmentSlot.starts_at > now,
            AppointmentSlot.starts_at <= now + timedelta(hours=24),
        )
    ).all()
    for appt in due:
        aff = appt.slot.affiliation
        caregivers = db.scalars(
            select(CareRelationship.caregiver_user_id)
            .join(CaregiverPermission, CaregiverPermission.relationship_id == CareRelationship.id)
            .where(
                CareRelationship.patient_id == appt.patient_id,
                CareRelationship.status == REL_ACTIVE,
                CaregiverPermission.permission == PERM_RECEIVE_REMINDERS,
            )
        ).all()
        notify(
            db,
            [appt.patient.user_id, *caregivers],
            "APPOINTMENT_REMINDER",
            {
                "appointment_id": str(appt.id),
                "patient_name": appt.patient.user.full_name,
                "doctor_name": aff.doctor.user.full_name,
                "hospital_name": aff.hospital.name,
                "starts_at": to_utc_iso(appt.slot.starts_at),
            },
        )
        appt.reminder_sent_at = now
    db.commit()
    return len(due)


def purge_old_data(db) -> None:
    """Retention: conversation text is kept 30 days; dead refresh tokens 30 days past expiry."""
    cutoff = utcnow() - timedelta(days=TRANSCRIPT_RETENTION_DAYS)
    old_sessions = select(ConversationSession.id).where(ConversationSession.expires_at < cutoff)
    db.execute(delete(ConversationMessage).where(ConversationMessage.session_id.in_(old_sessions)))
    db.execute(delete(ConversationSession).where(ConversationSession.expires_at < cutoff))
    db.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
    db.commit()


def run_once() -> dict:
    db = SessionLocal()
    try:
        expired = waitlist.expire_due(db)
        reminders = send_reminders(db)
        purge_old_data(db)
        return {"offers_expired": expired, "reminders_sent": reminders}
    finally:
        db.close()


async def loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            raise
        except Exception:  # a failed run must not stop future runs
            log.exception("background_job_failed")
        await asyncio.sleep(interval_seconds)
