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

describe("GET /api/repos/[repoId]/bootstrap", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("returns 401 without a session token", async () => {
    const response = await GET(new NextRequest("http://localhost/api/repos/x/bootstrap"), {
      params: { repoId: "x" },
    });
    expect(response.status).toBe(401);
  });

  it("passes through the backend's status and body unchanged", async () => {
    store.set("session_token", "test-token");
    const body = {
      stacks_detected: ["python"],
      services_detected: [],
      dockerfile: "FROM python:3.12-slim",
      docker_compose: "services:\n  python:",
      setup_script: "#!/usr/bin/env bash",
    };
    global.fetch = jest.fn().mockResolvedValue({
      status: 200,
      text: async () => JSON.stringify(body),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/bootstrap"), {
      params: { repoId: "x" },
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(body);
  });

  it("passes through a 409 unchanged (repo not ready yet)", async () => {
    store.set("session_token", "test-token");
    global.fetch = jest.fn().mockResolvedValue({
      status: 409,
      text: async () => JSON.stringify({ detail: "This repository hasn't finished analyzing yet." }),
    } as Response) as unknown as typeof fetch;

    const response = await GET(new NextRequest("http://localhost/api/repos/x/bootstrap"), {
      params: { repoId: "x" },
    });
    expect(response.status).toBe(409);
  });
});
