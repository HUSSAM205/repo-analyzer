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
import { POST } from "./route";

describe("POST /api/feedback", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await POST(
      new NextRequest("http://localhost/api/feedback", {
        method: "POST",
        body: JSON.stringify({ type: "bug", message: "x" }),
      })
    );
    expect(response.status).toBe(401);
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    const fetchMock = jest.fn().mockResolvedValue({
      status: 202,
      text: async () => JSON.stringify({ sent: true }),
    } as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    const response = await POST(
      new NextRequest("http://localhost/api/feedback", {
        method: "POST",
        body: JSON.stringify({ type: "bug", message: "it's broken" }),
      })
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ sent: true });
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/feedback");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer test-token");
  });

  it("passes through a 422 unchanged (invalid payload)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 422,
      text: async () => JSON.stringify({ detail: "invalid" }),
    } as Response) as unknown as typeof fetch;

    const response = await POST(
      new NextRequest("http://localhost/api/feedback", { method: "POST", body: JSON.stringify({ type: "bug", message: "" }) })
    );
    expect(response.status).toBe(422);
  });
});
