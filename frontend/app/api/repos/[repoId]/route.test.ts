/**
 * @jest-environment node
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

import { GET } from "./route";

describe("GET /api/repos/[repoId]", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, json: async () => ({}) } as Response);
    }) as unknown as typeof fetch;

    await GET(new Request("http://localhost/api/repos/x"), { params: { repoId: "../../etc/passwd" } });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("returns 401 when no session cookie is present", async () => {
    const res = await GET(new Request("http://localhost/api/repos/x"), { params: { repoId: "x" } });
    expect(res.status).toBe(401);
  });
});
