/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

describe("middleware guest-session bootstrap", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("mints a guest token and sets the session cookie when none exists", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "guest-token-123", token_type: "bearer" }),
    }) as unknown as typeof fetch;

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/auth/guest"), { method: "POST" });
    expect(response.cookies.get("session_token")?.value).toBe("guest-token-123");
  });

  it("does not mint a new guest when a session cookie already exists", async () => {
    global.fetch = jest.fn();

    const request = new NextRequest("http://localhost:3000/repos", {
      headers: new Headers({ cookie: "session_token=existing-token" }),
    });
    const response = await middleware(request);

    expect(fetch).not.toHaveBeenCalled();
    expect(response.cookies.get("session_token")).toBeUndefined();
  });

  it("lets the request through without a cookie when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network error"));

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(response.cookies.get("session_token")).toBeUndefined();
    expect(response.status).toBeLessThan(500);
  });

  it("does not mint a guest for a failed backend response", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch;

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(response.cookies.get("session_token")).toBeUndefined();
  });
});
