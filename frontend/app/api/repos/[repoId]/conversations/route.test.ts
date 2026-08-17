/**
 * @jest-environment node
 *
 * See app/api/repos/[repoId]/files/route.test.ts for why this needs the
 * "node" test environment instead of the project default (jsdom).
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

import { NextRequest } from "next/server";
import { GET, POST } from "./route";

describe("/api/repos/[repoId]/conversations", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("GET encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "[]" } as Response);
    }) as unknown as typeof fetch;

    await GET(new NextRequest("http://localhost/api/repos/x/conversations"), {
      params: { repoId: "../../etc/passwd" },
    });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd/conversations");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("POST encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "{}" } as Response);
    }) as unknown as typeof fetch;

    await POST(
      new NextRequest("http://localhost/api/repos/x/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New conversation" }),
      }),
      { params: { repoId: "../../etc/passwd" } }
    );

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd/conversations");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });
});
