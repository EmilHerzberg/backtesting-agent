const API_BASE = "/api";

export async function request<T>(
  path: string,
  options: RequestInit = {},
  _retry = true,
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch (err) {
    // Network error — retry once after 1s
    if (_retry) {
      await new Promise((r) => setTimeout(r, 1000));
      return request<T>(path, options, false);
    }
    throw new Error("Netzwerkfehler — bitte Verbindung pruefen");
  }

  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("token");
      // Only redirect if we're NOT already on the login page — prevents
      // infinite reload loop when the polling hook fires on an
      // unauthenticated page.
      if (window.location.pathname !== "/") {
        window.location.href = "/";
      }
      throw new Error("Session abgelaufen");
    }
    // Retry on 5xx server errors
    if (res.status >= 500 && _retry) {
      await new Promise((r) => setTimeout(r, 1000));
      return request<T>(path, options, false);
    }
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// Auth
export const authApi = {
  register: (
    email: string,
    password: string,
    provider_type?: string,
    api_key?: string,
  ) =>
    request<{ message: string; verify_url: string | null }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, provider_type, api_key }),
    }),
  verify: (token: string) =>
    request<{ message: string }>(`/auth/verify/${token}`),
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ message: string }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  deleteAccount: (current_password: string) =>
    request<{ message: string }>("/auth/account", {
      method: "DELETE",
      body: JSON.stringify({ current_password }),
    }),
};

// AI providers (account-settings — API-key management, per-user, key always masked)
export interface AIProvider {
  id: number;
  name: string;
  provider_type: string;
  base_url: string;
  is_active: boolean;
  api_key_masked: string;
  leakage?: string; // mechanism_only | risk | unvalidated
}

export const providerApi = {
  list: () => request<AIProvider[]>("/ai/providers"),
  types: () => request<{ types: string[] }>("/ai/provider-types"),
  create: (name: string, provider_type: string, api_key: string, base_url = "") =>
    request<AIProvider>("/ai/providers", {
      method: "POST",
      body: JSON.stringify({ name, provider_type, api_key, base_url }),
    }),
  remove: (id: number) =>
    request<{ message: string }>(`/ai/providers/${id}`, { method: "DELETE" }),
  toggle: (id: number, active: boolean) =>
    request<AIProvider>(`/ai/providers/${id}/toggle?active=${active}`, { method: "POST" }),
};

// Stocks
export const stockApi = {
  search: (query: string) =>
    request<
      {
        symbol: string;
        name: string;
        isin: string | null;
        exchange: string;
      }[]
    >(`/stocks/search?q=${encodeURIComponent(query)}`),
};

// Agent
export interface AgentConfigPayload {
  symbol: string;
  isin?: string;
  budget: number;
  indicator_name: string;
  indicator_params?: Record<string, number>;
  stop_loss_pct: number;
  interval_seconds: number;
  agent_type?: string;
  ai_provider?: string;
  ai_model?: string;
  system_prompt?: string;
  broker_account_id?: number;
}

export interface AgentStatusResponse {
  id: number;
  symbol: string;
  status: string;
  budget: number;
  indicator: string;
  stop_loss_pct: number;
  interval_seconds: number;
  agent_type: string;
  ai_provider: string | null;
  ai_model: string | null;
  system_prompt: string | null;
  entry_price: number | null;
  position_quantity: number | null;
  broker_account_id: number | null;
  error_count: number;
  last_error: string | null;
}

export const agentApi = {
  create: (config: AgentConfigPayload) =>
    request<AgentStatusResponse>("/agents", {
      method: "POST",
      body: JSON.stringify(config),
    }),
  list: () => request<AgentStatusResponse[]>("/agents"),
  get: (id: number) => request<AgentStatusResponse>(`/agents/${id}`),
  pause: (id: number) =>
    request<AgentStatusResponse>(`/agents/${id}/pause`, { method: "POST" }),
  resume: (id: number) =>
    request<AgentStatusResponse>(`/agents/${id}/resume`, { method: "POST" }),
  stop: (id: number) =>
    request<AgentStatusResponse>(`/agents/${id}/stop`, { method: "POST" }),
};

// Trades
export interface TradeResponse {
  id: number;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  filled_quantity: number;
  avg_fill_price: number | null;
  status: string;
  broker_order_id: string | null;
  submitted_at: string;
  filled_at: string | null;
  agent_config_id: number | null;
}

export interface DecisionLogEntry {
  timestamp: string;
  symbol: string;
  current_price: number;
  indicator_value: number | null;
  signal: string;
  action_taken: string;
  notes: string | null;
}

export const tradeApi = {
  list: (params?: { agent_id?: number; symbol?: string }) => {
    const query = new URLSearchParams();
    if (params?.agent_id) query.set("agent_id", String(params.agent_id));
    if (params?.symbol) query.set("symbol", params.symbol);
    const qs = query.toString();
    return request<TradeResponse[]>(`/trades${qs ? `?${qs}` : ""}`);
  },
  getDecisions: (agentId: number) =>
    request<DecisionLogEntry[]>(`/agents/${agentId}/decisions`),
};

// Broker
export interface BrokerStatus {
  connected: boolean;
  broker_name: string;
  connection_state: string;
}

export interface AccountSummary {
  account_id: string;
  currency: string;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  account_type: string;
}

export interface BrokerPosition {
  symbol: string;
  quantity: number;
  avg_cost: number;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  currency: string;
}

export interface QuoteData {
  symbol: string;
  bid: number;
  ask: number;
  last: number;
  volume: number;
}

export const brokerApi = {
  status: () => request<BrokerStatus>("/broker/status"),
  account: () => request<AccountSummary>("/broker/account"),
  positions: () => request<BrokerPosition[]>("/broker/positions"),
  quote: (symbol: string) => request<QuoteData>(`/broker/quote/${symbol}`),
  placeOrder: (order: {
    symbol: string;
    side: string;
    quantity: number;
    order_type?: string;
    limit_price?: number;
    account_id?: number;
  }) => {
    const qs = order.account_id ? `?account_id=${order.account_id}` : "";
    const { account_id, ...body } = order;
    return request<{ order_id: string; symbol: string; side: string; quantity: number; status: string }>(
      `/broker/order${qs}`,
      { method: "POST", body: JSON.stringify(body) }
    );
  },
};

// Indicators
export interface IndicatorDataPoint {
  index: number;
  price: number;
  indicator_value: number | null;
}

export interface IndicatorCalcResult {
  symbol: string;
  indicator_name: string;
  period: number;
  signal: string;
  current_value: number | null;
  data: IndicatorDataPoint[];
}

export const indicatorApi = {
  list: () => request<{ indicators: string[] }>("/indicators"),
  calculate: (symbol: string, indicator: string, period: number) =>
    request<IndicatorCalcResult>(
      `/indicators/calculate?symbol=${symbol}&indicator_name=${indicator}&period=${period}`,
      { method: "POST" }
    ),
};
