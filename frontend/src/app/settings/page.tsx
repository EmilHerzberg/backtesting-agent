"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AIProvider, authApi, providerApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LeakageBadge, PROVIDER_LEAKAGE } from "@/components/info-icon";
import { LeakageLegend } from "@/components/leakage-legend";

function tokenEmail(): string {
  if (typeof window === "undefined") return "";
  const t = localStorage.getItem("token");
  if (!t) return "";
  try {
    return JSON.parse(atob(t.split(".")[1] || "")).email || "";
  } catch {
    return "";
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-gray-800 bg-gray-900 p-5 space-y-4">
      <h2 className="text-sm uppercase font-semibold text-gray-400">{title}</h2>
      {children}
    </section>
  );
}

const INPUT =
  "w-full px-3 py-2 bg-gray-950 border border-gray-700 rounded outline-none focus:border-blue-500 text-sm";

export default function SettingsPage() {
  const { isLoggedIn, isInitialized, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isInitialized && !isLoggedIn) router.replace("/");
  }, [isInitialized, isLoggedIn, router]);

  if (!isInitialized) return <div className="text-center py-16 text-gray-500">Laden…</div>;
  if (!isLoggedIn) return null;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Einstellungen</h1>
      <ApiKeysSection />
      <SecuritySection onDone={() => { logout(); router.replace("/"); }} />
      <AccountSection onDeleted={() => { logout(); router.replace("/"); }} />
    </div>
  );
}

// ── API keys ──────────────────────────────────────────────────────────
function ApiKeysSection() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [providerType, setProviderType] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setProviders(await providerApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  }, []);

  useEffect(() => {
    void refresh();
    providerApi.types().then((r) => {
      setTypes(r.types);
      setProviderType((p) => p || r.types[0] || "");
    }).catch(() => {});
  }, [refresh]);

  const add = async () => {
    if (!providerType || !apiKey) return;
    setBusy(true);
    setError("");
    try {
      await providerApi.create(`${providerType} key`, providerType, apiKey);
      setApiKey("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Diesen API-Key wirklich löschen?")) return;
    try {
      await providerApi.remove(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  };

  const toggle = async (p: AIProvider) => {
    try {
      await providerApi.toggle(p.id, !p.is_active);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    }
  };

  return (
    <Section title="API-Keys">
      <p className="text-[11px] text-gray-500">
        Bevorzuge für die Strategie-Auswahl ein <b className="text-gray-300">mechanism-only</b> Reasoning-Modell:
      </p>
      <LeakageLegend />
      {providers.length === 0 ? (
        <p className="text-sm text-gray-600">Noch keine API-Keys hinterlegt.</p>
      ) : (
        <div className="space-y-2">
          {providers.map((p) => (
            <div key={p.id} className="flex items-center justify-between rounded border border-gray-800 bg-gray-950 px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm text-gray-200 flex items-center gap-2">
                  {p.name} <span className="text-gray-500">· {p.provider_type}</span>
                  <LeakageBadge state={p.leakage} />
                </div>
                <div className="font-mono text-[11px] text-gray-500">{p.api_key_masked}</div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => toggle(p)}
                  className={`text-[10px] uppercase px-2 py-0.5 rounded ${p.is_active ? "bg-green-900 text-green-300" : "bg-gray-800 text-gray-400"}`}
                >
                  {p.is_active ? "aktiv" : "inaktiv"}
                </button>
                <button onClick={() => remove(p.id)} className="text-[10px] uppercase px-2 py-0.5 rounded bg-red-900/70 text-red-200 hover:bg-red-800">
                  löschen
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <select value={providerType} onChange={(e) => setProviderType(e.target.value)} className={`${INPUT} w-40`}>
          {types.map((t) => {
            const s = PROVIDER_LEAKAGE[t];
            const tag = s === "risk" ? " ⚠ leakage risk" : s === "mechanism_only" ? " ✓ mechanism-only" : "";
            return <option key={t} value={t}>{t}{tag}</option>;
          })}
        </select>
        <input type="password" placeholder="Neuer API-Key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} className={INPUT} />
        <button onClick={add} disabled={busy || !apiKey} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-semibold disabled:opacity-40 shrink-0">
          Hinzufügen
        </button>
      </div>
      {error && <p className="text-red-400 text-sm">{error}</p>}
    </Section>
  );
}

// ── Security (change password) ────────────────────────────────────────
function SecuritySection({ onDone }: { onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError("");
    setMsg("");
    if (next.length < 8) return setError("Neues Passwort: min. 8 Zeichen");
    if (next !== confirm) return setError("Passwörter stimmen nicht überein");
    setBusy(true);
    try {
      await authApi.changePassword(current, next);
      setMsg("Passwort geändert — bitte neu anmelden.");
      setTimeout(onDone, 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Passwort ändern">
      <input type="password" placeholder="Aktuelles Passwort" value={current} onChange={(e) => setCurrent(e.target.value)} className={INPUT} />
      <input type="password" placeholder="Neues Passwort (min. 8)" value={next} onChange={(e) => setNext(e.target.value)} className={INPUT} />
      <input type="password" placeholder="Neues Passwort bestätigen" value={confirm} onChange={(e) => setConfirm(e.target.value)} className={INPUT} />
      <button onClick={submit} disabled={busy || !current || !next} className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-semibold disabled:opacity-40">
        Passwort ändern
      </button>
      {msg && <p className="text-green-400 text-sm">{msg}</p>}
      {error && <p className="text-red-400 text-sm">{error}</p>}
    </Section>
  );
}

// ── Account (email + delete) ──────────────────────────────────────────
function AccountSection({ onDeleted }: { onDeleted: () => void }) {
  const [email] = useState(tokenEmail());
  const [confirmText, setConfirmText] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const del = async () => {
    setError("");
    if (confirmText !== "DELETE") return setError('Zum Bestätigen "DELETE" eingeben');
    if (!password) return setError("Passwort erforderlich");
    if (!confirm("Konto und ALLE Daten unwiderruflich löschen?")) return;
    setBusy(true);
    try {
      await authApi.deleteAccount(password);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Konto">
      {email && <p className="text-sm text-gray-300">Angemeldet als <span className="font-mono text-gray-200">{email}</span></p>}
      <div className="rounded border border-red-900/60 bg-red-950/20 p-4 space-y-3">
        <div className="text-sm text-red-300 font-semibold">Gefahrenzone — Konto löschen</div>
        <p className="text-[12px] text-gray-400">
          Löscht dein Konto, deine API-Keys und alle Research-Läufe unwiderruflich. Nicht rückgängig zu machen.
        </p>
        <input placeholder='Zum Bestätigen "DELETE" eingeben' value={confirmText} onChange={(e) => setConfirmText(e.target.value)} className={INPUT} />
        <input type="password" placeholder="Passwort" value={password} onChange={(e) => setPassword(e.target.value)} className={INPUT} />
        <button onClick={del} disabled={busy || confirmText !== "DELETE" || !password} className="px-4 py-2 bg-red-800 hover:bg-red-700 rounded text-sm font-semibold disabled:opacity-40">
          Konto endgültig löschen
        </button>
        {error && <p className="text-red-400 text-sm">{error}</p>}
      </div>
    </Section>
  );
}
