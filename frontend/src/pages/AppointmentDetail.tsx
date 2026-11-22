// One appointment: details, questions before the visit, the optional AI summary of the
// patient's own answers, and the doctor's follow-up instructions.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get, patch, post, put, query, type Appointment, type FollowUp, type Intake, type Summary } from "../api";
import { fmtDate, fmtDateTime, pickName, rupees } from "../lib/format";
import { Banner, Button, Card, ErrorPanel, Loading, PageTitle, SimTag, StatusBadge, useAction, useLang, useLoad } from "../ui";
import { CancelDialog } from "./Appointments";

export const SUMMARY_KEYS = ["reason_for_visit", "concerns", "duration", "other_information", "questions_for_doctor", "unclear_or_missing"] as const;

export default function AppointmentDetail() {
  const { id } = useParams();
  const { t } = useTranslation();
  const lang = useLang();
  const navigate = useNavigate();
  const [cancelling, setCancelling] = useState(false);
  const { data: appt, error, loading, reload } = useLoad(() => get<Appointment>(`/appointments/${id}`), [id]);

  if (loading) return <Loading />;
  if (error != null) return <ErrorPanel error={error} onRetry={reload} />;
  if (!appt) return null;

  const self = appt.viewer === "SELF";
  const allowed = (permission: string) => self || (appt.caregiver_permissions ?? []).includes(permission);
  const open = appt.status === "CONFIRMED" || appt.status === "PENDING";
  const future = new Date(appt.starts_at).getTime() > Date.now();

  return (
    <div>
      <PageTitle action={<Link to="/appointments" className="btn btn-secondary">{t("common.back")}</Link>}>{t("appt.details")}</PageTitle>
      <Card className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-xl font-semibold">{fmtDateTime(appt.starts_at, lang)}</p>
          <StatusBadge status={appt.status} />
        </div>
        <dl className="mt-2 space-y-1">
          <div><dt className="inline font-semibold">{t("appt.patient")}: </dt><dd className="inline">{appt.patient.full_name}</dd></div>
          <div><dt className="inline font-semibold">{t("appt.doctor")}: </dt><dd className="inline">{appt.doctor_name}, {pickName(appt.specialty, lang)}</dd></div>
          <div>
            <dt className="inline font-semibold">{t("appt.hospital")}: </dt>
            <dd className="inline">{appt.hospital.name}, {appt.hospital.address}{appt.hospital.is_simulated && <SimTag />}</dd>
          </div>
          {appt.consultation_fee !== null && <div><dt className="inline font-semibold">{t("book.fee")}: </dt><dd className="inline">{rupees(appt.consultation_fee)}</dd></div>}
          {appt.reason_text && <div><dt className="inline font-semibold">{t("appt.reason")}: </dt><dd className="inline">{appt.reason_text}</dd></div>}
          {appt.cancel_reason && <div><dt className="inline font-semibold">{t("appt.cancelReason")}: </dt><dd className="inline">{appt.cancel_reason}</dd></div>}
        </dl>
        {open && future && (
          <div className="mt-3 flex flex-wrap gap-2">
            {allowed("RESCHEDULE_APPOINTMENTS") && (
              <Button variant="secondary" onClick={() => navigate(`/book${query({ reschedule: appt.id, specialty: appt.specialty.id })}`)}>{t("appt.reschedule")}</Button>
            )}
            {allowed("CANCEL_APPOINTMENTS") && <Button variant="danger" onClick={() => setCancelling(true)}>{t("appt.cancel")}</Button>}
          </div>
        )}
      </Card>

      {allowed("VIEW_PRECONSULTATION_INFORMATION") && <IntakeSection appointment={appt} />}
      {allowed("VIEW_FOLLOW_UP_INFORMATION") && <FollowUpSection appointmentId={appt.id} />}

      {cancelling && <CancelDialog appointment={appt} onClose={() => setCancelling(false)} onDone={() => { setCancelling(false); reload(); }} />}
    </div>
  );
}

