// The security-headers middleware on the FastAPI backend (see
// backend/app/main.py) never reaches an actual browser in this deployment
// -- the frontend proxies every backend call server-side (see
// lib/backend.ts), so the browser only ever talks to THIS Next.js app.
// These headers are the ones that matter for the real client-facing
// surface. next/font/google (see app/layout.tsx) self-hosts font files at
// build time -- no runtime request to fonts.googleapis.com/gstatic.com, so
// the CSP doesn't need to allow either.
const SECURITY_HEADERS = [
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next.js's App Router hydration bootstrap is an inline <script> --
      // 'unsafe-inline' is required for that specific (low-risk, framework-
      // controlled, not user-content-derived) script to run at all.
      // 'wasm-unsafe-eval' is required for Shiki (lib/highlight.ts): its
      // Oniguruma regex engine is a WebAssembly module, and
      // WebAssembly.instantiate() is blocked by CSP without this directive
      // -- without it, EVERY syntax-highlighted code render (Raw Code,
      // Annotated View, and chat code blocks) throws, which is what was
      // producing "Could not load this file's content" for every file.
      "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'",
      // Required for React inline `style={{...}}` props (used throughout
      // the workspace's resizable panes) and Tailwind's own injected
      // stylesheet -- neither is user-content-derived either.
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self' data:",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "geolocation=(), camera=(), microphone=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
