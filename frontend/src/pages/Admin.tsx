// Hospital administration. Every call is scoped to one hospital id, and the backend checks
// that the signed-in admin belongs to that hospital.
import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { del, get, patch, post, query, type Appointment, type DoctorCard, type Hospital, type Overview, type Schedule, type Slot, type Specialty } from "../api";
import { useAuth } from "../auth";
import { fmtDateTime, fmtTime, istDate, pickName, rupees } from "../lib/format";
import { Banner, Button, Card, Empty, ErrorPanel, Field, Loading, PageTitle, SimTag, StatusBadge, useAction, useLang, useLoad } from "../ui";
import { CancelDialog } from "./Appointments";

interface Department { id: string; name: string }

/** Resolve the admin's hospital; shows a clear message when the account has none. */
function useHospital(): { base: string | null; gate: ReactNode } {
  const { t } = useTranslation();
  const { user } = useAuth();
  const hospitalId = user?.hospital_ids[0] ?? null;
  return { base: hospitalId ? `/admin/hospitals/${hospitalId}` : null, gate: hospitalId ? null : <Banner kind="warning">{t("admin.noHospital")}</Banner> };
}

function DoctorPicker({ doctors, value, onChange }: { doctors: DoctorCard[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="mb-4 max-w-md">
      <label className="label" htmlFor="doctor-pick">{t("admin.chooseDoctor")}</label>
      <select id="doctor-pick" className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("admin.select")}</option>
        {doctors.map((d) => <option key={d.affiliation_id} value={d.affiliation_id}>{d.doctor_name} · {d.specialty.name_en}</option>)}
      </select>
    </div>
  );
}

