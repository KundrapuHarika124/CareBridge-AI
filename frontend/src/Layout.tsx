import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { get, patch, type Lang, type Notice, type Role } from "./api";
import { useAuth } from "./auth";
import { setLanguage } from "./i18n";
import { useLang } from "./ui";

const NAV: Record<Role, { to: string; key: string }[]> = {
  PATIENT: [
    { to: "/home", key: "nav.home" },
    { to: "/discover", key: "nav.discover" },
    { to: "/appointments", key: "nav.appointments" },
    { to: "/care-circle", key: "nav.careCircle" },
    { to: "/settings", key: "nav.settings" },
  ],
  CAREGIVER: [
    { to: "/home", key: "nav.home" },
    { to: "/discover", key: "nav.discover" },
    { to: "/appointments", key: "nav.appointments" },
    { to: "/patients", key: "nav.patients" },
    { to: "/settings", key: "nav.settings" },
  ],
  DOCTOR: [
    { to: "/doctor", key: "nav.schedule" },
    { to: "/settings", key: "nav.settings" },
  ],
  HOSPITAL_ADMIN: [
    { to: "/admin", key: "nav.overview" },
    { to: "/admin/doctors", key: "nav.doctors" },
    { to: "/admin/schedules", key: "nav.schedules" },
    { to: "/admin/appointments", key: "nav.appointments" },
    { to: "/admin/departments", key: "nav.departments" },
    { to: "/settings", key: "nav.settings" },
  ],
  SUPER_ADMIN: [
    { to: "/superadmin", key: "nav.superAdmin" },
    { to: "/settings", key: "nav.settings" },
  ],
};

export function LanguageSwitch({ onChange }: { onChange?: (lang: Lang) => void }) {
  const { t } = useTranslation();
  const lang = useLang();
  const choose = (next: Lang) => {
    setLanguage(next);
    onChange?.(next);
  };
  return (
    <div role="group" aria-label={t("common.language")} className="inline-flex overflow-hidden rounded-lg border border-slate-400">
      {(["te", "en"] as Lang[]).map((code) => (
        <button
          key={code}
          type="button"
          lang={code}
          aria-pressed={lang === code}
          onClick={() => choose(code)}
          className={`px-3 py-2 text-base font-semibold ${lang === code ? "bg-brand-600 text-white" : "bg-white text-slate-800"}`}
        >
          {code === "te" ? "తెలుగు" : "English"}
        </button>
      ))}
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout, activePatient } = useAuth();
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const comfort = user?.role === "PATIENT" || user?.role === "CAREGIVER";

  // Poll the unread count. Failures are ignored here; the Notifications page reports them.
  useEffect(() => {
    if (!user) return;
    let live = true;
    const load = () =>
      get<Notice[]>("/me/notifications?unread_only=true")
        .then((rows) => live && setUnread(rows.length))
        .catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [user]);

  if (!user) return null;
  const items = NAV[user.role] ?? [];
  const saveLanguage = (lang: Lang) => {
    patch("/me", { preferred_language: lang }).catch(() => undefined);
  };
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex min-h-[3rem] flex-1 items-center justify-center rounded-lg px-3 py-2 text-center font-semibold md:flex-none ${
      isActive ? "bg-brand-600 text-white" : "text-slate-800 hover:bg-brand-50"
    }`;

  return (
    <div className={`min-h-screen pb-24 md:pb-0 ${comfort ? "comfort" : ""}`}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-white focus:p-2">
        {t("common.skipToContent")}
      </a>
      <p className="bg-amber-100 px-4 py-1 text-center text-sm text-amber-900">{t("common.demoBanner")}</p>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to="/" className="text-xl font-bold text-brand-700">CareBridge AI</Link>
          <div className="flex flex-wrap items-center gap-2">
            <LanguageSwitch onChange={saveLanguage} />
            <Link to="/notifications" className="btn btn-secondary" aria-label={t("nav.notificationsCount", { count: unread })}>
              {t("nav.notifications")}
              {unread > 0 && <span className="rounded-full bg-red-700 px-2 text-sm text-white">{unread}</span>}
            </Link>
            <button
              type="button"
              className="btn btn-quiet"
              onClick={() => logout().finally(() => navigate("/login"))}
            >
              {t("nav.signOut")}
            </button>
          </div>
        </div>
        {user.role === "CAREGIVER" && (
          <div className={`px-4 py-2 text-center font-semibold ${activePatient ? "bg-brand-100 text-brand-800" : "bg-slate-100"}`} role="status">
            {activePatient ? t("care.actingFor", { name: activePatient.name }) : t("care.noPatientChosen")}{" "}
            <Link to="/patients" className="underline">{t("care.change")}</Link>
          </div>
        )}
      </header>
      <nav
        aria-label={t("nav.main")}
        className="fixed inset-x-0 bottom-0 z-40 flex gap-1 border-t border-slate-200 bg-white p-2 md:static md:mx-auto md:max-w-5xl md:justify-start md:border-0 md:bg-transparent md:px-4"
      >
        {items.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/admin"} className={linkClass}>
            {t(item.key)}
          </NavLink>
        ))}
      </nav>
      <main id="main" className="mx-auto max-w-5xl px-4 py-4">{children}</main>
    </div>
  );
}
