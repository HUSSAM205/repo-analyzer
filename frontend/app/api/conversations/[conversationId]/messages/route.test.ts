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

import { GET, POST } from "./route";

describe("/api/conversations/[conversationId]/messages", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("GET encodes a '..'-containing conversationId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "[]" } as Response);
    }) as unknown as typeof fetch;

    await GET(new Request("http://localhost/api/conversations/x/messages"), {
      params: { conversationId: "../../etc/passwd" },
    });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/conversations/..%2F..%2Fetc%2Fpasswd/messages");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("POST encodes a '..'-containing conversationId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      // ok: false short-circuits before the route tries to read a real SSE
      // body -- only the outgoing request URL matters for this test.
      return Promise.resolve({ ok: false, status: 400, text: async () => "{}" } as Response);
    }) as unknown as typeof fetch;

    await POST(
      new Request("http://localhost/api/conversations/x/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "hi" }),
      }),
      { params: { conversationId: "../../etc/passwd" } }
    );

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/conversations/..%2F..%2Fetc%2Fpasswd/messages");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });
});
