import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  // REST API removes the stage from the path forwarded to Lambda.
  // Keep Next routes at / and prefix browser-facing asset/API URLs explicitly.
  assetPrefix: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  compress: false,
  poweredByHeader: false,
  devIndicators: false,
};

export default config;
