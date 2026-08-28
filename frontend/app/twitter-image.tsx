import { ImageResponse } from "next/og";
import { SocialCardVisual } from "@/lib/social-card";

// See opengraph-image.tsx's comment: these exports must each be their own
// literal here (re-exporting from opengraph-image.tsx breaks prerendering),
// even though the visual and dimensions are identical.
export const runtime = "edge";
export const alt = "RepoLens AI -- Next-Gen AI Codebase & Repository Intelligence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(<SocialCardVisual />, { ...size });
}
