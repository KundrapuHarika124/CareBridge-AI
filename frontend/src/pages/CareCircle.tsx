// Patient's view of caregivers: approve or reject requests, change permissions, revoke.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { get, patch, post, type ConsentEvent, type Relationship } from "../api";
import { fmtDateTime } from "../lib/format";
import { Banner, Button, Card, Empty, ErrorPanel, Loading, Modal, PageTitle, StatusBadge, useAction, useLang, useLoad } from "../ui";

export function PermissionChecklist({ all, value, onChange, idPrefix }: { all: string[]; value: string[]; onChange: (next: string[]) => void; idPrefix: string }) {
  const { t } = useTranslation();
  return (
    <fieldset className="mb-4">
      <legend className="label">{t("care.permissionsLegend")}</legend>
      {all.map((permission) => (
        <label key={permission} htmlFor={`${idPrefix}-${permission}`} className="flex min-h-[3rem] items-center gap-3">
          <input id={`${idPrefix}-${permission}`} type="checkbox" className="h-5 w-5" checked={value.includes(permission)}
            onChange={(e) => onChange(e.target.checked ? [...value, permission] : value.filter((p) => p !== permission))} />
          {t(`permission.${permission}`)}
        </label>
      ))}
    </fieldset>
  );
}

export default function CareCircle() {
  const { t } = useTranslation();
  const lang = useLang();
  const rels = useLoad(() => get<Relationship[]>("/care/relationships"), []);
  const perms = useLoad(() => get<{ permissions: string[] }>("/care/permissions"), []);
  const action = useAction();
  const [editing, setEditing] = useState<{ rel: Relationship; mode: "approve" | "edit" } | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [revoking, setRevoking] = useState<Relationship | null>(null);
  const [history, setHistory] = useState<{ rel: Relationship; events: ConsentEvent[] } | null>(null);

  if (rels.loading || perms.loading) return <Loading />;
  if (rels.error != null) return <ErrorPanel error={rels.error} onRetry={rels.reload} />;
  if (perms.error != null) return <ErrorPanel error={perms.error} onRetry={perms.reload} />;
  const all = perms.data?.permissions ?? [];
  const list = rels.data ?? [];
  const requested = list.filter((r) => r.status === "REQUESTED");
  const active = list.filter((r) => r.status === "ACTIVE");
  const closed = list.filter((r) => r.status === "REJECTED" || r.status === "REVOKED");

  const done = () => {
    setEditing(null);
    setRevoking(null);
    rels.reload();
  };
  const saveEditing = async () => {
    if (!editing) return;
    const result = await action.run(() =>
      editing.mode === "approve"
        ? post(`/care/relationships/${editing.rel.id}/approve`, { permissions: chosen })
        : patch(`/care/relationships/${editing.rel.id}/permissions`, { permissions: chosen }),
    );
    if (result) done();
  };
  const reject = async (rel: Relationship) => {
    if (await action.run(() => post(`/care/relationships/${rel.id}/reject`))) done();
  };
  const revoke = async () => {
    if (!revoking) return;
    if (await action.run(() => post(`/care/relationships/${revoking.id}/revoke`, {}))) done();
  };
  const showHistory = async (rel: Relationship) => {
    const events = await action.run(() => get<ConsentEvent[]>(`/care/relationships/${rel.id}/history`));
    if (events) setHistory({ rel, events });
  };

  return (
    <div>
      <PageTitle>{t("nav.careCircle")}</PageTitle>
      <p className="mb-4">{t("care.intro")}</p>
      {action.error != null && !editing && !revoking && <ErrorPanel error={action.error} />}
      {list.length === 0 && <Empty title={t("care.none")} />}

      {requested.length > 0 && <h2 className="mb-2">{t("care.requests")}</h2>}
      <div className="mb-6 space-y-3">
        {requested.map((rel) => (
          <Card key={rel.id} className="border-2 border-amber-400">
            <p className="text-xl font-semibold">{rel.caregiver.full_name}</p>
            <p className="mb-1">{t("care.asksFor")}</p>
            <ul className="mb-3 list-disc pl-6">
              {rel.requested_permissions.map((p) => <li key={p}>{t(`permission.${p}`)}</li>)}
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => { setChosen(rel.requested_permissions); setEditing({ rel, mode: "approve" }); }}>{t("care.review")}</Button>
              <Button variant="secondary" disabled={action.busy} onClick={() => reject(rel)}>{t("care.reject")}</Button>
            </div>
          </Card>
        ))}
      </div>

      {active.length > 0 && <h2 className="mb-2">{t("care.active")}</h2>}
      <div className="mb-6 space-y-3">
        {active.map((rel) => (
          <Card key={rel.id}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="text-xl font-semibold">{rel.caregiver.full_name}</p>
              <StatusBadge status={rel.status} />
            </div>
            <p className="mb-1">{t("care.canDo")}</p>
            <ul className="mb-3 list-disc pl-6">
              {rel.permissions.map((p) => <li key={p}>{t(`permission.${p}`)}</li>)}
            </ul>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => { setChosen(rel.permissions); setEditing({ rel, mode: "edit" }); }}>{t("care.changePermissions")}</Button>
              <Button variant="danger" onClick={() => setRevoking(rel)}>{t("care.revoke")}</Button>
              <Button variant="quiet" disabled={action.busy} onClick={() => showHistory(rel)}>{t("care.history")}</Button>
            </div>
          </Card>
        ))}
      </div>

      {closed.length > 0 && <h2 className="mb-2">{t("care.closed")}</h2>}
      <div className="space-y-3">
        {closed.map((rel) => (
          <Card key={rel.id}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="font-semibold">{rel.caregiver.full_name}</p>
              <StatusBadge status={rel.status} />
            </div>
            <Button variant="quiet" disabled={action.busy} onClick={() => showHistory(rel)}>{t("care.history")}</Button>
          </Card>
        ))}
      </div>

      {editing && (
        <Modal title={editing.mode === "approve" ? t("care.approveTitle", { name: editing.rel.caregiver.full_name }) : t("care.changePermissions")} onClose={() => setEditing(null)}>
          {action.error != null && <ErrorPanel error={action.error} />}
          <p className="mb-3">{t("care.consentText", { name: editing.rel.caregiver.full_name })}</p>
          <PermissionChecklist all={all} value={chosen} onChange={setChosen} idPrefix="grant" />
          <div className="flex flex-wrap gap-2">
            <Button onClick={saveEditing} disabled={action.busy || chosen.length === 0}>
              {action.busy ? t("common.pleaseWait") : editing.mode === "approve" ? t("care.approve") : t("common.save")}
            </Button>
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={action.busy}>{t("common.cancel")}</Button>
          </div>
        </Modal>
      )}
      {revoking && (
        <Modal title={t("care.revokeTitle", { name: revoking.caregiver.full_name })} onClose={() => setRevoking(null)}>
          {action.error != null && <ErrorPanel error={action.error} />}
          <p className="mb-4">{t("care.revokeExplain")}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="danger" onClick={revoke} disabled={action.busy}>{action.busy ? t("common.pleaseWait") : t("care.revoke")}</Button>
            <Button variant="secondary" onClick={() => setRevoking(null)} disabled={action.busy}>{t("common.cancel")}</Button>
          </div>
        </Modal>
      )}
      {history && (
        <Modal title={t("care.historyTitle", { name: history.rel.caregiver.full_name })} onClose={() => setHistory(null)}>
          <ol className="mb-4 space-y-2">
            {history.events.map((event, index) => (
              <li key={index}>
                <span className="font-semibold">{t(`consent.${event.action}`, { defaultValue: event.action })}</span>, {fmtDateTime(event.created_at, lang)}
                {event.permissions.length > 0 && <span className="block text-sm text-slate-700">{event.permissions.map((p) => t(`permission.${p}`)).join(", ")}</span>}
              </li>
            ))}
          </ol>
          <Button variant="secondary" onClick={() => setHistory(null)}>{t("common.close")}</Button>
        </Modal>
      )}
      {list.length > 0 && <Banner kind="info">{t("care.auditNote")}</Banner>}
    </div>
  );
}