export function AdminOverview() {
  const { t } = useTranslation();
  const { base, gate } = useHospital();
  const data = useLoad(async () => {
    if (!base) return null;
    const [hospital, overview] = await Promise.all([get<Hospital>(base), get<Overview>(`${base}/overview`)]);
    return { hospital, overview };
  }, [base]);
  if (gate) return <>{gate}</>;
  if (data.loading) return <Loading />;
  if (data.error != null) return <ErrorPanel error={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  const { hospital, overview } = data.data;
  const tiles: [string, number][] = [
    [t("admin.tile.appointmentsToday"), overview.appointments_today],
    [t("admin.tile.upcoming"), overview.upcoming_confirmed],
    [t("admin.tile.openSlots"), overview.open_slots_next_7_days],
    [t("admin.tile.activeDoctors"), overview.active_doctors],
    [t("admin.tile.cancelled"), overview.cancelled_last_7_days],
    [t("admin.tile.waiting"), overview.waiting_list],
  ];
  return (
    <div>
      <PageTitle>{hospital.name}{hospital.is_simulated && <SimTag />}</PageTitle>
      <p className="mb-4 text-slate-700">{hospital.address}</p>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map(([label, value]) => (
          <div key={label} className="card">
            <dt className="text-slate-700">{label}</dt>
            <dd className="text-3xl font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function AdminDepartments() {
  const { t } = useTranslation();
  const { base, gate } = useHospital();
  const list = useLoad(() => (base ? get<Department[]>(`${base}/departments`) : Promise.resolve([])), [base]);
  const action = useAction();
  const [name, setName] = useState("");
  if (gate) return <>{gate}</>;
  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (await action.run(() => post(`${base}/departments`, { name: name.trim() }))) {
      setName("");
      list.reload();
    }
  };
  return (
    <div>
      <PageTitle>{t("nav.departments")}</PageTitle>
      {list.loading && <Loading />}
      {list.error != null && <ErrorPanel error={list.error} onRetry={list.reload} />}
      <ul className="mb-6 space-y-2">
        {(list.data ?? []).map((d) => <li key={d.id} className="card">{d.name}</li>)}
      </ul>
      <Card>
        <h2 className="mb-2">{t("admin.addDepartment")}</h2>
        {action.error != null && <ErrorPanel error={action.error} />}
        <form onSubmit={add} className="flex flex-wrap items-end gap-2">
          <div className="flex-1">
            <label className="label" htmlFor="dept-name">{t("admin.departmentName")}</label>
            <input id="dept-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={120} />
          </div>
          <Button type="submit" disabled={action.busy || name.trim().length < 2}>{t("admin.add")}</Button>
        </form>
      </Card>
    </div>
  );
}

export function AdminDoctors() {
  const { t } = useTranslation();
  const lang = useLang();
  const { base, gate } = useHospital();
  const data = useLoad(async () => {
    if (!base) return null;
    const [doctors, departments, specialties] = await Promise.all([
      get<DoctorCard[]>(`${base}/doctors`), get<Department[]>(`${base}/departments`), get<Specialty[]>("/specialties"),
    ]);
    return { doctors, departments, specialties };
  }, [base]);
  const action = useAction();
  const blank = { full_name: "", identifier: "", password: "", qualifications: "", years_experience: "", department_id: "", specialty_id: "", consultation_fee: "" };
  const [form, setForm] = useState(blank);
  const [added, setAdded] = useState(false);
  if (gate) return <>{gate}</>;
  if (data.loading) return <Loading />;
  if (data.error != null) return <ErrorPanel error={data.error} onRetry={data.reload} />;
  if (!data.data) return null;
  const { doctors, departments, specialties } = data.data;
  const set = (key: keyof typeof blank) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const add = async (event: FormEvent) => {
    event.preventDefault();
    setAdded(false);
    const result = await action.run(() =>
      post(`${base}/doctors`, {
        full_name: form.full_name.trim(),
        identifier: form.identifier.trim(),
        password: form.password || null,
        qualifications: form.qualifications.trim(),
        years_experience: form.years_experience === "" ? null : Number(form.years_experience),
        department_id: form.department_id,
        specialty_id: form.specialty_id,
        consultation_fee: form.consultation_fee === "" ? null : Number(form.consultation_fee),
      }),
    );
    if (result) {
      setForm(blank);
      setAdded(true);
      data.reload();
    }
  };
  const toggle = async (doctor: DoctorCard) => {
    if (await action.run(() => patch(`${base}/affiliations/${doctor.affiliation_id}`, { is_active: !doctor.is_active }))) data.reload();
  };

  return (
    <div>
      <PageTitle>{t("nav.doctors")}</PageTitle>
      {action.error != null && <ErrorPanel error={action.error} />}
      {doctors.length === 0 && <Empty title={t("admin.noDoctors")} />}
      <div className="mb-6 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-collapse bg-white text-left">
          <thead>
            <tr className="border-b border-slate-300">
              <th scope="col" className="p-2">{t("appt.doctor")}</th>
              <th scope="col" className="p-2">{t("admin.specialty")}</th>
              <th scope="col" className="p-2">{t("admin.department")}</th>
              <th scope="col" className="p-2">{t("book.fee")}</th>
              <th scope="col" className="p-2">{t("admin.state")}</th>
              <th scope="col" className="p-2"><span className="sr-only">{t("admin.actions")}</span></th>
            </tr>
          </thead>
          <tbody>
            {doctors.map((d) => (
              <tr key={d.affiliation_id} className="border-b border-slate-200">
                <th scope="row" className="p-2 font-semibold">{d.doctor_name}<span className="block text-sm font-normal text-slate-700">{d.qualifications}</span></th>
                <td className="p-2">{pickName(d.specialty, lang)}</td>
                <td className="p-2">{d.department.name}</td>
                <td className="p-2">{d.consultation_fee === null ? "–" : rupees(d.consultation_fee)}</td>
                <td className="p-2">{d.is_active ? t("admin.active") : t("admin.inactive")}</td>
                <td className="p-2">
                  <Button variant="secondary" disabled={action.busy} onClick={() => toggle(d)}>{d.is_active ? t("admin.deactivate") : t("admin.activate")}</Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Card>
        <h2 className="mb-1">{t("admin.addDoctor")}</h2>
        <p className="mb-3 text-sm text-slate-700">{t("admin.addDoctorNote")}</p>
        {added && <Banner kind="success">{t("admin.doctorAdded")}</Banner>}
        <form onSubmit={add} className="grid gap-x-4 sm:grid-cols-2">
          <Field label={t("auth.fullName")}>{(id) => <input id={id} className="input" value={form.full_name} onChange={set("full_name")} required minLength={2} />}</Field>
          <Field label={t("auth.identifier")} hint={t("auth.identifierHint")}>{(id) => <input id={id} className="input" value={form.identifier} onChange={set("identifier")} required autoComplete="off" />}</Field>
          <Field label={t("admin.initialPassword")} hint={t("admin.initialPasswordHint")}>{(id) => <input id={id} type="password" className="input" value={form.password} onChange={set("password")} autoComplete="new-password" />}</Field>
          <Field label={t("admin.qualifications")}>{(id) => <input id={id} className="input" value={form.qualifications} onChange={set("qualifications")} maxLength={200} />}</Field>
          <Field label={t("admin.years")}>{(id) => <input id={id} type="number" min={0} max={70} className="input" value={form.years_experience} onChange={set("years_experience")} />}</Field>
          <Field label={t("book.fee")}>{(id) => <input id={id} type="number" min={0} max={100000} className="input" value={form.consultation_fee} onChange={set("consultation_fee")} />}</Field>
          <Field label={t("admin.department")}>
            {(id) => (
              <select id={id} className="input" value={form.department_id} onChange={set("department_id")} required>
                <option value="">{t("admin.select")}</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            )}
          </Field>
          <Field label={t("admin.specialty")}>
            {(id) => (
              <select id={id} className="input" value={form.specialty_id} onChange={set("specialty_id")} required>
                <option value="">{t("admin.select")}</option>
                {specialties.map((s) => <option key={s.id} value={s.id}>{pickName(s, lang)}</option>)}
              </select>
            )}
          </Field>
          <div className="sm:col-span-2"><Button type="submit" disabled={action.busy}>{action.busy ? t("common.pleaseWait") : t("admin.addDoctor")}</Button></div>
        </form>
      </Card>
    </div>
  );
}

export function AdminSchedules() {
  const { t } = useTranslation();
  const lang = useLang();
  const { base, gate } = useHospital();
  const doctors = useLoad(() => (base ? get<DoctorCard[]>(`${base}/doctors`) : Promise.resolve([])), [base]);
  const [aff, setAff] = useState("");
  const [day, setDay] = useState(() => istDate(new Date()));
  const schedules = useLoad(() => (base && aff ? get<Schedule[]>(`${base}/affiliations/${aff}/schedules`) : Promise.resolve([])), [base, aff]);
  const slots = useLoad(() => (base && aff ? get<Slot[]>(`${base}/affiliations/${aff}/slots${query({ on_date: day })}`) : Promise.resolve([])), [base, aff, day]);
  const action = useAction();
  const [form, setForm] = useState({ weekday: "0", start_time: "09:00", end_time: "13:00", slot_minutes: "20" });
  const [notice, setNotice] = useState<string | null>(null);
  if (gate) return <>{gate}</>;

  const run = async (work: () => Promise<unknown>, message?: (result: unknown) => string) => {
    setNotice(null);
    const result = await action.run(work);
    if (result !== undefined) {
      if (message) setNotice(message(result));
      schedules.reload();
      slots.reload();
    }
  };
  const addSchedule = (event: FormEvent) => {
    event.preventDefault();
    run(() => post(`${base}/affiliations/${aff}/schedules`, {
      weekday: Number(form.weekday), start_time: form.start_time, end_time: form.end_time, slot_minutes: Number(form.slot_minutes),
    }));
  };

  return (
    <div>
      <PageTitle>{t("nav.schedules")}</PageTitle>
      {doctors.loading && <Loading />}
      {doctors.error != null && <ErrorPanel error={doctors.error} onRetry={doctors.reload} />}
      <DoctorPicker doctors={doctors.data ?? []} value={aff} onChange={setAff} />
      {action.error != null && <ErrorPanel error={action.error} />}
      {notice && <Banner kind="success">{notice}</Banner>}

      {aff && (
        <>
          <Card className="mb-4">
            <h2 className="mb-2">{t("admin.weeklyHours")}</h2>
            {schedules.loading && <Loading />}
            {schedules.error != null && <ErrorPanel error={schedules.error} onRetry={schedules.reload} />}
            {!schedules.loading && (schedules.data ?? []).length === 0 && <p className="mb-3">{t("admin.noSchedules")}</p>}
            <ul className="mb-4 space-y-2">
              {(schedules.data ?? []).map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                  <span>{t(`weekday.${s.weekday}`)}, {s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)} ({t("admin.minutes", { count: s.slot_minutes })})</span>
                  <Button variant="secondary" disabled={action.busy} onClick={() => run(() => del(`${base}/schedules/${s.id}`))}>{t("admin.remove")}</Button>
                </li>
              ))}
            </ul>
            <form onSubmit={addSchedule} className="grid gap-x-4 sm:grid-cols-4">
              <Field label={t("admin.weekday")}>
                {(id) => (
                  <select id={id} className="input" value={form.weekday} onChange={(e) => setForm({ ...form, weekday: e.target.value })}>
                    {[0, 1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{t(`weekday.${n}`)}</option>)}
                  </select>
                )}
              </Field>
              <Field label={t("admin.from")}>{(id) => <input id={id} type="time" className="input" value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} required />}</Field>
              <Field label={t("admin.to")}>{(id) => <input id={id} type="time" className="input" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} required />}</Field>
              <Field label={t("admin.slotLength")}>{(id) => <input id={id} type="number" min={5} max={120} className="input" value={form.slot_minutes} onChange={(e) => setForm({ ...form, slot_minutes: e.target.value })} required />}</Field>
              <div className="flex flex-wrap gap-2 sm:col-span-4">
                <Button type="submit" disabled={action.busy}>{t("admin.addHours")}</Button>
                <Button variant="secondary" disabled={action.busy}
                  onClick={() => run(() => post<{ created: number }>(`${base}/affiliations/${aff}/slots/generate`, { days: 14 }), (r) => t("admin.slotsCreated", { count: (r as { created: number }).created }))}>
                  {t("admin.generate")}
                </Button>
              </div>
            </form>
          </Card>

          <Card>
            <h2 className="mb-2">{t("admin.slotsOn")}</h2>
            <div className="mb-3 max-w-xs">
              <label className="label" htmlFor="slot-day">{t("doctor.date")}</label>
              <input id="slot-day" type="date" className="input" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
            </div>
            {slots.loading && <Loading />}
            {slots.error != null && <ErrorPanel error={slots.error} onRetry={slots.reload} />}
            {!slots.loading && (slots.data ?? []).length === 0 && <p>{t("admin.noSlots")}</p>}
            <ul className="space-y-2">
              {(slots.data ?? []).map((slot) => (
                <li key={slot.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
                  <span className="font-semibold">{fmtTime(slot.starts_at, lang)}</span>
                  <StatusBadge status={slot.status} />
                  {slot.status === "AVAILABLE" && <Button variant="secondary" disabled={action.busy} onClick={() => run(() => post(`${base}/slots/${slot.id}/block`))}>{t("admin.block")}</Button>}
                  {slot.status === "BLOCKED" && <Button variant="secondary" disabled={action.busy} onClick={() => run(() => post(`${base}/slots/${slot.id}/unblock`))}>{t("admin.unblock")}</Button>}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

export function AdminAppointments() {
  const { t } = useTranslation();
  const lang = useLang();
  const { base, gate } = useHospital();
  const [day, setDay] = useState(() => istDate(new Date()));
  const [status, setStatus] = useState("");
  const [cancelling, setCancelling] = useState<Appointment | null>(null);
  const list = useLoad(() => (base ? get<Appointment[]>(`${base}/appointments${query({ on_date: day, status })}`) : Promise.resolve([])), [base, day, status]);
  if (gate) return <>{gate}</>;
  const rows = list.data ?? [];
  return (
    <div>
      <PageTitle>{t("nav.appointments")}</PageTitle>
      <p className="mb-3 text-sm text-slate-700">{t("admin.noClinical")}</p>
      <div className="mb-4 grid max-w-xl gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="admin-day">{t("doctor.date")}</label>
          <input id="admin-day" type="date" className="input" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="admin-status">{t("admin.state")}</label>
          <select id="admin-status" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("admin.all")}</option>
            {["CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW", "RESCHEDULED"].map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
          </select>
        </div>
      </div>
      {list.loading && <Loading />}
      {list.error != null && <ErrorPanel error={list.error} onRetry={list.reload} />}
      {!list.loading && list.error == null && rows.length === 0 && <Empty title={t("doctor.none")} />}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse bg-white text-left">
            <thead>
              <tr className="border-b border-slate-300">
                <th scope="col" className="p-2">{t("appt.when")}</th>
                <th scope="col" className="p-2">{t("appt.patient")}</th>
                <th scope="col" className="p-2">{t("appt.doctor")}</th>
                <th scope="col" className="p-2">{t("admin.state")}</th>
                <th scope="col" className="p-2"><span className="sr-only">{t("admin.actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((appt) => (
                <tr key={appt.id} className="border-b border-slate-200">
                  <td className="p-2">{fmtDateTime(appt.starts_at, lang)}</td>
                  <td className="p-2">{appt.patient.full_name}</td>
                  <td className="p-2">{appt.doctor_name}</td>
                  <td className="p-2"><StatusBadge status={appt.status} /></td>
                  <td className="p-2">
                    {(appt.status === "CONFIRMED" || appt.status === "PENDING") && (
                      <Button variant="danger" onClick={() => setCancelling(appt)}>{t("appt.cancel")}</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cancelling && (
        <CancelDialog appointment={cancelling} adminPath={`${base}/appointments/${cancelling.id}/cancel`}
          onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); list.reload(); }} />
      )}
    </div>
  );
}
