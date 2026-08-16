import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";

export async function POST(request: NextRequest) {
  const body = await request.json();

  const backendResponse = await fetch(backendUrl("/api/v1/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const responseBody = await backendResponse.text();
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    headers: { "Content-Type": "application/json" },
  });
}
