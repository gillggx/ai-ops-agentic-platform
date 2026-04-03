import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  basePath: "/simulator",
  trailingSlash: true,
  images: { unoptimized: true },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
