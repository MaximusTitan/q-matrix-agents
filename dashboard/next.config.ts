import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/run", destination: `${API_URL}/run` },
      { source: "/reject", destination: `${API_URL}/reject` },
      { source: "/re-extract", destination: `${API_URL}/re-extract` },
      { source: "/runs", destination: `${API_URL}/runs` },
      { source: "/runs/:path*", destination: `${API_URL}/runs/:path*` },
      { source: "/stream/:runId", destination: `${API_URL}/stream/:runId` },
    ];
  },
};

export default nextConfig;
