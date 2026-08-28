// Shared visual for opengraph-image.tsx and twitter-image.tsx. Next.js
// requires each of those files to declare its own literal `runtime`/`size`
// exports (a re-export like `export { runtime } from "./opengraph-image"`
// fails prerendering -- "Invalid URL" from @vercel/og's static analysis,
// confirmed via a real build), so only the JSX itself is shared here.
export function SocialCardVisual() {
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#09090b",
        backgroundImage:
          "radial-gradient(circle at 25% 20%, rgba(99,102,241,0.35), transparent 55%), radial-gradient(circle at 80% 80%, rgba(59,130,246,0.25), transparent 55%)",
        fontFamily: "sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 28,
        }}
      >
        <svg width="56" height="56" viewBox="0 0 32 32" fill="none">
          <path d="M16 2 L29 9 V23 L16 30 L3 23 V9 Z" stroke="#818cf8" strokeWidth={2} strokeLinejoin="round" />
          <path
            d="M16 2 V16 M16 16 L29 9 M16 16 L3 9 M16 16 V30"
            stroke="#818cf8"
            strokeWidth={1.5}
            strokeOpacity={0.5}
          />
          <circle cx="16" cy="16" r="3" fill="#818cf8" />
        </svg>
        <span style={{ fontSize: 40, fontWeight: 700, color: "#fafafa", letterSpacing: -1 }}>RepoLens AI</span>
      </div>
      <div
        style={{
          fontSize: 30,
          fontWeight: 600,
          color: "#fafafa",
          textAlign: "center",
          maxWidth: 900,
          lineHeight: 1.3,
        }}
      >
        Next-Gen AI Codebase &amp; Repository Intelligence
      </div>
      <div
        style={{
          marginTop: 20,
          fontSize: 22,
          color: "#a1a1aa",
          textAlign: "center",
          maxWidth: 820,
        }}
      >
        Instant AST-powered mapping, architecture visualization &amp; token-efficient AI chat
      </div>
      <div
        style={{
          display: "flex",
          gap: 12,
          marginTop: 40,
        }}
      >
        {["Zero-Token Analysis", "Security Radar", "AI Chat"].map((label) => (
          <div
            key={label}
            style={{
              display: "flex",
              padding: "8px 18px",
              borderRadius: 999,
              border: "1px solid rgba(129,140,248,0.4)",
              color: "#c7d2fe",
              fontSize: 18,
            }}
          >
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
