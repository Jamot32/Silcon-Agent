import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Proxied SSE must flush each event instead of waiting in a gzip buffer.
  compress: false,
  devIndicators: false,
  async rewrites() {
    return [{
      source: "/api/:path*",
      destination: `${process.env.API_INTERNAL_URL ?? "http://api:8000"}/api/:path*`,
    }];
  },
};

export default nextConfig;
