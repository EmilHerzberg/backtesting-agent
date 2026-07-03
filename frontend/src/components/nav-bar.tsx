"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

// Research-only deployment (backtesting-agent): the nav surfaces just the
// autonomous research system. Other app sections still exist by direct URL.
export default function NavBar() {
  const { isLoggedIn, isInitialized, logout } = useAuth();

  return (
    <nav className="border-b border-gray-800 px-6 py-3 flex items-center justify-between">
      <Link href="/dashboard/research" className="text-xl font-bold text-white">
        Backtesting-Agent
      </Link>
      {isInitialized && isLoggedIn && (
        <div className="flex gap-6 text-sm font-medium items-center">
          <Link href="/dashboard/research" className="hover:text-blue-400 transition">
            Research
          </Link>
          <Link href="/settings" className="hover:text-blue-400 transition">
            Settings
          </Link>
          <button onClick={logout} className="text-gray-500 hover:text-gray-300 transition">
            Logout
          </button>
        </div>
      )}
    </nav>
  );
}
