import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

export const maxDuration = 60;

export async function GET(_request: NextRequest, { params }: { params: { repoId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const backendResponse = await fetch(
    backendUrl(`/api/v1/repos/${encodeURIComponent(params.repoId)}/complexity`),
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );
  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
