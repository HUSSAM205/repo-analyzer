import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";

// Deliberately unauthenticated (see middleware.ts's matcher, which
// excludes this path so a stateless pinger hitting it never triggers the
// guest-session bootstrap flow) and lightweight -- meant to be hit
// repeatedly to keep both the Render backend and the Neon Postgres it
// talks to warm, since both independently spin down on their own idle
// timers on their free tiers. Proxies straight through to the backend's
// own /api/v1/keepalive, which does a trivial `SELECT 1` to keep the
// pooled DB connection warm too.
//
// vercel.json's cron only hits this once/day -- confirmed live that
// Vercel's Hobby plan hard-rejects any cron schedule that would run more
// than once per day (the deploy itself fails outright, not just a
// downgrade), so a real 5-10 minute cadence isn't achievable via Vercel
// Cron on this plan. For actual free-tier-cold-start prevention, point an
// external always-free uptime pinger (e.g. cron-job.org, UptimeRobot) at
// this URL every 5-10 minutes -- same pattern already used for the
// backend's own /api/v1/keepalive endpoint directly. This route/cron
// combo still helps once/day and costs nothing extra to keep.
export async function GET() {
  try {
    const res = await fetch(backendUrl("/api/v1/keepalive"), { cache: "no-store" });
    return NextResponse.json({ ok: res.ok }, { status: res.ok ? 200 : 502 });
  } catch {
    return NextResponse.json({ ok: false }, { status: 502 });
  }
}
