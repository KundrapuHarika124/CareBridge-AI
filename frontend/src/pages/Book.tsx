// Manual booking in four steps: what it is about, where, doctor and time, confirm.
// Works with no AI or voice provider. Also used to pick a new time when rescheduling.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ApiError, get, newIdempotencyKey, post, query,
  type Appointment, type Concern, type DoctorCard, type Lang, type Slot, type Specialty, type Suggestion,
} from "../api";
import { can, useAuth } from "../auth";
import { fmtDate, fmtDateTime, fmtTime, groupByDay, pickName, rupees } from "../lib/format";
import { Banner, Button, Card, Empty, ErrorPanel, Loading, PageTitle, SimTag, useAction, useLang, useLoad } from "../ui";

type Step = "concern" | "area" | "doctor" | "confirm" | "done";
interface Choice { doctor: DoctorCard; slot: Slot }

export default function Book() {
  const { t } = useTranslation();
  const lang = useLang();
  const navigate = useNavigate();
  const { activePatient } = useAuth();
  const [params] = useSearchParams();
  const rescheduleId = params.get("reschedule");
  const presetSpecialty = params.get("specialty");

  const [step, setStep] = useState<Step>(presetSpecialty ? "area" : "concern");
  const [specialtyId, setSpecialtyId] = useState<string | null>(presetSpecialty);
  const [reason, setReason] = useState("");
  const [locality, setLocality] = useState<string | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [booked, setBooked] = useState<Appointment | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

  const allowed = can(activePatient, rescheduleId ? "RESCHEDULE_APPOINTMENTS" : "BOOK_APPOINTMENTS");
  if (!activePatient) return <Empty title={t("care.choosePatientFirst")}><Link className="btn btn-primary" to="/patients">{t("nav.patients")}</Link></Empty>;
  if (!allowed) return <Banner kind="warning">{t("care.noBookingPermission")}</Banner>;

  const steps: Step[] = ["concern", "area", "doctor", "confirm"];
  const stepNumber = Math.min(steps.indexOf(step) + 1, 4) || 4;

  return (
    <div>
      <PageTitle>{rescheduleId ? t("book.rescheduleTitle") : t("book.title")}</PageTitle>
      {activePatient && !activePatient.self && <Banner kind="info">{t("care.actingFor", { name: activePatient.name })}</Banner>}
      {step !== "done" && <p className="mb-4 font-semibold text-slate-700" aria-live="polite">{t("book.step", { n: stepNumber, total: 4 })}</p>}

      {step === "concern" && (
        <ConcernStep
          lang={lang}
          onPick={(id, text) => {
            setSpecialtyId(id);
            setReason(text);
            setStep("area");
          }}
        />
      )}
      {step === "area" && (
        <AreaStep
          onBack={presetSpecialty ? undefined : () => setStep("concern")}
          onPick={(value) => {
            setLocality(value);
            setStep("doctor");
          }}
        />
      )}
      {step === "doctor" && specialtyId && (
        <DoctorStep
          specialtyId={specialtyId}
          locality={locality}
          patientId={activePatient.id}
          onBack={() => setStep("area")}
          onPick={(picked) => {
            setChoice(picked);
            setIdempotencyKey(newIdempotencyKey());
            setStep("confirm");
          }}
        />
      )}
      {step === "confirm" && choice && (
        <ConfirmStep
          choice={choice}
          patientName={activePatient.name}
          isReschedule={!!rescheduleId}
          onBack={() => setStep("doctor")}
          submit={() =>
            rescheduleId
              ? post<Appointment>(`/appointments/${rescheduleId}/reschedule`, { new_slot_id: choice.slot.id }, { "Idempotency-Key": idempotencyKey })
              : post<Appointment>("/appointments", { slot_id: choice.slot.id, patient_id: activePatient.id, reason_text: reason || null }, { "Idempotency-Key": idempotencyKey })
          }
          onDone={(appt) => {
            setBooked(appt);
            setStep("done");
          }}
          onConflict={() => {
            setChoice(null);
            setStep("doctor");
          }}
        />
      )}
      {step === "done" && booked && (
        <Card>
          <Banner kind="success">{rescheduleId ? t("book.rescheduled") : t("book.success")}</Banner>
          <p className="text-xl font-semibold">{fmtDateTime(booked.starts_at, lang)}</p>
          <p>{booked.doctor_name}</p>
          <p>{booked.hospital.name}, {booked.hospital.locality}{booked.hospital.is_simulated && <SimTag />}</p>
          <p>{t("appt.patient")}: {booked.patient.full_name}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => navigate(`/appointments/${booked.id}`)}>{t("book.addDetails")}</Button>
            <Button variant="secondary" onClick={() => navigate("/appointments")}>{t("nav.appointments")}</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function ConcernStep({ lang, onPick }: { lang: Lang; onPick: (specialtyId: string, reason: string) => void }) {
  const { t } = useTranslation();
  const concerns = useLoad(() => get<Concern[]>("/navigation/concerns"), []);
  const specialties = useLoad(() => get<Specialty[]>("/specialties"), []);
  const { run, busy, error } = useAction();
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<{ emergency: boolean; suggestions: Suggestion[] } | null>(null);
  const [showAll, setShowAll] = useState(false);

  const suggest = async (body: { text?: string; concern_key?: string }, label: string) => {
    const found = await run(() => post<{ emergency: boolean; suggestions: Suggestion[] }>("/navigation/suggest", body));
    if (found) {
      setReason(label);
      setResult(found);
      setShowAll(found.suggestions.length === 0);
    }
  };

  if (concerns.loading || specialties.loading) return <Loading />;
  if (concerns.error != null) return <ErrorPanel error={concerns.error} onRetry={concerns.reload} />;
  if (specialties.error != null) return <ErrorPanel error={specialties.error} onRetry={specialties.reload} />;

  return (
    <div>
      <h2 className="mb-3">{t("book.whatAbout")}</h2>
      {error != null && <ErrorPanel error={error} />}
      {result?.emergency && <Banner kind="error">{t("book.emergency")}</Banner>}

      {!result && (
        <>
          <div className="mb-4 grid gap-2 sm:grid-cols-2">
            {(concerns.data ?? []).map((c) => (
              <Button key={c.concern_key} variant="secondary" disabled={busy} className="justify-start text-left"
                onClick={() => suggest({ concern_key: c.concern_key }, lang === "te" ? c.label_te : c.label_en)}>
                {lang === "te" ? c.label_te : c.label_en}
              </Button>
            ))}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) suggest({ text: text.trim() }, text.trim()); }}>
            <label className="label" htmlFor="concern-text">{t("book.orDescribe")}</label>
            <div className="flex flex-wrap gap-2">
              <input id="concern-text" className="input flex-1" value={text} maxLength={300} onChange={(e) => setText(e.target.value)} />
              <Button type="submit" disabled={busy || !text.trim()}>{t("common.continue")}</Button>
            </div>
          </form>
          <Button variant="quiet" className="mt-4" onClick={() => { setResult({ emergency: false, suggestions: [] }); setShowAll(true); }}>
            {t("book.iKnowSpecialty")}
          </Button>
        </>
      )}

      {result && (
        <>
          {result.suggestions.length > 0 && (
            <>
              <Banner kind="info">{t("book.suggestionNote")}</Banner>
              <div className="mb-4 space-y-2">
                {result.suggestions.map((s) => (
                  <Card key={s.specialty.id}>
                    <p className="text-xl font-semibold">{pickName(s.specialty, lang)}</p>
                    <p>{lang === "te" ? s.explanation_te : s.explanation_en}</p>
                    {s.review_status !== "CLINICIAN_REVIEWED" && <p className="mt-1 text-sm text-slate-600">{t("book.unreviewed")}</p>}
                    <Button className="mt-3" onClick={() => onPick(s.specialty.id, reason)}>{t("book.chooseThis")}</Button>
                  </Card>
                ))}
              </div>
            </>
          )}
          {result.suggestions.length === 0 && !result.emergency && <Banner kind="info">{t("book.noMatch")}</Banner>}
          {showAll ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {(specialties.data ?? []).map((s) => (
                <Button key={s.id} variant="secondary" onClick={() => onPick(s.id, reason)}>{pickName(s, lang)}</Button>
              ))}
            </div>
          ) : (
            <Button variant="quiet" onClick={() => setShowAll(true)}>{t("book.otherSpecialty")}</Button>
          )}
          <div className="mt-4">
            <Button variant="secondary" onClick={() => { setResult(null); setShowAll(false); }}>{t("common.back")}</Button>
          </div>
        </>
      )}
    </div>
  );
}