function IntakeSection({ appointment }: { appointment: Appointment }) {
  const { t } = useTranslation();
  const lang = useLang();
  const self = appointment.viewer === "SELF";
  const intake = useLoad(() => get<Intake>(`/appointments/${appointment.id}/intake`), [appointment.id]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [summaryTick, setSummaryTick] = useState(0);
  const save = useAction();

  useEffect(() => {
    if (intake.data) setAnswers(intake.data.answers);
  }, [intake.data]);

  if (intake.loading) return <Loading />;
  if (intake.error != null) return <ErrorPanel error={intake.error} onRetry={intake.reload} />;
  const data = intake.data;
  if (!data || !data.questionnaire) return null;
  const editable = data.can_edit && (appointment.status === "CONFIRMED" || appointment.status === "PENDING");
  const hasAnswers = Object.values(data.answers).some((value) => value.trim());

  const submit = async () => {
    setSaved(false);
    const result = await save.run(() => put<Intake>(`/appointments/${appointment.id}/intake`, { answers }));
    if (result) {
      setSaved(true);
      intake.reload();
      setSummaryTick((n) => n + 1);
    }
  };

  return (
    <>
      <Card className="mb-4">
        <h2 className="mb-1">{lang === "te" ? data.questionnaire.title_te : data.questionnaire.title_en}</h2>
        <p className="mb-3 text-sm text-slate-700">{t("intake.note")}</p>
        {data.questionnaire.review_status !== "CLINICIAN_REVIEWED" && <p className="mb-3 text-sm text-slate-600">{t("book.unreviewed")}</p>}
        {save.error != null && <ErrorPanel error={save.error} />}
        {saved && <Banner kind="success">{t("intake.saved")}</Banner>}
        {!editable && !hasAnswers && <p>{t("intake.none")}</p>}
        {data.questionnaire.questions.map((question) => {
          const label = lang === "te" ? question.text_te : question.text_en;
          const fieldId = `intake-${question.key}`;
          return editable ? (
            <div key={question.key} className="mb-4">
              <label className="label" htmlFor={fieldId}>{label}</label>
              <textarea id={fieldId} className="input" rows={2} maxLength={1000} value={answers[question.key] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [question.key]: e.target.value })} />
            </div>
          ) : data.answers[question.key] ? (
            <div key={question.key} className="mb-3">
              <p className="font-semibold">{label}</p>
              <p className="whitespace-pre-line">{data.answers[question.key]}</p>
            </div>
          ) : null;
        })}
        {editable && <Button onClick={submit} disabled={save.busy}>{save.busy ? t("common.pleaseWait") : t("intake.save")}</Button>}
      </Card>
      <SummarySection appointmentId={appointment.id} self={self} hasAnswers={hasAnswers} refresh={summaryTick} />
    </>
  );
}

