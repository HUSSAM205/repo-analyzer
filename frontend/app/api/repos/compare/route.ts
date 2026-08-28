import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

export async function GET(request: NextRequest) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const repoA = request.nextUrl.searchParams.get("repo_a");
  const repoB = request.nextUrl.searchParams.get("repo_b");
  if (!repoA || !repoB) {
    return NextResponse.json({ detail: "repo_a and repo_b are required" }, { status: 400 });
  }

  const backendResponse = await fetch(
    backendUrl(`/api/v1/repos/compare?repo_a=${encodeURIComponent(repoA)}&repo_b=${encodeURIComponent(repoB)}`),
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
