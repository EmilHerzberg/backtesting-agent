"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { authApi } from "./api";

interface RegisterResult {
  message: string;
  verify_url: string | null;
}

interface AuthState {
  token: string | null;
  isLoggedIn: boolean;
  isInitialized: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    providerType?: string,
    apiKey?: string,
  ) => Promise<RegisterResult>;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null,
  isLoggedIn: false,
  isInitialized: false,
  login: async () => {},
  register: async () => ({ message: "", verify_url: null }),
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("token");
    if (stored) setToken(stored);
    setIsInitialized(true);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    localStorage.setItem("token", res.access_token);
    setToken(res.access_token);
  }, []);

  const register = useCallback(
    async (
      email: string,
      password: string,
      providerType?: string,
      apiKey?: string,
    ): Promise<RegisterResult> => {
      const res = await authApi.register(email, password, providerType, apiKey);
      return { message: res.message, verify_url: res.verify_url };
    },
    []
  );

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        isLoggedIn: !!token,
        isInitialized,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
