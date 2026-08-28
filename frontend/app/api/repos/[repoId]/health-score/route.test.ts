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

describe("GET /api/repos/[repoId]/health-score", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/x/health-score"), {
      params: { repoId: "x" },
    });
    expect(response.status).toBe(401);
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    const body = {
      overall_score: 75,
      sub_scores: { documentation: 100, testing: 50, automation: 70, quality: 80 },
      commentary: "Solid.",
      signals: { has_readme: true, has_tests: true, has_ci: true, has_license: false },
    };
    global.fetch = jest.fn().mockResolvedValue({
      status: 200,
      text: async () => JSON.stringify(body),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/health-score"), {
      params: { repoId: "x" },
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(body);
  });
});
