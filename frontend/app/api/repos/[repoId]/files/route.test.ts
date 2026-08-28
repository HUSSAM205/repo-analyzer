/**
 * @jest-environment node
 *
 * Route Handlers import `next/server`, whose `NextRequest` extends the
 * global WHATWG `Request` class at module-load time. jsdom (this project's
 * default jest testEnvironment) doesn't define `Request`/`Response`/`fetch`
 * as globals, so importing the route under test would throw before any
 * assertion runs. Node's environment provides real fetch primitives
 * natively (Node 18+), so this file overrides to it instead of polyfilling.
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

import { GET } from "./route";

describe("GET /api/repos/[repoId]/files", () => {
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

    await GET(new Request("http://localhost/api/repos/x/files"), { params: { repoId: "../../etc/passwd" } });

    // encodeURIComponent turns "/" into "%2F", so the traversal segments can
    // never reach the backend as literal path separators for Node's URL
    // constructor (or the backend router) to normalize away.
    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd/files");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });
});
