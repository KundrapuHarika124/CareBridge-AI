// Date and time display. The API speaks UTC; this prototype always displays Asia/Kolkata.
import type { Lang } from "../api";

const ZONE = "Asia/Kolkata";
const locale = (lang: Lang) => (lang === "te" ? "te-IN" : "en-IN");

export function fmtDateTime(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(locale(lang), {
    timeZone: ZONE, weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true,
  }).format(new Date(iso));
}

export function fmtDate(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(locale(lang), { timeZone: ZONE, weekday: "long", day: "numeric", month: "long" }).format(new Date(iso));
}

export function fmtTime(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(locale(lang), { timeZone: ZONE, hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso));
}

/** Calendar date (YYYY-MM-DD) in IST for a moment in time. */
export function istDate(value: Date | string = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(
    typeof value === "string" ? new Date(value) : value,
  );
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

/** Group slots by their IST calendar date, keeping order. */
export function groupByDay<T extends { starts_at: string }>(items: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const day = istDate(item.starts_at);
    groups.set(day, [...(groups.get(day) ?? []), item]);
  }
  return [...groups.entries()];
}

export function pickName(item: { name_en: string; name_te: string }, lang: Lang): string {
  return lang === "te" ? item.name_te : item.name_en;
}

export function rupees(amount: number | null): string {
  return amount === null ? "" : `₹${amount.toFixed(0)}`;
}
