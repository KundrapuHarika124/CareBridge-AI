import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { patch, post, setAccessToken, type User } from "../api";
import { useAuth } from "../auth";
import { Banner, Button, Card, ErrorPanel, Field, PageTitle, useAction } from "../ui";

export default function Settings() {
  const { t } = useTranslation();
  const { user, reloadUser } = useAuth();
  const profile = useAction();
  const password = useAction();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [dob, setDob] = useState(user?.patient_profile?.date_of_birth ?? "");
  const [notes, setNotes] = useState(user?.patient_profile?.accessibility_notes ?? "");
  const [profileSaved, setProfileSaved] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);
  if (!user) return null;

  const saveProfile = async (event: FormEvent) => {
    event.preventDefault();
    setProfileSaved(false);
    const body: Record<string, unknown> = { full_name: fullName.trim() };
    if (user.role === "PATIENT") {
      if (dob) body.date_of_birth = dob;
      body.accessibility_notes = notes;
    }
    const result = await profile.run(() => patch<User>("/me", body));
    if (result) {
      await reloadUser();
      setProfileSaved(true);
    }
  };
  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setPasswordSaved(false);
    const result = await password.run(() => post<{ access_token: string }>("/auth/change-password", { current_password: current, new_password: next }));
    if (result) {
      setAccessToken(result.access_token);
      setCurrent("");
      setNext("");
      setPasswordSaved(true);
    }
  };

  return (
    <div>
      <PageTitle>{t("nav.settings")}</PageTitle>
      <Card className="mb-4">
        <h2 className="mb-3">{t("settings.profile")}</h2>
        {profile.error != null && <ErrorPanel error={profile.error} />}
        {profileSaved && <Banner kind="success">{t("settings.saved")}</Banner>}
        <form onSubmit={saveProfile}>
          <Field label={t("auth.fullName")}>
            {(id) => <input id={id} className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} maxLength={120} autoComplete="name" />}
          </Field>
          <p className="mb-4">{t("settings.signInId")}: <span className="font-semibold">{user.phone ?? user.email}</span></p>
          {user.role === "PATIENT" && (
            <>
              <Field label={t("settings.dob")}>
                {(id) => <input id={id} type="date" className="input" value={dob} onChange={(e) => setDob(e.target.value)} />}
              </Field>
              <Field label={t("settings.accessNotes")} hint={t("settings.accessNotesHint")}>
                {(id) => <textarea id={id} className="input" rows={2} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />}
              </Field>
            </>
          )}
          <Button type="submit" disabled={profile.busy}>{profile.busy ? t("common.pleaseWait") : t("common.save")}</Button>
        </form>
      </Card>

      <Card>
        <h2 className="mb-3">{t("settings.changePassword")}</h2>
        {password.error != null && <ErrorPanel error={password.error} />}
        {passwordSaved && <Banner kind="success">{t("settings.passwordChanged")}</Banner>}
        <form onSubmit={changePassword}>
          <Field label={t("settings.currentPassword")}>
            {(id) => <input id={id} type="password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" />}
          </Field>
          <Field label={t("settings.newPassword")} hint={t("auth.passwordHint")}>
            {(id) => <input id={id} type="password" className="input" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} autoComplete="new-password" />}
          </Field>
          <Button type="submit" disabled={password.busy}>{password.busy ? t("common.pleaseWait") : t("settings.changePassword")}</Button>
        </form>
        <p className="mt-3 text-sm text-slate-700">{t("settings.noReset")}</p>
      </Card>
    </div>
  );
}
