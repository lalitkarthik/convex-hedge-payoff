import type { NextConfig } from "next";

/**
 * **Same-origin, always.** The browser talks only to its own origin; `/api/*` is
 * rewritten to the backend by the server, so no cross-origin policy exists — and a
 * policy that does not exist cannot be misconfigured, which is #25's rule.
 *
 * `BACKEND_ORIGIN` is an environment variable rather than a constant so a preview
 * deployment can point at a staging backend without a rebuild of the client. It is read
 * on the server only: it is never inlined into browser code and is not prefixed
 * `NEXT_PUBLIC_`, so pointing it at an internal host is safe.
 */
const BACKEND = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The dev overlay badge sits on top of the chain's bottom-left corner, which is where
  // the deepest in-the-money calls are. Off, so the table is judged without it.
  devIndicators: false,

  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/:path*` }];
  },
};

export default nextConfig;
