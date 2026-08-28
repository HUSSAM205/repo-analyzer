import { ImageResponse } from "next/og";

// App Router convention: apple-icon.tsx is auto-served as the
// apple-touch-icon (with the correct <link rel="apple-touch-icon"> tag
// added for us) -- generated at build time via the same next/og renderer
// as opengraph-image.tsx, so the two share one visual source of truth
// instead of a hand-exported PNG that could drift from the real branding.
export const runtime = "edge";
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#09090b",
        }}
      >
        <svg width="120" height="120" viewBox="0 0 32 32" fill="none">
          <path d="M16 4 L27 10.5 V21.5 L16 28 L5 21.5 V10.5 Z" stroke="#818cf8" strokeWidth={1.8} strokeLinejoin="round" />
          <path
            d="M16 4 V16 M16 16 L27 10.5 M16 16 L5 10.5 M16 16 V28"
            stroke="#818cf8"
            strokeWidth={1.2}
            strokeOpacity={0.5}
          />
          <circle cx="16" cy="16" r="2.6" fill="#818cf8" />
        </svg>
      </div>
    ),
    { ...size }
  );
}
