import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { setSessionToken } from "@/lib/session";
import type { TokenResponse } from "@/lib/types";

export async function POST(request: NextRequest) {
  const body = await request.json();

  const backendResponse = await fetch(backendUrl("/api/v1/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!backendResponse.ok) {
    const errorBody = await backendResponse.text();
    return new NextResponse(errorBody, {
      status: backendResponse.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const data = (await backendResponse.json()) as TokenResponse;
  setSessionToken(data.access_token);
  return NextResponse.json({ ok: true });
}
