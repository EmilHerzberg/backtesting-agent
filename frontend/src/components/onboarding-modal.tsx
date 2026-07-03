"use client";

import { useState } from "react";
import { providerApi } from "@/lib/api";
import { LeakageLegend } from "./leakage-legend";
import { PROVIDER_LEAKAGE } from "./info-icon";

// First-login onboarding (F-1/F-2): explain rule-based vs AI modes, show the leakage legend, and let the user
// add a key inline or skip (add later in Settings). Rule-based never blocked (C-1).
export function OnboardingModal({
  types,
  onDone,
  onSkip,
}: {
  types: string[];
  onDone: () => void;
  onSkip: () => void;
}) {
  const [providerType, setProviderType] = useState(types[0] || "deepseek");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (!apiKey) return;
    setBusy(true);
    setError("");
    try {
      await providerApi.create(`${providerType} key`, providerType, apiKey);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Fehler");
      setBusy(false);
    }
  };

  const tag = (t: string) =>
    PROVIDER_LEAKAGE[t] === "mechanism_only" ? " ✓ mechanism-only"
      : PROVIDER_LEAKAGE[t] === "risk" ? " ⚠ leakage risk" : "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-gray-800 bg-gray-900 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold text-gray-100">Willkommen beim Backtesting-Agent</h2>
        <p className="text-sm text-gray-400">
          Der Agent sucht autonom nach Handelsstrategien. Der <b className="text-gray-200">regelbasierte Modus</b> läuft
          kostenlos ganz ohne API-Key. Für die <b className="text-gray-200">KI-Modi</b> (LLM-Strategist / Critic)
          brauchst du einen AI-API-Key — den kannst du jetzt hinterlegen oder jederzeit in den Einstellungen.
        </p>

        <div>
          <div className="text-xs uppercase font-semibold text-gray-500 mb-1">Welches Modell?</div>
          <LeakageLegend />
        </div>

        <div className="space-y-2">
          <div className="text-xs uppercase font-semibold text-gray-500">API-Key hinzufügen (optional)</div>
          <div className="flex gap-2">
            <select
              value={providerType}
              onChange={(e) => setProviderType(e.target.value)}
              className="w-44 px-3 py-2 bg-gray-950 border border-gray-700 rounded text-sm outline-none"
            >
              {types.map((t) => <option key={t} value={t}>{t}{tag(t)}</option>)}
            </select>
            <input
              type="password"
              placeholder="API-Key einfügen"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="flex-1 px-3 py-2 bg-gray-950 border border-gray-700 rounded text-sm outline-none"
            />
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
        </div>

        <div className="flex items-center justify-between pt-2">
          <button onClick={onSkip} className="text-sm text-gray-400 hover:text-gray-200">
            Später (in Einstellungen)
          </button>
          <button
            onClick={save}
            disabled={busy || !apiKey}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-semibold disabled:opacity-40"
          >
            Key speichern &amp; los
          </button>
        </div>
      </div>
    </div>
  );
}
