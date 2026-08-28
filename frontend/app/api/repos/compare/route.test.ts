/**
 * @jest-environment node
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

import { NextRequest } from "next/server";
import { GET } from "./route";

describe("GET /api/repos/compare", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/compare?repo_a=a&repo_b=b"));
    expect(response.status).toBe(401);
  });

  it("returns 400 when repo_a or repo_b is missing", async () => {
    store.set("session_token", "test-token");
    const response = await GET(new NextRequest("http://localhost/api/repos/compare?repo_a=a"));
    expect(response.status).toBe(400);
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    const body = {
      repo_a: { repo_id: "a", name: "repo-a", url: "https://github.com/x/a", metrics: { file_count: 1 } },
      repo_b: { repo_id: "b", name: "repo-b", url: "https://github.com/x/b", metrics: { file_count: 2 } },
      deltas: { file_count_delta: 1 },
      security_verdict: "Both repos have a comparable security posture.",
      disclaimer: "...",
    };
    const fetchMock = jest.fn().mockResolvedValue({
      status: 200,
      text: async () => JSON.stringify(body),
    } as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/compare?repo_a=a&repo_b=b"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(body);
    expect(fetchMock.mock.calls[0][0]).toContain("repo_a=a&repo_b=b");
  });

  it("passes through a 409 unchanged (a repo not ready yet)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 409,
      text: async () => JSON.stringify({ detail: "This repository hasn't finished analyzing yet." }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/compare?repo_a=a&repo_b=b"));
    expect(response.status).toBe(409);
  });
});
