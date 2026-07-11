"use client";

// Research-flow error boundary: a render/data crash anywhere under /dashboard/research shows a recoverable
// panel (retry + back to runs) instead of a blank white screen — important for an unattended live demo.
import Link from "next/link";
import { useEffect } from "react";

export default function ResearchError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface it in the console for debugging; users get the friendly panel below.
    console.error("research route error:", error);
  }, [error]);

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-4 p-6 text-center">
      <div className="text-lg font-semibold text-gray-100">Something went wrong loading this view.</div>
      <div className="max-w-md text-sm text-gray-400">
        {error?.message || "An unexpected error occurred."}
        {error?.digest ? <span className="block mt-1 text-[11px] text-gray-600">ref: {error.digest}</span> : null}
      </div>
      <div className="flex gap-2">
        <button
          onClick={reset}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
        >
          Retry
        </button>
        <Link
          href="/dashboard/research"
          className="rounded bg-gray-800 px-4 py-2 text-sm text-gray-200 hover:bg-gray-700"
        >
          Back to runs
        </Link>
      </div>
    </div>
  );
}
