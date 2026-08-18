/**
 * @jest-environment node
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
    delete: (name: string) => store.delete(name),
  }),
}));

import { GET } from "./route";

describe("GET /api/auth/reset", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("clears the session cookie and redirects to '/'", async () => {
    store.set("session_token", "stale-token");

    const res = await GET(new Request("http://localhost/api/auth/reset"));

    expect(store.has("session_token")).toBe(false);
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost/");
  });

  it("still redirects to '/' even when there was no cookie to begin with", async () => {
    const res = await GET(new Request("http://localhost/api/auth/reset"));

    expect(store.has("session_token")).toBe(false);
    expect(res.headers.get("location")).toBe("http://localhost/");
  });
});
