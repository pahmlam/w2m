import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: process.env.W2M_DOCKER_BUILD === "1" ? "standalone" : undefined,
};

export default nextConfig;
