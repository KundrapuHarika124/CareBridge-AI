// Small shared components and hooks. Plain elements with accessible defaults.
import { useCallback, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, type Lang } from "./api";
import { currentLanguage } from "./i18n";

export function useLang(): Lang {
  useTranslation(); // re-render when the language changes
  return currentLanguage();
}

/** Message for an error: a translated text for known codes, otherwise the server's message. */
export function useErrorText(): (error: unknown) => string {
  const { t, i18n } = useTranslation();
  return useCallback(
    (error: unknown) => {
      if (error instanceof ApiError) {
        const key = `errors.${error.code}`;
        return i18n.exists(key) ? t(key) : error.message || t("errors.GENERIC");
      }
      return t("errors.GENERIC");
    },
    [t, i18n],
  );
}

/** Load data for a screen, with loading and error states and a reload function. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    loader()
      .then((value) => {
        if (live) {
          setData(value);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (live) {
          setError(err);
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Run an action with busy and error state. Returns [run, busy, error, clearError]. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (err) {
      setError(err);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { run, busy, error, clear: () => setError(null) };
}

type Variant = "primary" | "secondary" | "quiet" | "danger";
export function Button({ variant = "primary", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type="button" {...rest} className={`btn btn-${variant} ${className}`} />;
}

export function Card({ children, className = "", ...rest }: React.HTMLAttributes<HTMLElement>) {
  return <section {...rest} className={`card ${className}`}>{children}</section>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="mb-4">
      <label className="label" htmlFor={id}>{label}</label>
      {children(id)}
      {hint && <p className="mt-1 text-sm text-slate-600">{hint}</p>}
    </div>
  );
}

const BANNER = {
  info: "border-sky-300 bg-sky-50 text-sky-900",
  success: "border-green-300 bg-green-50 text-green-900",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
  error: "border-red-300 bg-red-50 text-red-900",
};
export function Banner({ kind = "info", children }: { kind?: keyof typeof BANNER; children: ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`mb-4 rounded-lg border px-4 py-3 ${BANNER[kind]}`}>
      {children}
    </div>
  );
}

export function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" className="space-y-3 py-4">
      <span className="sr-only">{t("common.loading")}</span>
      <div className="h-6 w-2/3 rounded bg-slate-200" />
      <div className="h-20 rounded bg-slate-200" />
      <div className="h-20 rounded bg-slate-200" />
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center">
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const text = useErrorText();
  const requestId = error instanceof ApiError ? error.requestId : "";
  return (
    <div role="alert" className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900">
      <p className="font-semibold">{text(error)}</p>
      {onRetry && <Button variant="secondary" className="mt-3" onClick={onRetry}>{t("common.retry")}</Button>}
      {requestId && <p className="mt-2 text-xs text-red-800">{t("common.reference")}: {requestId}</p>}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  CONFIRMED: "bg-green-100 text-green-900",
  PENDING: "bg-amber-100 text-amber-900",
  COMPLETED: "bg-slate-200 text-slate-900",
  CANCELLED: "bg-red-100 text-red-900",
  NO_SHOW: "bg-red-100 text-red-900",
  RESCHEDULED: "bg-slate-200 text-slate-900",
  AVAILABLE: "bg-green-100 text-green-900",
  BOOKED: "bg-sky-100 text-sky-900",
  BLOCKED: "bg-slate-200 text-slate-900",
  HELD: "bg-amber-100 text-amber-900",
  ACTIVE: "bg-green-100 text-green-900",
  REQUESTED: "bg-amber-100 text-amber-900",
  REJECTED: "bg-red-100 text-red-900",
  REVOKED: "bg-slate-200 text-slate-900",
  OFFERED: "bg-amber-100 text-amber-900",
};
/** Status is always shown as a word, never by colour alone. */
export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${STATUS_STYLE[status] ?? "bg-slate-200 text-slate-900"}`}>
      {t(`status.${status}`, { defaultValue: status })}
    </span>
  );
}

export function SimTag() {
  const { t } = useTranslation();
  return <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">{t("common.simulated")}</span>;
}

/** Modal dialog with focus moved in on open, Escape to close, and focus returned on close. */
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-full max-w-lg rounded-xl bg-white p-5 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className="mb-3">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function PageTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1>{children}</h1>
      {action}
    </div>
  );
}
