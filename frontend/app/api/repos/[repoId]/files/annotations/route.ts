import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

// Same reasoning as the chat messages route: a cache-miss here waits on a
// full Groq round trip (including its own retry/backoff), which can run
// past Vercel's default serverless function timeout.
export const maxDuration = 60;

export async function GET(request: NextRequest, { params }: { params: { repoId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const path = request.nextUrl.searchParams.get("path");
  if (!path) {
    return NextResponse.json({ detail: "Missing 'path' query parameter" }, { status: 400 });
  }

  const backendResponse = await fetch(
    backendUrl(
      `/api/v1/repos/${encodeURIComponent(params.repoId)}/files/annotations?path=${encodeURIComponent(path)}`
    ),
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
