import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

// Same reasoning as the annotations route: a cache-miss here waits on a
// full Groq round trip (including its own retry/backoff), which can run
// past Vercel's default serverless function timeout.
export const maxDuration = 60;

export async function GET(_request: NextRequest, { params }: { params: { repoId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const backendResponse = await fetch(
    backendUrl(`/api/v1/repos/${encodeURIComponent(params.repoId)}/readme`),
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
