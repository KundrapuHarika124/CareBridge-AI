// Doctor's day: the list of appointments, and for each one the patient's answers, the
// patient-reviewed AI summary (if any), private notes, follow-up instructions and outcome.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { get, patch, post, put, query, type Appointment, type FollowUp, type Intake, type Note, type Summary } from "../api";
import { fmtDate, fmtTime, istDate } from "../lib/format";
import { Banner, Button, Card, Empty, ErrorPanel, Loading, PageTitle, StatusBadge, useAction, useLang, useLoad } from "../ui";
import { SUMMARY_KEYS } from "./AppointmentDetail";

export default function DoctorToday() {
  const { t } = useTranslation();
  const lang = useLang();
  const [day, setDay] = useState(() => istDate(new Date()));
  const [openId, setOpenId] = useState<string | null>(null);
  const reviewAction = useAction();
  const list = useLoad(() => get<Appointment[]>(`/doctor/appointments${query({ on_date: day })}`), [day]);
  const rows = list.data ?? [];

  return (
    <div>
      <PageTitle>{t("doctor.title")}</PageTitle>
      <div className="mb-4 max-w-xs">
        <label className="label" htmlFor="doctor-day">{t("doctor.date")}</label>
        <input id="doctor-day" type="date" className="input" value={day} onChange={(e) => { if (e.target.value) { setDay(e.target.value); setOpenId(null); } }} />
      </div>
      {reviewAction.error != null && <ErrorPanel error={reviewAction.error} />}
      {list.loading && <Loading />}
      {list.error != null && <ErrorPanel error={list.error} onRetry={list.reload} />}
      {!list.loading && list.error == null && rows.length === 0 && <Empty title={t("doctor.none")} />}
      <div className="space-y-3">
        {rows.map((appt) => (
          <Card key={appt.id}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-lg font-semibold">{fmtTime(appt.starts_at, lang)} · {appt.patient.full_name}</p>
                <p className="text-slate-700">{appt.hospital.name}</p>
                {appt.reason_text && <p>{t("appt.reason")}: {appt.reason_text}</p>}
              </div>
              <StatusBadge status={appt.status} />
            </div>
            {appt.status === "PENDING" ? (
              <div className="mt-3">
                <p className="mb-2 text-sm text-slate-700">{t("doctor.pendingHint")}</p>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={reviewAction.busy} onClick={async () => { const result = await reviewAction.run(() => post(`/doctor/appointments/${appt.id}/approve`)); if (result !== undefined) list.reload(); }}>{t("doctor.approveRequest")}</Button>
                  <Button variant="danger" disabled={reviewAction.busy} onClick={async () => { const result = await reviewAction.run(() => post(`/doctor/appointments/${appt.id}/reject`)); if (result !== undefined) list.reload(); }}>{t("doctor.rejectRequest")}</Button>
                </div>
              </div>
            ) : (
              <>
                <Button variant="secondary" className="mt-2" aria-expanded={openId === appt.id} onClick={() => setOpenId(openId === appt.id ? null : appt.id)}>
                  {openId === appt.id ? t("common.close") : t("doctor.open")}
                </Button>
                {openId === appt.id && <Visit appointment={appt} onChanged={list.reload} />}
              </>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Visit({ appointment, onChanged }: { appointment: Appointment; onChanged: () => void }) {
  const { t } = useTranslation();
  const lang = useLang();
  const base = `/appointments/${appointment.id}`;
  const data = useLoad(async () => {
    const [intake, summary, note, followUp] = await Promise.all([
      get<Intake>(`${base}/intake`),
      get<Summary | null>(`${base}/summary`),
      get<Note | null>(`${base}/notes`),
      get<FollowUp | null>(`${base}/follow-up`),
    ]);
    return { intake, summary, note, followUp };
  }, [appointment.id]);
  const action = useAction();
  const [noteText, setNoteText] = useState("");
  const [instructions, setInstructions] = useState("");
  const [nextVisit, setNextVisit] = useState("");
  const [correction, setCorrection] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (!data.data) return;
    setNoteText(data.data.note?.note_text ?? "");
    setInstructions(data.data.followUp?.instructions_text ?? "");
    setNextVisit(data.data.followUp?.next_visit_date ?? "");
    setCorrection(data.data.summary?.clinician_correction ?? "");
  }, [data.data]);

  if (data.loading) return <Loading />;
  if (data.error != null) return <ErrorPanel error={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  const { intake, summary } = data.data;
  const answered = intake.questionnaire?.questions.filter((q) => intake.answers[q.key]) ?? [];
  const open = appointment.status === "CONFIRMED" || appointment.status === "PENDING";

  const act = async (label: string, work: () => Promise<unknown>, reloadList = false) => {
    setSaved(null);
    const result = await action.run(work);
    if (result !== undefined) {
      setSaved(label);
      if (reloadList) onChanged();
      else data.reload();
    }
  };

  return (
    <div className="mt-4 space-y-5 border-t border-slate-200 pt-4">
      {action.error != null && <ErrorPanel error={action.error} />}
      {saved && <Banner kind="success">{saved}</Banner>}

      <section>
        <h3 className="mb-1 font-semibold">{t("doctor.patientAnswers")}</h3>
        <p className="mb-2 text-sm text-slate-700">{t("doctor.patientReported")}</p>
        {answered.length === 0 && <p>{t("intake.none")}</p>}
        {answered.map((q) => (
          <div key={q.key} className="mb-2">
            <p className="font-semibold">{lang === "te" ? q.text_te : q.text_en}</p>
            <p className="whitespace-pre-line">{intake.answers[q.key]}</p>
          </div>
        ))}
      </section>

      {summary && (
        <section>
          <h3 className="mb-1 font-semibold">
            {t("summary.title")} <span className="rounded bg-violet-100 px-2 py-0.5 text-sm text-violet-900">{t("summary.aiLabel")}</span>
          </h3>
          <p className="mb-2 text-sm text-slate-700">{t("doctor.summaryNote")}</p>
          {SUMMARY_KEYS.filter((key) => summary.content[key]).map((key) => (
            <div key={key} className="mb-2">
              <p className="font-semibold">{t(`summary.section.${key}`)}</p>
              <p className="whitespace-pre-line">{summary.content[key]}</p>
            </div>
          ))}
          <label className="label" htmlFor={`correction-${appointment.id}`}>{t("summary.correction")}</label>
          <textarea id={`correction-${appointment.id}`} className="input" rows={2} maxLength={4000} value={correction} onChange={(e) => setCorrection(e.target.value)} />
          <Button variant="secondary" className="mt-2" disabled={action.busy}
            onClick={() => act(t("common.savedMsg"), () => patch(`${base}/summary`, { clinician_correction: correction }))}>
            {t("doctor.saveCorrection")}
          </Button>
        </section>
      )}

      <section>
        <label className="label" htmlFor={`note-${appointment.id}`}>{t("doctor.notes")}</label>
        <p className="mb-1 text-sm text-slate-700">{t("doctor.notesPrivate")}</p>
        <textarea id={`note-${appointment.id}`} className="input" rows={4} maxLength={8000} value={noteText} onChange={(e) => setNoteText(e.target.value)} />
        <Button variant="secondary" className="mt-2" disabled={action.busy || !noteText.trim()}
          onClick={() => act(t("common.savedMsg"), () => put(`${base}/notes`, { note_text: noteText }))}>
          {t("doctor.saveNotes")}
        </Button>
      </section>

      <section>
        <label className="label" htmlFor={`follow-${appointment.id}`}>{t("followUp.title")}</label>
        <p className="mb-1 text-sm text-slate-700">{t("doctor.followUpVisible")}</p>
        <textarea id={`follow-${appointment.id}`} className="input" rows={3} maxLength={4000} value={instructions} onChange={(e) => setInstructions(e.target.value)} />
        <label className="label mt-2" htmlFor={`next-${appointment.id}`}>{t("followUp.nextVisit")}</label>
        <input id={`next-${appointment.id}`} type="date" className="input max-w-xs" value={nextVisit} onChange={(e) => setNextVisit(e.target.value)} />
        {nextVisit && <p className="text-sm text-slate-700">{fmtDate(`${nextVisit}T06:30:00Z`, lang)}</p>}
        <div>
          <Button variant="secondary" className="mt-2" disabled={action.busy || !instructions.trim()}
            onClick={() => act(t("common.savedMsg"), () => put(`${base}/follow-up`, { instructions_text: instructions, next_visit_date: nextVisit || null }))}>
            {t("doctor.saveFollowUp")}
          </Button>
        </div>
      </section>

      {open && (
        <section className="flex flex-wrap gap-2">
          <Button disabled={action.busy} onClick={() => act(t("common.savedMsg"), () => post(`${base}/complete`), true)}>{t("doctor.markCompleted")}</Button>
          <Button variant="secondary" disabled={action.busy} onClick={() => act(t("common.savedMsg"), () => post(`${base}/no-show`), true)}>{t("doctor.markNoShow")}</Button>
        </section>
      )}
    </div>
  );
}
