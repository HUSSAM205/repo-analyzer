import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

const fontSans = Inter({ subsets: ["latin"], variable: "--font-sans" });
const fontMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Repo Analyzer",
  description: "AI-powered GitHub repository analysis and chat",
};

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
      </body>
    </html>
  );
}
