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

describe("GET /api/repos/[repoId]/flow-map", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/x/flow-map"), { params: { repoId: "x" } });
    expect(response.status).toBe(401);
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    const body = { diagram: "flowchart TD\n  A --> B" };
    global.fetch = jest.fn().mockResolvedValue({
      status: 200,
      text: async () => JSON.stringify(body),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/flow-map"), { params: { repoId: "x" } });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(body);
  });

  it("passes through a 503 unchanged (AI temporarily unavailable)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 503,
      text: async () => JSON.stringify({ detail: "The AI provider is temporarily unavailable. Please try again." }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/flow-map"), { params: { repoId: "x" } });
    expect(response.status).toBe(503);
  });
});
