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

describe("GET /api/repos/[repoId]/files/annotations", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "{}" } as Response);
    }) as unknown as typeof fetch;

    await GET(new NextRequest("http://localhost/api/repos/x/files/annotations?path=main.py"), {
      params: { repoId: "../../etc/passwd" },
    });

    expect(capturedUrl).toBe(
      "http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd/files/annotations?path=main.py"
    );
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/x/files/annotations?path=main.py"), {
      params: { repoId: "x" },
    });
    expect(response.status).toBe(401);
  });

  it("returns 400 when the 'path' query parameter is missing", async () => {
    store.set("session_token", "test-token");
    const response = await GET(new NextRequest("http://localhost/api/repos/x/files/annotations"), {
      params: { repoId: "x" },
    });
    expect(response.status).toBe(400);
  });

  it("passes through the backend's status and body unchanged (e.g. a 413 too-large response)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 413,
      text: async () => JSON.stringify({ detail: "File too large to annotate." }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/files/annotations?path=main.py"), {
      params: { repoId: "x" },
    });

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ detail: "File too large to annotate." });
  });
});
