import { useTranslation } from "react-i18next";
import { get, post, type Notice } from "../api";
import { fmtDateTime } from "../lib/format";
import { Button, Card, Empty, ErrorPanel, Loading, PageTitle, useAction, useLang, useLoad } from "../ui";

export default function Notifications() {
  const { t, i18n } = useTranslation();
  const lang = useLang();
  const { data, error, loading, reload } = useLoad(() => get<Notice[]>("/me/notifications"), []);
  const action = useAction();

  const text = (notice: Notice) => {
    const key = `notice.${notice.type}`;
    if (!i18n.exists(key)) return notice.type;
    const payload = notice.payload ?? {};
    return t(key, {
      ...payload,
      when: payload.starts_at ? fmtDateTime(payload.starts_at, lang) : "",
      expires: payload.expires_at ? fmtDateTime(payload.expires_at, lang) : "",
    });
  };
  const markAll = async () => {
    if (await action.run(() => post("/me/notifications/read-all"))) reload();
  };
  const markOne = async (notice: Notice) => {
    if (await action.run(() => post(`/me/notifications/${notice.id}/read`))) reload();
  };

  const rows = data ?? [];
  const anyUnread = rows.some((n) => !n.read_at);
  return (
    <div>
      <PageTitle action={anyUnread ? <Button variant="secondary" disabled={action.busy} onClick={markAll}>{t("notice.markAll")}</Button> : undefined}>
        {t("nav.notifications")}
      </PageTitle>
      <p className="mb-4 text-sm text-slate-700">{t("notice.inAppOnly")}</p>
      {loading && <Loading />}
      {error != null && <ErrorPanel error={error} onRetry={reload} />}
      {action.error != null && <ErrorPanel error={action.error} />}
      {!loading && error == null && rows.length === 0 && <Empty title={t("notice.none")} />}
      <ul className="space-y-3">
        {rows.map((notice) => (
          <li key={notice.id}>
            <Card className={notice.read_at ? "" : "border-2 border-brand-600"}>
              <p className={notice.read_at ? "" : "font-semibold"}>{text(notice)}</p>
              <p className="text-sm text-slate-700">
                {fmtDateTime(notice.created_at, lang)}
                {!notice.read_at && <span className="ml-2 font-semibold">{t("notice.unread")}</span>}
              </p>
              {!notice.read_at && <Button variant="quiet" disabled={action.busy} onClick={() => markOne(notice)}>{t("notice.markRead")}</Button>}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
