"use client";

import { useEffect, useState } from "react";
import { Loader2, Settings as SettingsIcon, UserCircle2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { ThemeToggle } from "@/components/theme-toggle";
import type { User } from "@/lib/types";

export default function SettingsPage() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/auth/me", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled) setUser(data);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="mb-6 flex items-center gap-2 text-xl font-semibold text-foreground">
        <SettingsIcon className="h-5 w-5 text-primary" aria-hidden="true" />
        Settings
      </h1>

      <section className="glass mb-4 rounded-lg border border-zinc-800/60 p-4">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-primary/80">Appearance</h2>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">Theme</p>
            <p className="text-xs text-muted-foreground">Switch between light and dark mode.</p>
          </div>
          <ThemeToggle />
        </div>
      </section>

      <section className="glass rounded-lg border border-zinc-800/60 p-4">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-primary/80">Account</h2>
        {user === undefined ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading...
          </div>
        ) : user === null ? (
          <p className="text-sm text-destructive">Could not load your account details.</p>
        ) : (
          <div className="flex items-start gap-3">
            <UserCircle2 className="mt-0.5 h-8 w-8 shrink-0 text-muted-foreground" aria-hidden="true" />
            <dl className="space-y-1 text-sm">
              <div>
                <dt className="inline text-muted-foreground">Account type: </dt>
                <dd className="inline font-medium text-foreground">{user.is_guest ? "Guest" : "Registered"}</dd>
              </div>
              {user.email && (
                <div>
                  <dt className="inline text-muted-foreground">Email: </dt>
                  <dd className="inline font-medium text-foreground">{user.email}</dd>
                </div>
              )}
              <div>
                <dt className="inline text-muted-foreground">Member since: </dt>
                <dd className="inline font-medium text-foreground">
                  {new Date(user.created_at).toLocaleDateString()}
                </dd>
              </div>
            </dl>
          </div>
        )}
      </section>
    </main>
  );
}
