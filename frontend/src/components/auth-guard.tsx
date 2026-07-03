"use client";

import { useEffect } from "react";
import { useAuth } from "@/lib/auth-context";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isLoggedIn, isInitialized } = useAuth();

  useEffect(() => {
    if (isInitialized && !isLoggedIn) {
      window.location.href = "/";
    }
  }, [isLoggedIn, isInitialized]);

  if (!isInitialized) {
    return <div className="text-center py-16 text-gray-500">Laden...</div>;
  }

  if (!isLoggedIn) {
    return (
      <div className="text-center py-16 text-gray-500">
        Weiterleitung zum Login...
      </div>
    );
  }

  return <>{children}</>;
}
