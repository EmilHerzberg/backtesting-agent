"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

// Research-only deployment: the landing is the login; authenticated users are
// sent straight to the autonomous research console (/dashboard/research).
export default function Home() {
  const { isLoggedIn, isInitialized, login, register } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [verifyUrl, setVerifyUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  // Optional AI key at registration (Q3). Pre-auth, so the provider list is the known set.
  const [providerType, setProviderType] = useState("deepseek");
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    if (isInitialized && isLoggedIn) router.replace("/dashboard/research");
  }, [isInitialized, isLoggedIn, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    try {
      if (mode === "register") {
        const result = await register(
          email,
          password,
          apiKey ? providerType : undefined,
          apiKey || undefined,
        );
        setMessage(result.message);
        setVerifyUrl(result.verify_url);
        setMode("login");
      } else {
        await login(email, password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler");
    }
  };

  if (!isInitialized) return <div className="text-center py-16 text-gray-500">Laden...</div>;
  if (isLoggedIn)
    return <div className="text-center py-16 text-gray-500">Weiterleitung zur Research-Konsole…</div>;

  return (
    <div className="max-w-md mx-auto mt-16">
      <h1 className="text-2xl font-bold mb-1 text-center">Backtesting-Agent</h1>
      <p className="text-center text-sm text-gray-500 mb-6">
        Autonome Research-Engine — {mode === "login" ? "Login" : "Registrierung"}
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <input
          type="email"
          placeholder="E-Mail"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded focus:border-blue-500 outline-none"
          required
        />
        <input
          type="password"
          placeholder="Passwort (min. 8 Zeichen)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-4 py-2 bg-gray-900 border border-gray-700 rounded focus:border-blue-500 outline-none"
          required
          minLength={8}
        />
        {mode === "register" && (
          <details className="text-sm text-gray-400 border border-gray-800 rounded px-3 py-2">
            <summary className="cursor-pointer select-none">
              AI-API-Key hinzufügen (optional) — für KI-Modus
            </summary>
            <div className="mt-3 space-y-2">
              <select
                value={providerType}
                onChange={(e) => setProviderType(e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded outline-none"
              >
                {["deepseek", "minimax", "qwen", "zhipu", "moonshot"].map((p) => (
                  <option key={p} value={p}>
                    {p}
                    {p === "deepseek" ? " (mechanism-only, empfohlen)" : ""}
                  </option>
                ))}
              </select>
              <input
                type="password"
                placeholder="API-Key (optional)"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded outline-none"
              />
              <p className="text-[11px] text-gray-600">
                Kann auch später unter Einstellungen verwaltet werden.
              </p>
            </div>
          </details>
        )}
        <button
          type="submit"
          className="w-full py-2 bg-blue-600 hover:bg-blue-700 rounded font-semibold transition"
        >
          {mode === "login" ? "Login" : "Registrieren"}
        </button>
      </form>
      {message && (
        <div className="mt-4 text-green-400 text-sm text-center">
          <p>{message}</p>
          {verifyUrl && (
            <a
              href={verifyUrl}
              className="mt-2 inline-block px-4 py-1 bg-green-600 hover:bg-green-700 text-white rounded transition"
            >
              E-Mail jetzt verifizieren
            </a>
          )}
        </div>
      )}
      {error && <p className="mt-4 text-red-400 text-sm text-center">{error}</p>}
      <p className="mt-4 text-center text-sm text-gray-500">
        {mode === "login" ? (
          <>
            Noch kein Konto?{" "}
            <button onClick={() => setMode("register")} className="text-blue-400 hover:underline">
              Registrieren
            </button>
          </>
        ) : (
          <>
            Bereits registriert?{" "}
            <button onClick={() => setMode("login")} className="text-blue-400 hover:underline">
              Login
            </button>
          </>
        )}
      </p>
    </div>
  );
}
