// Conversation with the booking assistant. Every reply shown here comes from the backend;
// nothing is generated in the browser. Voice appears only when a real speech provider is
// configured, and typing plus buttons always work.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { get, post, type AssistantReply, type Lang } from "../api";
import { can, useAuth } from "../auth";
import { fmtDateTime } from "../lib/format";
import {
  cancelListening,
  isBrowserRecognitionSupported,
  isBrowserSynthesisSupported,
  recognizeOnce,
  speak,
  SpeechError,
  stopSpeaking,
} from "../lib/speech";
import { Banner, Button, Card, Empty, ErrorPanel, Loading, PageTitle, useAction, useLang, useLoad } from "../ui";

interface Line { who: "assistant" | "you"; text: string }
interface Status { assistant: { mode: "ai" | "guided" }; speech: { available: boolean; provider: string } }

export default function Assistant() {
  const { t } = useTranslation();
  const lang = useLang();
  const { user, activePatient } = useAuth();
  const [last, setLast] = useState<AssistantReply | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [runId, setRunId] = useState(0);
  const turn = useAction();
  const logEnd = useRef<HTMLDivElement>(null);

  const status = useLoad<Status>(async () => {
    const [assistant, speech] = await Promise.all([
      get<{ mode: "ai" | "guided" }>("/assistant/status"),
      get<{ available: boolean; provider: string }>("/speech/status").catch(() => ({ available: false, provider: "none" })),
    ]);
    return { assistant, speech };
  }, []);
  const voiceOn = (!!status.data && status.data.speech.available && status.data.speech.provider === "azure")
    || isBrowserRecognitionSupported()
    || isBrowserSynthesisSupported();

  const start = useLoad<AssistantReply | null>(async () => {
    if (user?.role === "CAREGIVER" && !activePatient) return null;
    const body: { language: Lang; patient_id?: string } = { language: lang };
    if (activePatient && !activePatient.self) body.patient_id = activePatient.id;
    return post<AssistantReply>("/assistant/sessions", body);
    // The language at session start is deliberate: switching language later is sent per turn.
  }, [activePatient?.id, runId]);

  const adopt = (reply: AssistantReply, said?: string) => {
    setLast(reply);
    setLines((prev) => [...prev, ...(said ? [{ who: "you" as const, text: said }] : []), { who: "assistant" as const, text: reply.reply }]);
    if (voiceOn && speakReplies) speak(reply.reply, reply.language).catch(() => setVoiceNote(t("assistant.voiceOutFailed")));
  };

  useEffect(() => {
    if (start.data) {
      setLines([]);
      adopt(start.data);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start.data]);
  useEffect(() => {
    logEnd.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length]);
  useEffect(() => () => { cancelListening(); stopSpeaking(); }, []);

  const send = async (body: Record<string, unknown>, said: string) => {
    if (!last) return;
    stopSpeaking();
    const reply = await turn.run(() => post<AssistantReply>(`/assistant/sessions/${last.session_id}/turns`, { ...body, language: lang }));
    if (reply) adopt(reply, said);
  };
  const sendText = () => {
    const value = text.trim();
    if (!value) return;
    setText("");
    send({ text: value, input_mode: "TEXT" }, value);
  };
  const confirm = async () => {
    if (!last?.confirmation) return;
    const token = last.confirmation.token;
    const reply = await turn.run(() => post<AssistantReply>(`/assistant/sessions/${last.session_id}/confirm`, { token }));
    if (reply) adopt(reply, t("assistant.confirmed"));
  };
  const listen = async () => {
    if (listening) {
      cancelListening();
      setListening(false);
      return;
    }
    setVoiceNote(null);
    stopSpeaking();
    setListening(true);
    try {
      const heard = await recognizeOnce(lang);
      setText(heard.text);
      setVoiceNote(t("assistant.voiceTranscriptReady"));
    } catch (error) {
      const kind = error instanceof SpeechError ? error.kind : "FAILED";
      setVoiceNote(t(`assistant.voice.${kind}`));
    } finally {
      setListening(false);
    }
  };

  if (!can(activePatient, "BOOK_APPOINTMENTS") && activePatient) return <Banner kind="warning">{t("care.noBookingPermission")}</Banner>;
  if (user?.role === "CAREGIVER" && !activePatient) {
    return <Empty title={t("care.choosePatientFirst")}><Link className="btn btn-primary" to="/patients">{t("nav.patients")}</Link></Empty>;
  }

  const ended = !!last?.ended;
  return (
    <div>
      <PageTitle action={<Link to="/book" className="btn btn-secondary">{t("home.bookManually")}</Link>}>{t("assistant.title")}</PageTitle>
      {status.data?.assistant.mode === "guided" && <Banner kind="info">{t("assistant.guidedMode")}</Banner>}
      {status.data && !voiceOn && <Banner kind="info">{t("assistant.voiceOff")}</Banner>}
      {activePatient && !activePatient.self && <Banner kind="info">{t("care.actingFor", { name: activePatient.name })}</Banner>}
      {start.loading && <Loading />}
      {start.error != null && <ErrorPanel error={start.error} onRetry={start.reload} />}
      {last?.emergency && <Banner kind="error">{t("book.emergency")}</Banner>}

      {last && (
        <>
          <div role="log" aria-live="polite" aria-label={t("assistant.conversation")} className="mb-4 max-h-[50vh] space-y-3 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4">
            {lines.map((line, index) => (
              <div key={index} className={line.who === "you" ? "text-right" : ""}>
                <p className="text-sm font-semibold text-slate-600">{line.who === "you" ? t("assistant.you") : t("assistant.name")}</p>
                <p className={`inline-block whitespace-pre-line rounded-lg px-3 py-2 text-left ${line.who === "you" ? "bg-brand-50" : "bg-slate-100"}`}>{line.text}</p>
              </div>
            ))}
            <div ref={logEnd} />
          </div>

          {turn.error != null && <ErrorPanel error={turn.error} />}
          {voiceNote && <Banner kind="warning">{voiceNote}</Banner>}

          {last.confirmation && !ended && (
            <Card className="mb-4 border-2 border-brand-600">
              <h2 className="mb-2">{t("book.checkDetails")}</h2>
              {last.confirmation.patient_name && <p>{t("appt.patient")}: {last.confirmation.patient_name}</p>}
              <p>{last.confirmation.slot.doctor}</p>
              <p>{last.confirmation.slot.hospital}, {last.confirmation.slot.locality}</p>
              <p className="text-xl font-semibold">{fmtDateTime(last.confirmation.slot.starts_at, lang)}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={confirm} disabled={turn.busy}>{turn.busy ? t("common.pleaseWait") : t("book.confirm")}</Button>
                <Button variant="secondary" disabled={turn.busy} onClick={() => send({ option_value: "no", input_mode: "BUTTON" }, t("assistant.notThis"))}>
                  {t("assistant.notThis")}
                </Button>
              </div>
            </Card>
          )}

          {last.appointment && (
            <Card className="mb-4">
              <Banner kind="success">{t("book.success")}</Banner>
              <p className="text-xl font-semibold">{fmtDateTime(last.appointment.starts_at, lang)}</p>
              <p>{last.appointment.doctor_name}</p>
              <p>{last.appointment.hospital.name}, {last.appointment.hospital.locality}</p>
              <Link to={`/appointments/${last.appointment.id}`} className="btn btn-primary mt-3">{t("book.addDetails")}</Link>
            </Card>
          )}

          {!ended && !last.confirmation && last.options.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {last.options.map((option) => (
                <Button key={option.value} variant="secondary" disabled={turn.busy}
                  onClick={() => send({ option_value: option.value, input_mode: "BUTTON" }, option.label)}>
                  {option.label}
                </Button>
              ))}
            </div>
          )}

          {!ended ? (
            <form onSubmit={(e) => { e.preventDefault(); sendText(); }} className="flex flex-wrap items-end gap-2">
              {voiceOn && (
                <Button onClick={listen} disabled={listening || turn.busy} aria-pressed={listening} className="min-w-[8rem]">
                  <span aria-hidden="true">🎙</span> {listening ? t("assistant.listening") : t("assistant.speak")}
                </Button>
              )}
              <div className="min-w-[12rem] flex-1">
                <label className="label" htmlFor="assistant-text">{t("assistant.typeHere")}</label>
                <input id="assistant-text" className="input" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} autoComplete="off" />
              </div>
              <Button type="submit" disabled={turn.busy || !text.trim()}>{turn.busy ? t("common.pleaseWait") : t("assistant.send")}</Button>
            </form>
          ) : (
            <Button variant="secondary" onClick={() => { setLast(null); setRunId((n) => n + 1); }}>{t("assistant.startAgain")}</Button>
          )}

          {voiceOn && (
            <label className="mt-4 flex items-center gap-2">
              <input type="checkbox" className="h-5 w-5" checked={speakReplies}
                onChange={(e) => { setSpeakReplies(e.target.checked); if (!e.target.checked) stopSpeaking(); }} />
              {t("assistant.readAloud")}
            </label>
          )}
          <p className="mt-4 text-sm text-slate-600">{t("assistant.disclaimer")}</p>
        </>
      )}
    </div>
  );
}
