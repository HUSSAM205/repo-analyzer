import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

export async function GET(request: Request, { params }: { params: { repoId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const backendResponse = await fetch(backendUrl(`/api/v1/repos/${params.repoId}/files`), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
