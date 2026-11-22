import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { del, get, post, query, type Appointment, type WaitEntry, type WaitOffer } from "../api";
import { can, useAuth } from "../auth";
import { fmtDateTime } from "../lib/format";
import { Banner, Button, Card, Empty, ErrorPanel, Loading, Modal, PageTitle, SimTag, StatusBadge, useAction, useLang, useLoad } from "../ui";

export function CancelDialog({ appointment, onClose, onDone, adminPath }: {
  appointment: Appointment; onClose: () => void; onDone: () => void; adminPath?: string;
}) {
  const { t } = useTranslation();
  const lang = useLang();
  const { run, busy, error } = useAction();
  const [reason, setReason] = useState("");
  const needReason = !!adminPath;
  const submit = async () => {
    const result = await run(() => post(adminPath ?? `/appointments/${appointment.id}/cancel`, { reason: reason.trim() || null }));
    if (result) onDone();
  };
  return (
    <Modal title={t("appt.cancelTitle")} onClose={onClose}>
      {error != null && <ErrorPanel error={error} />}
      <p>{appointment.patient.full_name}</p>
      <p>{appointment.doctor_name}</p>
      <p className="mb-3 font-semibold">{fmtDateTime(appointment.starts_at, lang)}</p>
      <label className="label" htmlFor="cancel-reason">{needReason ? t("appt.reasonRequired") : t("appt.reasonOptional")}</label>
      <input id="cancel-reason" className="input mb-4" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button variant="danger" onClick={submit} disabled={busy || (needReason && !reason.trim())}>
          {busy ? t("common.pleaseWait") : t("appt.confirmCancel")}
        </Button>
        <Button variant="secondary" onClick={onClose} disabled={busy}>{t("appt.keep")}</Button>
      </div>
    </Modal>
  );
}

