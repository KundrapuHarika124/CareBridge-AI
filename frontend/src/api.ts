// Typed API client. The access token lives in memory only; the refresh token is an
// HttpOnly cookie the browser sends to /api/v1/auth. On a 401 the client refreshes once.

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export type Lang = "te" | "en" | "hi" | "ta" | "kn" | "ml" | "bn" | "mr" | "gu" | "pa" | "ur";
export type Role = "PATIENT" | "CAREGIVER" | "DOCTOR" | "HOSPITAL_ADMIN" | "SUPER_ADMIN";

export interface User {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  role: Role;
  preferred_language: Lang;
  patient_id: string | null;
  doctor_id: string | null;
  hospital_ids: string[];
  patient_profile?: { date_of_birth: string | null; sex: string | null; accessibility_notes: string | null };
}
export interface Specialty { id: string; code: string; name_en: string; name_te: string }
export interface Hospital {
  id: string;
  name: string;
  locality: string;
  city: string;
  address: string;
  phone: string;
  is_simulated: boolean;
  latitude?: number | null;
  longitude?: number | null;
  is_approved?: boolean;
  distance_km?: number;
}
export interface Slot { id: string; affiliation_id: string; starts_at: string; ends_at: string; status: string }
export interface DoctorCard {
  affiliation_id: string;
  doctor_id: string;
  doctor_name: string;
  qualifications: string;
  years_experience: number | null;
  verification_status: string;
  specialty: Specialty;
  hospital: Hospital;
  department: { id: string; name: string };
  consultation_fee: number | null;
  is_active: boolean;
  next_slots: Slot[];
}
export interface Appointment {
  id: string;
  status: string;
  slot_id: string;
  affiliation_id: string;
  starts_at: string;
  ends_at: string;
  patient: { id: string; full_name: string };
  doctor_name: string;
  specialty: Specialty;
  hospital: Hospital;
  consultation_fee: number | null;
  reason_text?: string | null;
  cancel_reason: string | null;
  rescheduled_from_id: string | null;
  viewer?: "SELF" | "CAREGIVER" | "DOCTOR" | "ADMIN";
  caregiver_permissions?: string[];
  has_intake?: boolean;
  has_summary?: boolean;
  has_follow_up?: boolean;
}
export interface Relationship {
  id: string;
  status: "REQUESTED" | "ACTIVE" | "REJECTED" | "REVOKED";
  caregiver: { id: string; full_name: string };
  patient: { id: string; full_name: string };
  requested_permissions: string[];
  permissions: string[];
  requested_at: string;
}
export interface ConsentEvent { action: string; permissions: string[]; consent_text_version: string; created_at: string }
export interface Notice { id: string; type: string; payload: Record<string, string>; read_at: string | null; created_at: string }
export interface Suggestion { specialty: Specialty; explanation_en: string; explanation_te: string; review_status: string }
export interface Concern { concern_key: string; label_en: string; label_te: string }
export interface AssistantOption { label: string; value: string }
export interface AssistantReply {
  session_id: string;
  state: string;
  language: Lang;
  reply: string;
  options: AssistantOption[];
  confirmation: { token: string; expires_at: string; patient_name: string | null; slot: { slot_id: string; doctor: string; hospital: string; locality: string; starts_at: string } } | null;
  appointment: Appointment | null;
  ai_used: boolean;
  emergency: boolean;
  ended: boolean;
}
export interface Intake {
  questionnaire: { id: string; title_en: string; title_te: string; questions: { key: string; text_en: string; text_te: string }[]; review_status: string } | null;
  answers: Record<string, string>;
  submitted_at: string | null;
  can_edit: boolean;
}
export interface Summary {
  content: Record<string, string>;
  source: string;
  label: string;
  model_name: string;
  created_at: string;
  patient_edited: boolean;
  patient_reviewed_at: string | null;
  clinician_correction: string | null;
}
export interface FollowUp { instructions_text: string; next_visit_date: string | null; updated_at: string; label: string }
export interface Note { note_text: string; updated_at: string; label: string }
export interface Schedule { id: string; weekday: number; start_time: string; end_time: string; slot_minutes: number }
export interface WaitEntry { id: string; status: string; patient_id: string; created_at: string; doctor: DoctorCard }
export interface WaitOffer { id: string; entry_id: string; patient_id: string; status: string; expires_at: string; slot: Slot; doctor_name: string; hospital_name: string }
export interface Overview {
  active_doctors: number;
  appointments_today: number;
  upcoming_confirmed: number;
  cancelled_last_7_days: number;
  open_slots_next_7_days: number;
  waiting_list: number;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  requestId: string;
  constructor(status: number, code: string, message: string, details: unknown = null, requestId = "") {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

let accessToken: string | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler;
}

async function send(method: string, path: string, body?: unknown, extraHeaders?: Record<string, string>): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  try {
    return await fetch(BASE + path, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Could not reach the server.");
  }
}

async function parse<T>(response: Response): Promise<T> {
  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok && payload && "data" in payload) return payload.data as T;
  const err = payload?.error;
  const code = err?.code ?? (response.status >= 500 ? "SERVER_UNAVAILABLE" : "HTTP_ERROR");
  throw new ApiError(response.status, code, err?.message ?? "Request failed.", err?.details ?? null, payload?.meta?.request_id ?? "");
}

let refreshing: Promise<{ access_token: string; user: User } | null> | null = null;

/** Exchange the refresh cookie for a new access token. Returns null when not signed in. */
export function refreshSession(): Promise<{ access_token: string; user: User } | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await send("POST", "/auth/refresh", undefined, { "X-Requested-With": "carebridge" });
        const data = await parse<{ access_token: string; user: User }>(response);
        accessToken = data.access_token;
        return data;
      } catch {
        accessToken = null;
        return null;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

export async function api<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  let response = await send(method, path, body, headers);
  const isAuthCall = path.startsWith("/auth/login") || path.startsWith("/auth/register") || path.startsWith("/auth/refresh");
  if (response.status === 401 && !isAuthCall) {
    const renewed = await refreshSession();
    if (renewed) {
      response = await send(method, path, body, headers);
    } else if (onSessionLost) {
      onSessionLost();
    }
  }
  return parse<T>(response);
}

export const get = <T,>(path: string) => api<T>("GET", path);
export const post = <T,>(path: string, body?: unknown, headers?: Record<string, string>) => api<T>("POST", path, body ?? {}, headers);
export const put = <T,>(path: string, body: unknown) => api<T>("PUT", path, body);
export const patch = <T,>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const del = <T,>(path: string) => api<T>("DELETE", path);

/** A fresh key per user action, so an automatic retry cannot create a second booking. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}
