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

import { GET } from "./route";

describe("GET /api/jobs/[jobId]", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("encodes a '..'-containing jobId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, text: async () => "{}" } as Response);
    }) as unknown as typeof fetch;

    await GET(new Request("http://localhost/api/jobs/x"), { params: { jobId: "../../etc/passwd" } });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/jobs/..%2F..%2Fetc%2Fpasswd");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });
});
