import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { Lang } from "../api";
import { homePath } from "../App";
import { useAuth } from "../auth";
import { LanguageSwitch } from "../Layout";
import { Banner, Button, ErrorPanel, Field, useAction, useLang } from "../ui";

function Shell({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="comfort mx-auto max-w-md px-4 py-6">
      <p className="mb-4 rounded bg-amber-100 px-3 py-2 text-center text-sm text-amber-900">{t("common.demoBanner")}</p>
      <div className="mb-6 flex items-center justify-between gap-3">
        <p className="text-2xl font-bold text-brand-700">CareBridge AI</p>
        <LanguageSwitch />
      </div>
      <main>
        <h1 className="mb-4">{title}</h1>
        {children}
      </main>
    </div>
  );
}

export function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const { run, busy, error } = useAction();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const user = await run(() => login(identifier, password));
    if (user) navigate(homePath(user.role), { replace: true });
  };

  return (
    <Shell title={t("auth.signIn")}>
      {error != null && <ErrorPanel error={error} />}
      <form onSubmit={submit} noValidate>
        <Field label={t("auth.identifier")} hint={t("auth.identifierHint")}>
          {(id) => <input id={id} className="input" autoComplete="username" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required />}
        </Field>
        <Field label={t("auth.password")}>
          {(id) => <input id={id} className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />}
        </Field>
        <Button type="submit" className="w-full" disabled={busy || !identifier || !password}>
          {busy ? t("common.pleaseWait") : t("auth.signIn")}
        </Button>
      </form>
      <p className="mt-6 text-center">
        {t("auth.noAccount")} <Link className="font-semibold text-brand-700 underline" to="/register">{t("auth.createAccount")}</Link>
      </p>
      <Banner kind="info">
        <p className="mt-1 text-base">{t("auth.demoHint")}</p>
      </Banner>
    </Shell>
  );
}

export function Register() {
  const { t } = useTranslation();
  const { register } = useAuth();
  const navigate = useNavigate();
  const lang = useLang();
  const { run, busy, error } = useAction();
  const [form, setForm] = useState({ full_name: "", identifier: "", password: "", role: "PATIENT" });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const user = await run(() => register({ ...form, preferred_language: lang as Lang }));
    if (user) navigate(homePath(user.role), { replace: true });
  };

  return (
    <Shell title={t("auth.createAccount")}>
      {error != null && <ErrorPanel error={error} />}
      <form onSubmit={submit} noValidate>
        <fieldset className="mb-4">
          <legend className="label">{t("auth.iAm")}</legend>
          <div className="grid grid-cols-2 gap-2">
            {["PATIENT", "CAREGIVER"].map((role) => (
              <label key={role} className={`btn cursor-pointer ${form.role === role ? "btn-primary" : "btn-secondary"}`}>
                <input type="radio" name="role" className="sr-only" value={role} checked={form.role === role} onChange={set("role")} />
                {t(`role.${role}`)}
              </label>
            ))}
          </div>
          {form.role === "CAREGIVER" && <p className="mt-2 text-base text-slate-700">{t("auth.caregiverNote")}</p>}
        </fieldset>
        <Field label={t("auth.fullName")}>
          {(id) => <input id={id} className="input" autoComplete="name" value={form.full_name} onChange={set("full_name")} required />}
        </Field>
        <Field label={t("auth.identifier")} hint={t("auth.identifierHint")}>
          {(id) => <input id={id} className="input" autoComplete="username" value={form.identifier} onChange={set("identifier")} required />}
        </Field>
        <Field label={t("auth.password")} hint={t("auth.passwordHint")}>
          {(id) => <input id={id} className="input" type="password" autoComplete="new-password" value={form.password} onChange={set("password")} required />}
        </Field>
        <p className="mb-4 text-base text-slate-700">{t("auth.syntheticOnly")}</p>
        <Button type="submit" className="w-full" disabled={busy || !form.full_name || !form.identifier || !form.password}>
          {busy ? t("common.pleaseWait") : t("auth.createAccount")}
        </Button>
      </form>
      <p className="mt-6 text-center">
        {t("auth.haveAccount")} <Link className="font-semibold text-brand-700 underline" to="/login">{t("auth.signIn")}</Link>
      </p>
    </Shell>
  );
}