export default function Appointments() {
  const { t } = useTranslation();
  const lang = useLang();
  const navigate = useNavigate();
  const { user, activePatient } = useAuth();
  const [scope, setScope] = useState<"upcoming" | "past">("upcoming");
  const [cancelling, setCancelling] = useState<Appointment | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const offerAction = useAction();

  const canView = can(activePatient, "VIEW_APPOINTMENTS");
  const canBook = can(activePatient, "BOOK_APPOINTMENTS");
  const list = useLoad(
    () => (activePatient && canView ? get<Appointment[]>(`/appointments${query({ patient_id: activePatient.id, scope })}`) : Promise.resolve([])),
    [activePatient?.id, scope, canView],
  );
  const waiting = useLoad(
    () =>
      activePatient && canBook
        ? get<{ entries: WaitEntry[]; offers: WaitOffer[] }>(`/waiting-list${query({ patient_id: activePatient.id })}`)
        : Promise.resolve({ entries: [], offers: [] }),
    [activePatient?.id, canBook],
  );

  if (user?.role === "CAREGIVER" && !activePatient) {
    return <Empty title={t("care.choosePatientFirst")}><Link className="btn btn-primary" to="/patients">{t("nav.patients")}</Link></Empty>;
  }
  if (!canView) return <Banner kind="warning">{t("care.noViewPermission")}</Banner>;

  const answerOffer = async (offer: WaitOffer, accept: boolean) => {
    const result = await offerAction.run(() => post(`/waiting-list/offers/${offer.id}/${accept ? "accept" : "decline"}`));
    if (result) {
      setNotice(accept ? t("wait.accepted") : t("wait.declined"));
      list.reload();
    }
    waiting.reload();
  };
  const leave = async (entry: WaitEntry) => {
    await offerAction.run(() => del(`/waiting-list/${entry.id}`));
    waiting.reload();
  };

  const tab = (value: "upcoming" | "past", label: string) => (
    <button type="button" role="tab" aria-selected={scope === value} onClick={() => setScope(value)}
      className={`min-h-[3rem] flex-1 rounded-lg px-4 py-2 font-semibold ${scope === value ? "bg-brand-600 text-white" : "bg-white text-slate-800 border border-slate-300"}`}>
      {label}
    </button>
  );

  return (
    <div>
      <PageTitle action={canBook ? <Link to="/book" className="btn btn-primary">{t("book.title")}</Link> : undefined}>{t("nav.appointments")}</PageTitle>
      {notice && <Banner kind="success">{notice}</Banner>}
      {offerAction.error != null && <ErrorPanel error={offerAction.error} />}

      {(waiting.data?.offers ?? []).map((offer) => (
        <Card key={offer.id} className="mb-4 border-2 border-amber-400">
          <h2 className="mb-1">{t("wait.offerTitle")}</h2>
          <p>{offer.doctor_name}, {offer.hospital_name}</p>
          <p className="text-xl font-semibold">{fmtDateTime(offer.slot.starts_at, lang)}</p>
          <p className="text-sm text-slate-700">{t("wait.offerExpires", { when: fmtDateTime(offer.expires_at, lang) })}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button disabled={offerAction.busy} onClick={() => answerOffer(offer, true)}>{t("wait.accept")}</Button>
            <Button variant="secondary" disabled={offerAction.busy} onClick={() => answerOffer(offer, false)}>{t("wait.decline")}</Button>
          </div>
        </Card>
      ))}

      <div role="tablist" aria-label={t("nav.appointments")} className="mb-4 flex gap-2">
        {tab("upcoming", t("appt.upcoming"))}
        {tab("past", t("appt.past"))}
      </div>

      {list.loading && <Loading />}
      {list.error != null && <ErrorPanel error={list.error} onRetry={list.reload} />}
      {!list.loading && list.error == null && (list.data ?? []).length === 0 && (
        <Empty title={scope === "upcoming" ? t("home.noUpcoming") : t("appt.noPast")} />
      )}
      <div className="space-y-3">
        {(list.data ?? []).map((appt) => {
          const open = appt.status === "CONFIRMED" || appt.status === "PENDING";
          const future = new Date(appt.starts_at).getTime() > Date.now();
          return (
            <Card key={appt.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="text-xl font-semibold">{fmtDateTime(appt.starts_at, lang)}</p>
                <StatusBadge status={appt.status} />
              </div>
              <p>{appt.doctor_name}</p>
              <p>{appt.hospital.name}, {appt.hospital.locality}{appt.hospital.is_simulated && <SimTag />}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to={`/appointments/${appt.id}`} className="btn btn-secondary">{t("appt.details")}</Link>
                {open && future && can(activePatient, "RESCHEDULE_APPOINTMENTS") && (
                  <Button variant="secondary" onClick={() => navigate(`/book${query({ reschedule: appt.id, specialty: appt.specialty.id })}`)}>{t("appt.reschedule")}</Button>
                )}
                {open && future && can(activePatient, "CANCEL_APPOINTMENTS") && (
                  <Button variant="danger" onClick={() => setCancelling(appt)}>{t("appt.cancel")}</Button>
                )}
              </div>
            </Card>
          );
        })}
      </div>

      {(waiting.data?.entries ?? []).length > 0 && (
        <section className="mt-6" aria-labelledby="waiting-title">
          <h2 id="waiting-title" className="mb-2">{t("wait.title")}</h2>
          <div className="space-y-3">
            {(waiting.data?.entries ?? []).map((entry) => (
              <Card key={entry.id}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="font-semibold">{entry.doctor.doctor_name}</p>
                  <StatusBadge status={entry.status} />
                </div>
                <p>{entry.doctor.hospital.name}, {entry.doctor.hospital.locality}</p>
                <Button variant="secondary" className="mt-3" disabled={offerAction.busy} onClick={() => leave(entry)}>{t("wait.leave")}</Button>
              </Card>
            ))}
          </div>
        </section>
      )}

      {cancelling && (
        <CancelDialog appointment={cancelling} onClose={() => setCancelling(null)}
          onDone={() => { setCancelling(null); setNotice(t("appt.cancelled")); list.reload(); }} />
      )}
    </div>
  );
}
