"use client";

import { useState } from "react";

// The 3-state leakage legend (F-4): always-visible short lines + an expandable "what do these mean?".
// Grounded in docs/bt-agent/LEAKAGE-CLASSIFICATION-GROUNDED.md.
const STATES = [
  {
    badge: "✓ mechanism-only",
    cls: "bg-teal-950 text-teal-300 border-teal-800",
    short: "Reasons from the mechanism you give it — safest for strategy selection.",
    long: "Validated in our research (DeepSeek Reasoner, BytePlus Seed 2.0 Pro): it does not rely on memorised " +
      "market history, so it cannot inflate a backtest by ‘recalling’ which strategies happened to work in the " +
      "tested period. Recommended for selection.",
  },
  {
    badge: "⚠ leakage risk",
    cls: "bg-amber-950 text-amber-300 border-amber-800",
    short: "May recall memorised outcomes → an over-optimistic, contaminated backtest.",
    long: "Gemini showed this in our research (calibrated recall). GPT and Claude are flagged by analogy — " +
      "not tested by us. Useful as a research oracle, but not for honest strategy selection.",
  },
  {
    badge: "· not tested",
    cls: "bg-gray-800 text-gray-400 border-gray-700",
    short: "Not evaluated for leakage — no safety claim either way.",
    long: "e.g. MiniMax, Qwen, Moonshot, Zhipu, DeepSeek Chat. We never measured these for leakage, so we make " +
      "no claim in either direction — treat with caution and prefer a validated mechanism-only model.",
  },
];

const CHIP = "inline-block text-[10px] uppercase px-1.5 py-0.5 rounded border font-semibold";

export function LeakageLegend() {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded border border-gray-800 bg-gray-950 p-3 space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {STATES.map((s) => (
          <div key={s.badge}>
            <span className={`${CHIP} ${s.cls}`}>{s.badge}</span>
            <p className="text-[11px] text-gray-500 mt-1">{s.short}</p>
          </div>
        ))}
      </div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-[11px] text-blue-400 hover:underline"
      >
        {open ? "▲ Weniger anzeigen" : "ⓘ Was bedeuten diese?"}
      </button>
      {open && (
        <div className="space-y-2 pt-2 border-t border-gray-800">
          {STATES.map((s) => (
            <div key={s.badge} className="text-[11px] text-gray-400 leading-relaxed">
              <span className={`${CHIP} ${s.cls} mr-2`}>{s.badge}</span>
              {s.long}
            </div>
          ))}
          <p className="text-[10px] text-gray-600 pt-1">
            „Leakage" = das Modell hat Marktausgänge im Training gesehen und kann so einen Backtest schönen.
            Mechanism-only-Modelle argumentieren nur aus dem gegebenen Mechanismus.
          </p>
        </div>
      )}
    </div>
  );
}
