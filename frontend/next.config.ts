import type { NextConfig } from "next";

const api = process.env.API_INTERNAL_URL || "http://localhost:8000";
const config: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default config;