function SummarySection({ appointmentId, self, hasAnswers, refresh }: { appointmentId: string; self: boolean; hasAnswers: boolean; refresh: number }) {
  const { t } = useTranslation();
  const summary = useLoad(() => get<Summary | null>(`/appointments/${appointmentId}/summary`), [appointmentId, refresh]);
  const action = useAction();
  const [draft, setDraft] = useState<Record<string, string> | null>(null);

  if (summary.loading) return null;
  if (summary.error != null) return <ErrorPanel error={summary.error} onRetry={summary.reload} />;
  const data = summary.data;
  if (!data && !self) return null;

  const generate = async () => {
    const result = await action.run(() => post<Summary>(`/appointments/${appointmentId}/summary`));
    if (result) summary.reload();
  };
  const saveDraft = async () => {
    if (!draft) return;
    const result = await action.run(() => patch<Summary>(`/appointments/${appointmentId}/summary`, { content: draft }));
    if (result) {
      setDraft(null);
      summary.reload();
    }
  };
  const share = async () => {
    const result = await action.run(() => patch<Summary>(`/appointments/${appointmentId}/summary`, { mark_reviewed: true }));
    if (result) summary.reload();
  };

  return (
    <Card className="mb-4">
      <h2 className="mb-1">{t("summary.title")}</h2>
      {action.error != null && <ErrorPanel error={action.error} />}
      {!data && (
        <>
          <p className="mb-3">{t("summary.explain")}</p>
          <Button onClick={generate} disabled={action.busy || !hasAnswers}>{action.busy ? t("common.pleaseWait") : t("summary.generate")}</Button>
          {!hasAnswers && <p className="mt-2 text-sm text-slate-700">{t("summary.needAnswers")}</p>}
        </>
      )}
      {data && (
        <>
          <p className="mb-3">
            <span className="rounded bg-violet-100 px-2 py-0.5 text-sm font-semibold text-violet-900">{t("summary.aiLabel")}</span>
            {data.patient_edited && <span className="ml-2 text-sm text-slate-700">{t("summary.edited")}</span>}
          </p>
          {SUMMARY_KEYS.map((key) =>
            draft ? (
              <div key={key} className="mb-3">
                <label className="label" htmlFor={`summary-${key}`}>{t(`summary.section.${key}`)}</label>
                <textarea id={`summary-${key}`} className="input" rows={2} maxLength={2000} value={draft[key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
              </div>
            ) : data.content[key] ? (
              <div key={key} className="mb-3">
                <p className="font-semibold">{t(`summary.section.${key}`)}</p>
                <p className="whitespace-pre-line">{data.content[key]}</p>
              </div>
            ) : null,
          )}
          {data.clinician_correction && (
            <div className="mb-3 rounded-lg border border-slate-300 p-3">
              <p className="font-semibold">{t("summary.correction")}</p>
              <p className="whitespace-pre-line">{data.clinician_correction}</p>
            </div>
          )}
          {self && (
            <>
              {data.patient_reviewed_at
                ? <Banner kind="success">{t("summary.shared")}</Banner>
                : <Banner kind="warning">{t("summary.notShared")}</Banner>}
              <div className="flex flex-wrap gap-2">
                {draft ? (
                  <>
                    <Button onClick={saveDraft} disabled={action.busy}>{t("common.save")}</Button>
                    <Button variant="secondary" onClick={() => setDraft(null)} disabled={action.busy}>{t("common.cancel")}</Button>
                  </>
                ) : (
                  <>
                    {!data.patient_reviewed_at && <Button onClick={share} disabled={action.busy}>{t("summary.share")}</Button>}
                    <Button variant="secondary" onClick={() => setDraft({ ...data.content })} disabled={action.busy}>{t("summary.edit")}</Button>
                    <Button variant="quiet" onClick={generate} disabled={action.busy}>{t("summary.regenerate")}</Button>
                  </>
                )}
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}

function FollowUpSection({ appointmentId }: { appointmentId: string }) {
  const { t } = useTranslation();
  const lang = useLang();
  const followUp = useLoad(() => get<FollowUp | null>(`/appointments/${appointmentId}/follow-up`), [appointmentId]);
  if (followUp.loading) return null;
  if (followUp.error != null) return <ErrorPanel error={followUp.error} onRetry={followUp.reload} />;
  if (!followUp.data) return null;
  return (
    <Card className="mb-4">
      <h2 className="mb-1">{t("followUp.title")}</h2>
      <p className="mb-2 text-sm text-slate-700">{t("followUp.byDoctor")}</p>
      <p className="whitespace-pre-line">{followUp.data.instructions_text}</p>
      {followUp.data.next_visit_date && <p className="mt-2 font-semibold">{t("followUp.nextVisit")}: {fmtDate(`${followUp.data.next_visit_date}T06:30:00Z`, lang)}</p>}
    </Card>
  );
}
