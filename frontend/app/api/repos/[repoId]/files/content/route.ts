import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

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
    backendUrl(`/api/v1/repos/${params.repoId}/files/content?path=${encodeURIComponent(path)}`),
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
  );

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
