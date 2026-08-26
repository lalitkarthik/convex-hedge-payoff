import type { NextConfig } from "next";

/**
 * The skeleton has no backend, so there is nothing to proxy to yet.
 *
 * When one exists it is reached through a **rewrite, not CORS** (#17): the browser only
 * ever talks to its own origin, and `BACKEND_ORIGIN` is an environment variable so a
 * preview deployment can point at a staging backend. Kept here, commented, because the
 * decision is made and the shape of it is worth not rediscovering.
 *
 *   async rewrites() {
 *     return [{ source: "/api/:path*", destination: `${process.env.BACKEND_ORIGIN}/:path*` }];
 *   }
 */
const nextConfig: NextConfig = {};

export default nextConfig;
