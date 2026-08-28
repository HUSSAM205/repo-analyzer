import { NextResponse } from "next/server";
import { clearSessionToken } from "@/lib/session";

export async function POST() {
  clearSessionToken();
  return NextResponse.json({ ok: true });
}
