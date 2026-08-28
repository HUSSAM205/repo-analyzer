import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { getSessionToken } from "@/lib/session";

// Only redirects into the workspace once a session cookie actually exists --
// i.e. once the middleware's guest-mint has succeeded at least once. If it
// unconditionally redirected to /repos, and /repos in turn redirects back to
// "/" whenever it finds no token (see app/repos/page.tsx), a persistently
// failing guest-mint (backend down) would bounce the browser between "/" and
// "/repos" forever instead of ever landing on a real page.
export default function HomePage() {
  cookies(); // opts this route into dynamic rendering (reads the session cookie)
  const token = getSessionToken();
  if (token) {
    redirect("/repos");
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-sm text-muted-foreground">
        Having trouble connecting to the server. Please refresh the page.
      </p>
    </main>
  );
}
