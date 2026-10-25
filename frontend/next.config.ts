import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Hide the "N" development indicator (bottom-left in `next dev` only; never in
  // production builds). Compile and runtime errors are still shown.
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
