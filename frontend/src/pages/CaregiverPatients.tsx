// Caregiver's view: choose which patient to act for, or ask a patient for access.
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { get, post, type Relationship } from "../api";
import { useAuth } from "../auth";
import { Banner, Button, Card, Empty, ErrorPanel, Field, Loading, PageTitle, StatusBadge, useAction, useLoad } from "../ui";
import { PermissionChecklist } from "./CareCircle";

export default function CaregiverPatients() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { activePatient, chooseCaregiverPatient } = useAuth();
  const rels = useLoad(() => get<Relationship[]>("/care/relationships"), []);
  const perms = useLoad(() => get<{ permissions: string[] }>("/care/permissions"), []);
  const request = useAction();
  const [identifier, setIdentifier] = useState("");
  const [chosen, setChosen] = useState<string[]>(["VIEW_APPOINTMENTS", "BOOK_APPOINTMENTS"]);
  const [sent, setSent] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSent(false);
    const result = await request.run(() => post("/care/requests", { patient_identifier: identifier.trim(), permissions: chosen }));
    if (result) {
      setSent(true);
      setIdentifier("");
      rels.reload();
    }
  };

  const list = rels.data ?? [];
  const active = list.filter((r) => r.status === "ACTIVE");
  const others = list.filter((r) => r.status !== "ACTIVE");

  return (
    <div>
      <PageTitle>{t("nav.patients")}</PageTitle>
      {rels.loading && <Loading />}
      {rels.error != null && <ErrorPanel error={rels.error} onRetry={rels.reload} />}

      {!rels.loading && rels.error == null && active.length === 0 && <Empty title={t("care.noPatients")} />}
      <div className="mb-6 space-y-3">
        {active.map((rel) => {
          const current = activePatient?.id === rel.patient.id;
          return (
            <Card key={rel.id} className={current ? "border-2 border-brand-600" : ""}>
              <p className="text-xl font-semibold">{rel.patient.full_name}</p>
              <p className="mb-1">{t("care.youCan")}</p>
              <ul className="mb-3 list-disc pl-6">
                {rel.permissions.map((p) => <li key={p}>{t(`permission.${p}`)}</li>)}
              </ul>
              {current
                ? <p className="font-semibold">{t("care.currentlyActing")}</p>
                : <Button onClick={() => { chooseCaregiverPatient(rel); navigate("/home"); }}>{t("care.actFor", { name: rel.patient.full_name })}</Button>}
            </Card>
          );
        })}
      </div>

      {others.length > 0 && (
        <section className="mb-6" aria-labelledby="other-requests">
          <h2 id="other-requests" className="mb-2">{t("care.yourRequests")}</h2>
          <div className="space-y-2">
            {others.map((rel) => (
              <Card key={rel.id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold">{rel.patient.full_name}</p>
                  <StatusBadge status={rel.status} />
                </div>
              </Card>
            ))}
          </div>
        </section>
      )}

      <Card>
        <h2 className="mb-2">{t("care.requestTitle")}</h2>
        <p className="mb-3">{t("care.requestExplain")}</p>
        {request.error != null && <ErrorPanel error={request.error} />}
        {sent && <Banner kind="success">{t("care.requestSent")}</Banner>}
        <form onSubmit={submit}>
          <Field label={t("care.patientIdentifier")} hint={t("auth.identifierHint")}>
            {(id) => <input id={id} className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required autoComplete="off" />}
          </Field>
          {perms.data && <PermissionChecklist all={perms.data.permissions} value={chosen} onChange={setChosen} idPrefix="ask" />}
          <Button type="submit" disabled={request.busy || !identifier.trim() || chosen.length === 0}>
            {request.busy ? t("common.pleaseWait") : t("care.sendRequest")}
          </Button>
        </form>
      </Card>
    </div>
  );
}
