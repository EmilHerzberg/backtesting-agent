import path from "path";
import type { NextConfig } from "next";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Pin the tracing root to this app so a stray lockfile in a parent directory doesn't get inferred as the
  // workspace root (silences the "inferred your workspace root" build warning; keeps standalone output correct).
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
