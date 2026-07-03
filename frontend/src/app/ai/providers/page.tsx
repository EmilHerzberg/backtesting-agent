"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/auth-guard";

const API = "/api/ai";

interface Provider {
  id: number;
  name: string;
  provider_type: string;
  base_url: string;
  is_active: boolean;
  api_key_masked: string;
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Error ${res.status}`);
  return res.json();
}

export default function ProvidersPage() {
  return (
    <AuthGuard>
      <ProvidersInner />
    </AuthGuard>
  );
}

function ProvidersInner() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [providerType, setProviderType] = useState("minimax");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = async () => {
    try {
      const [p, t] = await Promise.all([
        req<Provider[]>("/providers"),
        req<{ types: string[] }>("/provider-types"),
      ]);
      setProviders(p);
      setTypes(t.types);
    } catch {}
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    try {
      await req<Provider>("/providers", {
        method: "POST",
        body: JSON.stringify({
          name, provider_type: providerType, api_key: apiKey,
          base_url: baseUrl || undefined,
        }),
      });
      setSuccess(`Provider "${name}" angelegt!`);
      setShowForm(false);
      setName(""); setApiKey(""); setBaseUrl("");
      await load();
    } catch (err: any) { setError(err.message); }
  };

  const handleToggle = async (id: number, active: boolean) => {
    await req(`/providers/${id}/toggle?active=${active}`, { method: "POST" });
    await load();
  };

  const handleDelete = async (id: number) => {
    await req(`/providers/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">AI Provider</h1>
        <button onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-semibold">
          {showForm ? "Abbrechen" : "Provider hinzufuegen"}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {success && <p className="text-green-400 text-sm">{success}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="bg-gray-900 border border-gray-800 rounded-lg p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Name</label>
              <input value={name} onChange={e => setName(e.target.value)} required
                placeholder="z.B. MiniMax Production"
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Typ</label>
              <select value={providerType} onChange={e => setProviderType(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded outline-none focus:border-blue-500">
                {types.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">API Key</label>
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} required
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Base URL (optional)</label>
              <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
                placeholder="Standard wird automatisch gesetzt"
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded outline-none focus:border-blue-500" />
            </div>
          </div>
          <button type="submit" className="w-full py-2 bg-green-600 hover:bg-green-700 rounded font-semibold">
            Speichern
          </button>
        </form>
      )}

      {providers.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-800">
              <th className="py-2">Name</th><th>Typ</th><th>Base URL</th><th>API Key</th><th>Status</th><th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {providers.map(p => (
              <tr key={p.id} className="border-b border-gray-800/50 hover:bg-gray-900">
                <td className="py-3 font-semibold">{p.name}</td>
                <td className="text-gray-400">{p.provider_type}</td>
                <td className="text-gray-400 text-xs font-mono">{p.base_url}</td>
                <td className="font-mono text-xs text-gray-500">{p.api_key_masked}</td>
                <td>
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                    p.is_active ? "bg-green-900 text-green-300" : "bg-gray-700 text-gray-400"
                  }`}>{p.is_active ? "Aktiv" : "Inaktiv"}</span>
                </td>
                <td className="space-x-2">
                  <button onClick={() => handleToggle(p.id, !p.is_active)}
                    className={`text-xs hover:underline ${p.is_active ? "text-yellow-400" : "text-green-400"}`}>
                    {p.is_active ? "Deaktivieren" : "Aktivieren"}
                  </button>
                  <button onClick={() => handleDelete(p.id)}
                    className="text-xs text-red-400 hover:underline">Loeschen</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !showForm && <p className="text-gray-500 text-sm">Noch keine Provider konfiguriert.</p>}
    </div>
  );
}
