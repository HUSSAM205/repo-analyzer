import { ImageResponse } from "next/og";
import { SocialCardVisual } from "@/lib/social-card";

// Next.js App Router convention: a file named opengraph-image.tsx anywhere
// under app/ is automatically picked up as that route segment's og:image
// -- no manual <meta> tag needed, and no static PNG asset to keep in sync
// with the app's actual branding. Rendered once at build time (this route
// has no dynamic params), so it costs nothing per request.
export const runtime = "edge";
export const alt = "RepoLens AI -- Next-Gen AI Codebase & Repository Intelligence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(<SocialCardVisual />, { ...size });
}
