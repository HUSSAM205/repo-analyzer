"use client";

// Next.js requires this exact separate file (not just app/error.tsx) to
// catch an error thrown by the root layout itself (app/layout.tsx) -- since
// the root layout normally renders the <html>/<body> that every other
// error.tsx relies on, this one has to render its own when it takes over.
// Deliberately minimal/inline-styled: it can't assume globals.css, fonts,
// or ThemeProvider successfully loaded, since one of those failing is
// exactly the case this exists to catch.
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          textAlign: "center",
          fontFamily: "system-ui, sans-serif",
          background: "#09090b",
          color: "#fafafa",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600, margin: 0 }}>Something went wrong</h1>
        <p style={{ maxWidth: "24rem", fontSize: "0.875rem", color: "#a1a1aa", margin: 0 }}>
          An unexpected error occurred while loading the app. Try again below.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            marginTop: "0.5rem",
            borderRadius: "0.375rem",
            border: "none",
            background: "#6366f1",
            color: "#fff",
            padding: "0.5rem 1rem",
            fontSize: "0.875rem",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
