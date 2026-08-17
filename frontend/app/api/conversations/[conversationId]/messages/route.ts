import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: { conversationId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const backendResponse = await fetch(backendUrl(`/api/v1/conversations/${params.conversationId}/messages`), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function POST(request: Request, { params }: { params: { conversationId: string } }) {
  const token = getSessionToken();
  if (!token) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const body = await request.text();

  const backendResponse = await fetch(backendUrl(`/api/v1/conversations/${params.conversationId}/messages`), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body,
  });

  if (!backendResponse.ok || !backendResponse.body) {
    const errorBody = await backendResponse.text();
    return new NextResponse(errorBody, { status: backendResponse.status });
  }

  return new Response(backendResponse.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
