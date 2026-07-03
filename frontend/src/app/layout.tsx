import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import NavBar from "@/components/nav-bar";

export const metadata: Metadata = {
  title: "Backtesting Agent",
  description: "Autonomous strategy research",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen">
        <AuthProvider>
          <NavBar />
          <main className="overflow-y-auto px-6 py-8">
            <div className="max-w-6xl mx-auto">{children}</div>
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
