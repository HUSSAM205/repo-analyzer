/**
 * @jest-environment node
 */
import { GET } from "./route";

describe("GET /api/keepalive", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("proxies to the backend's keepalive endpoint and reports ok on success", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true }) as unknown as typeof fetch;

    const res = await GET();

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/keepalive"), expect.anything());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });

  it("reports a 502 when the backend responds with a failure status", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;

    const res = await GET();

    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ ok: false });
  });

  it("reports a 502 when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network error"));

    const res = await GET();

    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ ok: false });
  });
});
