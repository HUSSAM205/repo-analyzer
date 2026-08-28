import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { GoogleAnalytics } from "@next/third-parties/google";
import { Analytics } from "@vercel/analytics/react";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const fontSans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const fontMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

const SITE_URL = "https://repolens-ai-app.vercel.app";
const SITE_DESCRIPTION =
  "Instant AST-powered codebase mapping, architecture visualization, and token-efficient AI " +
  "chat for GitHub repositories.";

// opengraph-image.tsx / twitter-image.tsx (next/og, generated at build time)
// are picked up automatically by Next.js for the openGraph.images /
// twitter.images entries -- no manual image URL needed here.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "RepoLens AI | Next-Gen AI Codebase & Repository Intelligence",
    template: "%s | RepoLens AI",
  },
  description: SITE_DESCRIPTION,
  openGraph: {
    title: "RepoLens AI | Next-Gen AI Codebase & Repository Intelligence",
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    siteName: "RepoLens AI",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "RepoLens AI | Next-Gen AI Codebase & Repository Intelligence",
    description: SITE_DESCRIPTION,
  },
};

// Unset in most environments -- GoogleAnalytics only renders when a real
// measurement ID is configured, so local/preview builds never fire GA
// events at a production property. Set NEXT_PUBLIC_GA_ID in Vercel's env
// vars to activate it (same "safe until manually configured" pattern as
// RESEND_API_KEY in render.yaml).
const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_ID;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning is the documented next-themes pattern: the
    // "dark"/"light" class next-themes applies to <html> is set from
    // localStorage before React hydrates, which legitimately differs from
    // the server-rendered markup (which knows neither).
    <html lang="en" suppressHydrationWarning>
      <body className={`${fontSans.variable} ${fontMono.variable} font-sans antialiased`}>
        {/* defaultTheme="dark" keeps the app's existing look for anyone who
            hasn't chosen a theme yet -- enableSystem is off so a visitor's
            OS light-mode setting doesn't silently flip it. */}
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          {children}
        </ThemeProvider>
        <Analytics />
        {GA_MEASUREMENT_ID && <GoogleAnalytics gaId={GA_MEASUREMENT_ID} />}
      </body>
    </html>
  );
}
