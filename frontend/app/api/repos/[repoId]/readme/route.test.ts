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
import { GET } from "./route";

describe("GET /api/repos/[repoId]/readme", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/x/readme"), { params: { repoId: "x" } });
    expect(response.status).toBe(401);
  });

  it("encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "{}" } as Response);
    }) as unknown as typeof fetch;

    await GET(new NextRequest("http://localhost/api/repos/x/readme"), { params: { repoId: "../../etc/passwd" } });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd/readme");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 200,
      text: async () => JSON.stringify({ content: "# Hello" }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/readme"), { params: { repoId: "x" } });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ content: "# Hello" });
  });

  it("passes through a 503 unchanged (AI temporarily unavailable)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 503,
      text: async () => JSON.stringify({ detail: "The AI provider is temporarily unavailable. Please try again." }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/readme"), { params: { repoId: "x" } });
    expect(response.status).toBe(503);
  });
});
