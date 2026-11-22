"""Waiting list.

Policy (transparent, first come first served):
- Entries are per patient and per doctor-at-hospital (affiliation).
- When a future slot of that affiliation is released, the oldest ACTIVE entry that has not
  already been offered this slot receives an offer and the slot is HELD for 30 minutes.
- Accepting books the slot through the normal booking service. Declining or letting the
  offer expire returns the entry to the list and passes the slot to the next entry, or
  back to general availability when nobody is left.
"""
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import (
    OFFER_ACCEPTED,
    OFFER_DECLINED,
    OFFER_EXPIRED,
    OFFER_MINUTES,
    OFFER_OPEN,
    SLOT_AVAILABLE,
    SLOT_HELD,
    WAIT_ACTIVE,
    WAIT_CANCELLED,
    WAIT_FULFILLED,
    WAIT_OFFERED,
)
from app.core import errors
from app.core.timeutil import to_utc_iso, utcnow
from app.models import Affiliation, AppointmentSlot, Hospital, Patient, User, WaitingListEntry, WaitingListOffer
from app.services.common import audit, notify


def _lock_hospital(db: Session, hospital_id: uuid.UUID) -> Hospital:
    hospital = db.execute(
        select(Hospital)
        .where(Hospital.id == hospital_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if hospital is None:
        db.rollback()
        raise errors.not_found("Hospital")
    return hospital


def join(db: Session, *, actor: User, patient: Patient, affiliation_id: uuid.UUID, request_id=None) -> WaitingListEntry:
    aff = db.get(Affiliation, affiliation_id)
    if aff is None or not aff.is_active:
        raise errors.not_found("Doctor")
    hospital = _lock_hospital(db, aff.hospital_id)
    if not hospital.is_approved:
        db.rollback()
        raise errors.not_found("Hospital")
    open_entry = db.scalar(
        select(WaitingListEntry).where(
            WaitingListEntry.patient_id == patient.id,
            WaitingListEntry.affiliation_id == affiliation_id,
            WaitingListEntry.status.in_((WAIT_ACTIVE, WAIT_OFFERED)),
        ).with_for_update()
    )
    if open_entry:
        return open_entry
    entry = WaitingListEntry(patient_id=patient.id, affiliation_id=affiliation_id, created_by_user_id=actor.id)
    db.add(entry)
    db.flush()
    audit(db, actor_id=actor.id, action="WAITLIST_JOINED", entity_type="waiting_list_entry", entity_id=entry.id,
          hospital_id=aff.hospital_id, request_id=request_id)
    db.commit()
    return entry


def leave(db: Session, *, actor: User, entry: WaitingListEntry, request_id=None) -> None:
    offers = list(db.scalars(
        select(WaitingListOffer).where(WaitingListOffer.entry_id == entry.id, WaitingListOffer.status == OFFER_OPEN)
    ))
    if offers:
        offer_resources = []
        for offer in offers:
            slot = db.get(AppointmentSlot, offer.slot_id)
            if slot is None:
                continue
            offer_resources.append((slot.affiliation.hospital_id, slot.id, offer.id, entry.id))

        hospital_ids = sorted({resource[0] for resource in offer_resources}, key=str)
        slot_ids = sorted({resource[1] for resource in offer_resources}, key=str)
        offer_ids = sorted({resource[2] for resource in offer_resources}, key=str)
        entry_ids = sorted({resource[3] for resource in offer_resources}, key=str)

        for hospital_id in hospital_ids:
            _lock_hospital(db, hospital_id)
        for slot_id in slot_ids:
            db.execute(
                select(AppointmentSlot)
                .where(AppointmentSlot.id == slot_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
        for offer_id in offer_ids:
            db.execute(
                select(WaitingListOffer)
                .where(WaitingListOffer.id == offer_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
        for entry_id in entry_ids:
            db.execute(
                select(WaitingListEntry)
                .where(WaitingListEntry.id == entry_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()

    for offer in sorted(offers, key=lambda item: str(item.id)):
        _release(db, offer, OFFER_DECLINED)
    entry = db.execute(
        select(WaitingListEntry)
        .where(WaitingListEntry.id == entry.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if entry is None:
        raise errors.not_found("Waiting list entry")
    entry.status = WAIT_CANCELLED
    audit(db, actor_id=actor.id, action="WAITLIST_LEFT", entity_type="waiting_list_entry", entity_id=entry.id,
          request_id=request_id)
    db.commit()


def offer_slot(
    db: Session,
    slot: AppointmentSlot,
    *,
    hospital_locked: bool = False,
    slot_locked: bool = False,
) -> WaitingListOffer | None:
    """Offer a just-released slot to the next waiting patient. Does not commit.

    The caller must hold the row lock on `slot` and have set it to AVAILABLE.
    """
    if slot.status != SLOT_AVAILABLE or slot.starts_at <= utcnow():
        return None
    if not hospital_locked:
        hospital = _lock_hospital(db, slot.affiliation.hospital_id)
    else:
        hospital = db.get(Hospital, slot.affiliation.hospital_id)
    if not slot_locked:
        slot = db.execute(
            select(AppointmentSlot)
            .where(AppointmentSlot.id == slot.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if slot is None:
            return None
    if not hospital.is_approved:
        return None
    already_offered = select(WaitingListOffer.entry_id).where(WaitingListOffer.slot_id == slot.id)
    db.scalars(
        select(WaitingListOffer)
        .where(WaitingListOffer.slot_id == slot.id)
        .order_by(WaitingListOffer.id)
        .with_for_update()
    ).all()
    entry = db.execute(
        select(WaitingListEntry)
        .where(
            WaitingListEntry.affiliation_id == slot.affiliation_id,
            WaitingListEntry.status == WAIT_ACTIVE,
            WaitingListEntry.id.not_in(already_offered),
        )
        .order_by(WaitingListEntry.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if entry is None:
        return None
    offer = WaitingListOffer(
        entry_id=entry.id,
        slot_id=slot.id,
        status=OFFER_OPEN,
        expires_at=min(utcnow() + timedelta(minutes=OFFER_MINUTES), slot.starts_at),
    )
    entry.status = WAIT_OFFERED
    slot.status = SLOT_HELD
    db.add(offer)
    db.flush()
    aff = slot.affiliation
    notify(
        db,
        [entry.patient.user_id, entry.created_by_user_id],
        "WAITLIST_OFFER",
        {
            "offer_id": str(offer.id),
            "patient_name": entry.patient.user.full_name,
            "doctor_name": aff.doctor.user.full_name,
            "hospital_name": aff.hospital.name,
            "starts_at": to_utc_iso(slot.starts_at),
            "expires_at": to_utc_iso(offer.expires_at),
        },
    )
    return offer


def _release(db: Session, offer: WaitingListOffer, new_status: str) -> None:
    """Close an open offer without booking and pass the slot on. Does not commit."""
    entry_id = offer.entry_id
    slot_id = offer.slot_id

    slot = db.get(AppointmentSlot, slot_id)
    if slot is None:
        return
    hospital = _lock_hospital(db, slot.affiliation.hospital_id)
    if not hospital.is_approved:
        return
    slot = db.execute(
        select(AppointmentSlot)
        .where(AppointmentSlot.id == slot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if slot is None:
        return
    offer = db.execute(
        select(WaitingListOffer)
        .where(WaitingListOffer.id == offer.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if offer is None or offer.status == OFFER_ACCEPTED:
        return
    entry = db.execute(
        select(WaitingListEntry)
        .where(WaitingListEntry.id == entry_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if entry is None:
        return

    offer.status = new_status
    if entry.status == WAIT_OFFERED:
        entry.status = WAIT_ACTIVE
    db.flush()
    if slot.status == SLOT_HELD:
        slot.status = SLOT_AVAILABLE
        offer_slot(db, slot, hospital_locked=True, slot_locked=True)


def _lock_offer(db: Session, offer_id: uuid.UUID) -> WaitingListOffer | None:
    return db.execute(
        select(WaitingListOffer)
        .where(WaitingListOffer.id == offer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def accept(db: Session, *, actor: User, offer_id: uuid.UUID, idempotency_key=None, request_id=None):
    """Accept an offer. Returns the new appointment. Authorization is done by the caller."""
    from app.services import booking

    offer = db.get(WaitingListOffer, offer_id)
    if offer is None:
        raise errors.not_found("Offer")
    entry = db.get(WaitingListEntry, offer.entry_id)
    slot = db.get(AppointmentSlot, offer.slot_id)
    if entry is None or slot is None:
        raise errors.not_found("Offer")

    hospital = _lock_hospital(db, slot.affiliation.hospital_id)
    if not hospital.is_approved:
        db.rollback()
        raise errors.not_found("Hospital")
    slot = db.execute(
        select(AppointmentSlot)
        .where(AppointmentSlot.id == offer.slot_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    offer = db.execute(
        select(WaitingListOffer)
        .where(WaitingListOffer.id == offer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    entry = db.execute(
        select(WaitingListEntry)
        .where(WaitingListEntry.id == offer.entry_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if slot is None or offer is None or entry is None:
        db.rollback()
        raise errors.not_found("Offer")

    if offer.status == OFFER_OPEN and offer.expires_at <= utcnow():
        _release(db, offer, OFFER_EXPIRED)
        db.commit()
        raise errors.conflict("OFFER_NOT_OPEN", "This offer has expired.")
    if offer.status != OFFER_OPEN:
        db.rollback()
        raise errors.conflict("OFFER_NOT_OPEN", "This offer is no longer open.")
    offer.status = OFFER_ACCEPTED
    entry.status = WAIT_FULFILLED
    # book() commits; the offer and entry changes above commit with it or not at all.
    return booking.book(
        db,
        actor=actor,
        patient=entry.patient,
        slot_id=offer.slot_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        held_offer=True,
        hospital_locked=True,
        slot_locked=True,
    )


def decline(db: Session, *, actor: User, offer_id: uuid.UUID, request_id=None) -> None:
    offer = db.get(WaitingListOffer, offer_id)
    if offer is None:
        raise errors.not_found("Offer")
    entry = db.get(WaitingListEntry, offer.entry_id)
    slot = db.get(AppointmentSlot, offer.slot_id)
    if entry is None or slot is None:
        raise errors.not_found("Offer")
    hospital = _lock_hospital(db, slot.affiliation.hospital_id)
    if not hospital.is_approved:
        db.rollback()
        raise errors.not_found("Hospital")
    slot = db.execute(
        select(AppointmentSlot).where(AppointmentSlot.id == offer.slot_id).with_for_update()
    ).scalar_one_or_none()
    offer = db.execute(
        select(WaitingListOffer).where(WaitingListOffer.id == offer_id).with_for_update()
    ).scalar_one_or_none()
    entry = db.execute(
        select(WaitingListEntry).where(WaitingListEntry.id == offer.entry_id).with_for_update()
    ).scalar_one_or_none()
    if slot is None or offer is None or entry is None:
        db.rollback()
        raise errors.not_found("Offer")
    if offer.status != OFFER_OPEN:
        db.rollback()
        raise errors.conflict("OFFER_NOT_OPEN", "This offer is no longer open.")
    _release(db, offer, OFFER_DECLINED)
    audit(db, actor_id=actor.id, action="WAITLIST_OFFER_DECLINED", entity_type="waiting_list_offer",
          entity_id=offer.id, request_id=request_id)
    db.commit()


def cleanup_rejected_hospital(
   db: Session,
   hospital_id: uuid.UUID,
   *,
   hospital_locked: bool = False,
) -> dict[str, int]:
   """Invalidate waiting offers and return HELD slots for one rejected hospital."""
   if not hospital_locked:
       hospital = _lock_hospital(db, hospital_id)
       if hospital.is_approved:
           return {"offers": 0, "entries": 0, "slots": 0}

   rows = list(
       db.execute(
           select(
               WaitingListOffer.id.label("offer_id"),
               WaitingListOffer.entry_id,
               WaitingListOffer.slot_id,
           )
           .join(WaitingListEntry, WaitingListEntry.id == WaitingListOffer.entry_id)
           .join(Affiliation, Affiliation.id == WaitingListEntry.affiliation_id)
           .where(
               Affiliation.hospital_id == hospital_id,
               WaitingListOffer.status == OFFER_OPEN,
           )
           .order_by(WaitingListOffer.slot_id, WaitingListOffer.id)
       ).all()
   )
   if not rows:
       return {"offers": 0, "entries": 0, "slots": 0}

   slot_ids = sorted({row.slot_id for row in rows}, key=str)
   offer_ids = sorted({row.offer_id for row in rows}, key=str)
   entry_ids = sorted({row.entry_id for row in rows}, key=str)

   slots = []
   for slot_id in slot_ids:
       slot = db.execute(
           select(AppointmentSlot)
           .where(AppointmentSlot.id == slot_id)
           .with_for_update()
           .execution_options(populate_existing=True)
       ).scalar_one_or_none()
       if slot is not None:
           slots.append(slot)

   offers = []
   for offer_id in offer_ids:
       offer = db.execute(
           select(WaitingListOffer)
           .where(WaitingListOffer.id == offer_id)
           .with_for_update()
           .execution_options(populate_existing=True)
       ).scalar_one_or_none()
       if offer is not None and offer.status == OFFER_OPEN:
           offers.append(offer)

   entries = []
   for entry_id in entry_ids:
       entry = db.execute(
           select(WaitingListEntry)
           .where(WaitingListEntry.id == entry_id)
           .with_for_update()
           .execution_options(populate_existing=True)
       ).scalar_one_or_none()
       if entry is not None:
           entries.append(entry)

   released_slots = 0
   for offer in offers:
       offer.status = OFFER_EXPIRED
   for entry in entries:
       if entry.status == WAIT_OFFERED:
           entry.status = WAIT_CANCELLED
   for slot in slots:
       if slot.status == SLOT_HELD:
           slot.status = SLOT_AVAILABLE
           released_slots += 1

   return {
       "offers": len(offers),
       "entries": len(entries),
       "slots": released_slots,
   }


def expire_due(db: Session) -> int:
    """Expire offers past their deadline. Called by the background job."""
    due = list(
        db.execute(
            select(WaitingListOffer.id, Affiliation.hospital_id, WaitingListOffer.slot_id)
            .join(WaitingListEntry, WaitingListEntry.id == WaitingListOffer.entry_id)
            .join(Affiliation, Affiliation.id == WaitingListEntry.affiliation_id)
            .where(
                WaitingListOffer.status == OFFER_OPEN,
                WaitingListOffer.expires_at <= utcnow(),
            )
            .order_by(Affiliation.hospital_id, WaitingListOffer.slot_id, WaitingListOffer.id)
        ).all()
    )
    count = 0
    for offer_id, _hospital_id, _slot_id in due:
        offer = db.get(WaitingListOffer, offer_id)
        if offer is None:
            continue
        entry = db.get(WaitingListEntry, offer.entry_id)
        slot = db.get(AppointmentSlot, offer.slot_id)
        if entry is None or slot is None:
            continue
        hospital = _lock_hospital(db, slot.affiliation.hospital_id)
        if not hospital.is_approved:
            continue
        slot = db.execute(
            select(AppointmentSlot).where(AppointmentSlot.id == offer.slot_id).with_for_update()
        ).scalar_one_or_none()
        offer = db.execute(
            select(WaitingListOffer).where(WaitingListOffer.id == offer_id).with_for_update()
        ).scalar_one_or_none()
        entry = db.execute(
            select(WaitingListEntry).where(WaitingListEntry.id == offer.entry_id).with_for_update()
        ).scalar_one_or_none()
        if offer is not None and entry is not None and slot is not None and offer.status == OFFER_OPEN:
            _release(db, offer, OFFER_EXPIRED)
            count += 1
        db.commit()
    return count
