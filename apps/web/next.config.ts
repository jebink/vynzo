import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide the floating "N" dev-tools badge; build and runtime errors still show as an overlay.
  devIndicators: false,
  cacheComponents: true,
  // The app opens on the dashboard. Temporary (307) so "/" can become a landing page later
  // without browsers having cached a permanent redirect.
  redirects: () =>
    Promise.resolve([
      { source: "/", destination: "/dashboard", permanent: false },
      // Old name of the Market section ("Markets & Signals"); keeps bookmarks working.
      { source: "/markets", destination: "/market", permanent: true },
    ]),
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
