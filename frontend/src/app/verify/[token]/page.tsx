"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { authApi } from "@/lib/api";

export default function VerifyPage() {
  const params = useParams();
  const token = params.token as string;
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading"
  );
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) return;
    authApi
      .verify(token)
      .then((res) => {
        setStatus("success");
        setMessage(res.message);
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err.message);
      });
  }, [token]);

  return (
    <div className="max-w-md mx-auto mt-16 text-center">
      {status === "loading" && (
        <p className="text-gray-400">Verifizierung wird durchgefuehrt...</p>
      )}
      {status === "success" && (
        <div className="space-y-4">
          <p className="text-green-400 text-lg font-semibold">{message}</p>
          <a
            href="/"
            className="inline-block px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded font-semibold transition"
          >
            Zum Login
          </a>
        </div>
      )}
      {status === "error" && (
        <div className="space-y-4">
          <p className="text-red-400 text-lg">{message}</p>
          <a href="/" className="text-blue-400 hover:underline">
            Zurueck
          </a>
        </div>
      )}
    </div>
  );
}
