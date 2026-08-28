import { cookies } from "next/headers";

const SESSION_COOKIE = "session_token";

export function getSessionToken(): string | undefined {
  return cookies().get(SESSION_COOKIE)?.value;
}

export function setSessionToken(token: string): void {
  cookies().set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60,
  });
}

export function clearSessionToken(): void {
  cookies().delete(SESSION_COOKIE);
}
