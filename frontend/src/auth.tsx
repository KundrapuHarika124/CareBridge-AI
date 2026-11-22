// Signed-in user, plus the patient a caregiver is currently acting for.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, post, refreshSession, setAccessToken, setSessionLostHandler, type Lang, type Relationship, type User } from "./api";
import { setLanguage } from "./i18n";

export interface ActivePatient { id: string; name: string; permissions: string[]; self: boolean }

interface AuthState {
  user: User | null;
  ready: boolean;
  activePatient: ActivePatient | null;
  login: (identifier: string, password: string) => Promise<User>;
  register: (input: { full_name: string; identifier: string; password: string; role: string; preferred_language: Lang }) => Promise<User>;
  logout: () => Promise<void>;
  reloadUser: () => Promise<void>;
  chooseCaregiverPatient: (relationship: Relationship | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);
const ACTIVE_KEY = "cb_active_patient";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [caregiverPatient, setCaregiverPatient] = useState<ActivePatient | null>(null);

  const adopt = useCallback((next: User | null) => {
    setUser(next);
    if (next) setLanguage(next.preferred_language);
    if (!next) {
      setCaregiverPatient(null);
      try {
        sessionStorage.removeItem(ACTIVE_KEY);
      } catch {
        /* ignore */
      }
    }
  }, []);

  // On load, try the refresh cookie once to restore a session.
  useEffect(() => {
    let live = true;
    refreshSession().then((session) => {
      if (!live) return;
      if (session) adopt(session.user);
      setReady(true);
    });
    setSessionLostHandler(() => {
      setAccessToken(null);
      adopt(null);
    });
    return () => {
      live = false;
      setSessionLostHandler(null);
    };
  }, [adopt]);

  // A caregiver's chosen patient is re-validated against the server after a reload:
  // access may have been revoked in the meantime.
  useEffect(() => {
    if (!user || user.role !== "CAREGIVER") return;
    let remembered: string | null = null;
    try {
      remembered = sessionStorage.getItem(ACTIVE_KEY);
    } catch {
      remembered = null;
    }
    if (!remembered) return;
    get<Relationship[]>("/care/relationships")
      .then((rels) => {
        const rel = rels.find((r) => r.status === "ACTIVE" && r.patient.id === remembered);
        setCaregiverPatient(rel ? { id: rel.patient.id, name: rel.patient.full_name, permissions: rel.permissions, self: false } : null);
      })
      .catch(() => setCaregiverPatient(null));
  }, [user]);

  const value = useMemo<AuthState>(() => {
    const activePatient: ActivePatient | null =
      user?.role === "PATIENT" && user.patient_id
        ? { id: user.patient_id, name: user.full_name, permissions: [], self: true }
        : user?.role === "CAREGIVER"
          ? caregiverPatient
          : null;
    return {
      user,
      ready,
      activePatient,
      async login(identifier, password) {
        const data = await post<{ access_token: string; user: User }>("/auth/login", { identifier, password });
        setAccessToken(data.access_token);
        adopt(data.user);
        return data.user;
      },
      async register(input) {
        const data = await post<{ access_token: string; user: User }>("/auth/register", input);
        setAccessToken(data.access_token);
        adopt(data.user);
        return data.user;
      },
      async logout() {
        try {
          await post("/auth/logout");
        } finally {
          setAccessToken(null);
          adopt(null);
        }
      },
      async reloadUser() {
        setUser(await get<User>("/me"));
      },
      chooseCaregiverPatient(rel) {
        const next = rel ? { id: rel.patient.id, name: rel.patient.full_name, permissions: rel.permissions, self: false } : null;
        setCaregiverPatient(next);
        try {
          if (next) sessionStorage.setItem(ACTIVE_KEY, next.id);
          else sessionStorage.removeItem(ACTIVE_KEY);
        } catch {
          /* ignore */
        }
      },
    };
  }, [user, ready, caregiverPatient, adopt]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** True when the active patient is the user, or the caregiver holds `permission`. */
export function can(active: ActivePatient | null, permission: string): boolean {
  return !!active && (active.self || active.permissions.includes(permission));
}