function AreaStep({ onPick, onBack }: { onPick: (locality: string | null) => void; onBack?: () => void }) {
  const { t } = useTranslation();
  const { data, error, loading, reload } = useLoad(() => get<string[]>("/localities"), []);
  if (loading) return <Loading />;
  if (error != null) return <ErrorPanel error={error} onRetry={reload} />;
  return (
    <div>
      <h2 className="mb-3">{t("book.whichArea")}</h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {(data ?? []).map((loc) => <Button key={loc} variant="secondary" onClick={() => onPick(loc)}>{loc}</Button>)}
        <Button variant="secondary" onClick={() => onPick(null)}>{t("book.anyArea")}</Button>
      </div>
      {onBack && <Button variant="quiet" className="mt-4" onClick={onBack}>{t("common.back")}</Button>}
    </div>
  );
}

function DoctorStep({ specialtyId, locality, patientId, onPick, onBack }: {
  specialtyId: string; locality: string | null; patientId: string; onPick: (choice: Choice) => void; onBack: () => void;
}) {
  const { t } = useTranslation();
  const lang = useLang();
  const { data, error, loading, reload } = useLoad(
    () => get<DoctorCard[]>(`/doctors${query({ specialty_id: specialtyId, locality })}`),
    [specialtyId, locality],
  );
  const [open, setOpen] = useState<string | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const more = useAction();
  const wait = useAction();
  const [joined, setJoined] = useState<string[]>([]);

  const showMore = async (doctor: DoctorCard) => {
    setOpen(doctor.affiliation_id);
    setSlots([]);
    const found = await more.run(() => get<Slot[]>(`/affiliations/${doctor.affiliation_id}/slots`));
    if (found) setSlots(found);
  };
  const joinWaitingList = async (doctor: DoctorCard) => {
    const entry = await wait.run(() => post("/waiting-list", { affiliation_id: doctor.affiliation_id, patient_id: patientId }));
    if (entry) setJoined([...joined, doctor.affiliation_id]);
  };

  if (loading) return <Loading />;
  if (error != null) return <ErrorPanel error={error} onRetry={reload} />;
  const doctors = data ?? [];

  return (
    <div>
      <h2 className="mb-3">{t("book.chooseDoctor")}</h2>
      {wait.error != null && <ErrorPanel error={wait.error} />}
      {doctors.length === 0 && <Empty title={t("book.noDoctors")}><Button onClick={onBack}>{t("book.changeArea")}</Button></Empty>}
      <div className="space-y-3">
        {doctors.map((doctor) => (
          <Card key={doctor.affiliation_id}>
            <p className="text-xl font-semibold">{doctor.doctor_name}</p>
            <p>{pickName(doctor.specialty, lang)}{doctor.qualifications && `, ${doctor.qualifications}`}</p>
            <p>{doctor.hospital.name}, {doctor.hospital.locality}{doctor.hospital.is_simulated && <SimTag />}</p>
            {doctor.consultation_fee !== null && <p>{t("book.fee")}: {rupees(doctor.consultation_fee)}</p>}
            {doctor.next_slots.length === 0 ? (
              <div className="mt-3">
                <p className="mb-2">{t("book.noSlots")}</p>
                {joined.includes(doctor.affiliation_id)
                  ? <Banner kind="success">{t("wait.joined")}</Banner>
                  : <Button variant="secondary" disabled={wait.busy} onClick={() => joinWaitingList(doctor)}>{t("wait.join")}</Button>}
              </div>
            ) : (
              <div className="mt-3">
                <p className="mb-2 font-semibold">{t("book.nextTimes")}</p>
                <div className="flex flex-wrap gap-2">
                  {doctor.next_slots.map((slot) => (
                    <Button key={slot.id} variant="secondary" onClick={() => onPick({ doctor, slot })}>{fmtDateTime(slot.starts_at, lang)}</Button>
                  ))}
                  <Button variant="quiet" onClick={() => showMore(doctor)} aria-expanded={open === doctor.affiliation_id}>{t("book.moreTimes")}</Button>
                </div>
              </div>
            )}
            {open === doctor.affiliation_id && (
              <div className="mt-3 border-t border-slate-200 pt-3">
                {more.busy && <Loading />}
                {more.error != null && <ErrorPanel error={more.error} />}
                {groupByDay(slots).map(([day, daySlots]) => (
                  <div key={day} className="mb-3">
                    <p className="mb-1 font-semibold">{fmtDate(daySlots[0].starts_at, lang)}</p>
                    <div className="flex flex-wrap gap-2">
                      {daySlots.map((slot) => (
                        <Button key={slot.id} variant="secondary" onClick={() => onPick({ doctor, slot })}>{fmtTime(slot.starts_at, lang)}</Button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>
      <Button variant="quiet" className="mt-4" onClick={onBack}>{t("common.back")}</Button>
    </div>
  );
}

function ConfirmStep({ choice, patientName, isReschedule, submit, onDone, onConflict, onBack }: {
  choice: Choice; patientName: string; isReschedule: boolean; submit: () => Promise<Appointment>;
  onDone: (appt: Appointment) => void; onConflict: () => void; onBack: () => void;
}) {
  const { t } = useTranslation();
  const lang = useLang();
  const { run, busy, error } = useAction();
  const conflict = error instanceof ApiError && error.code === "SLOT_UNAVAILABLE";

  const confirm = async () => {
    const appt = await run(submit);
    if (appt) onDone(appt);
  };

  return (
    <Card>
      <h2 className="mb-3">{t("book.checkDetails")}</h2>
      {error != null && <ErrorPanel error={error} />}
      <dl className="mb-4 space-y-2">
        <div><dt className="font-semibold">{t("appt.patient")}</dt><dd>{patientName}</dd></div>
        <div><dt className="font-semibold">{t("appt.doctor")}</dt><dd>{choice.doctor.doctor_name}, {pickName(choice.doctor.specialty, lang)}</dd></div>
        <div>
          <dt className="font-semibold">{t("appt.hospital")}</dt>
          <dd>{choice.doctor.hospital.name}, {choice.doctor.hospital.locality}{choice.doctor.hospital.is_simulated && <SimTag />}</dd>
        </div>
        <div><dt className="font-semibold">{t("appt.when")}</dt><dd className="text-xl">{fmtDateTime(choice.slot.starts_at, lang)}</dd></div>
        {choice.doctor.consultation_fee !== null && <div><dt className="font-semibold">{t("book.fee")}</dt><dd>{rupees(choice.doctor.consultation_fee)}</dd></div>}
      </dl>
      {conflict ? (
        <Button onClick={onConflict}>{t("book.chooseAnotherTime")}</Button>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button onClick={confirm} disabled={busy}>{busy ? t("common.pleaseWait") : isReschedule ? t("book.confirmReschedule") : t("book.confirm")}</Button>
          <Button variant="secondary" onClick={onBack} disabled={busy}>{t("common.back")}</Button>
        </div>
      )}
    </Card>
  );
}
