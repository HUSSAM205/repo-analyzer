/**
 * @jest-environment node
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
    set: (name: string, value: string) => store.set(name, value),
  }),
}));

import { NextRequest } from "next/server";
import { GET } from "./route";

describe("GET /api/auth/bootstrap", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("mints a guest token, sets the session cookie, and redirects to 'next'", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "guest-token-123", token_type: "bearer" }),
    }) as unknown as typeof fetch;

    const res = await GET(new NextRequest("http://localhost/api/auth/bootstrap?next=%2Frepos%2Fabc"));

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/guest"),
      expect.objectContaining({ method: "POST" })
    );
    expect(store.get("session_token")).toBe("guest-token-123");
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost/repos/abc");
  });

  it("defaults to '/' when no 'next' param is given", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "guest-token-123" }),
    }) as unknown as typeof fetch;

    const res = await GET(new NextRequest("http://localhost/api/auth/bootstrap"));

    expect(res.headers.get("location")).toBe("http://localhost/");
  });

  it("redirects to 'next' without setting a cookie when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network error"));

    const res = await GET(new NextRequest("http://localhost/api/auth/bootstrap?next=%2Frepos"));

    expect(store.has("session_token")).toBe(false);
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost/repos");
  });

  it("redirects to 'next' without setting a cookie for a failed backend response", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch;

    const res = await GET(new NextRequest("http://localhost/api/auth/bootstrap?next=%2Frepos"));

    expect(store.has("session_token")).toBe(false);
    expect(res.headers.get("location")).toBe("http://localhost/repos");
  });

  it("fails open when the guest-mint fetch exceeds its timeout", async () => {
    global.fetch = jest.fn().mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
        })
    ) as unknown as typeof fetch;

    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    const pending = GET(new NextRequest("http://localhost/api/auth/bootstrap?next=%2Frepos"));
    await jest.advanceTimersByTimeAsync(8000);
    const res = await pending;
    jest.useRealTimers();

    expect(store.has("session_token")).toBe(false);
    expect(res.headers.get("location")).toBe("http://localhost/repos");
  });
});
