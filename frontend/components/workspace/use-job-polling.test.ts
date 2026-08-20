import { act, renderHook, waitFor } from "@testing-library/react";
import { useJobPolling } from "./use-job-polling";

describe("useJobPolling", () => {
  beforeEach(() => {
    jest.useFakeTimers({ legacyFakeTimers: false });
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("stops polling once the job reaches a terminal status", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "j1", status: "running", progress: 50 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "j1", status: "completed", progress: 100 }) });

    const { result } = renderHook(() => useJobPolling("j1"));

    await waitFor(() => expect(result.current.job?.status).toBe("running"));
    expect(result.current.polling).toBe(true);

    await act(async () => {
      jest.advanceTimersByTime(2000);
    });

    await waitFor(() => expect(result.current.job?.status).toBe("completed"));
    expect(result.current.polling).toBe(false);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("does nothing when jobId is undefined", () => {
    const { result } = renderHook(() => useJobPolling(undefined));
    expect(result.current.polling).toBe(false);
    expect(result.current.job).toBeNull();
    expect(result.current.pollingFailed).toBe(false);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("retries with backoff on a transient poll failure, keeping the last known job", async () => {
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "j1", status: "running", progress: 50 }) })
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "j1", status: "running", progress: 65 }) });

    const { result } = renderHook(() => useJobPolling("j1"));

    await waitFor(() => expect(result.current.job?.progress).toBe(50));
    expect(result.current.pollingFailed).toBe(false);
    expect(result.current.polling).toBe(true);

    // The next scheduled poll (after POLL_INTERVAL_MS) fails.
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });

    // A single dropped request shouldn't surface as "lost connection" or
    // clear the last known job -- it should be silently retried.
    expect(result.current.pollingFailed).toBe(false);
    expect(result.current.polling).toBe(true);
    expect(result.current.job?.progress).toBe(50);

    // First retry delay (1000ms) elapses and succeeds.
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });

    await waitFor(() => expect(result.current.job?.progress).toBe(65));
    expect(result.current.pollingFailed).toBe(false);
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it("surfaces pollingFailed without clearing the stale job once retries are exhausted", async () => {
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: "j1", status: "running", progress: 47 }),
    });
    // 5 consecutive failures: the poll scheduled right after the successful
    // one, plus all 4 backoff retries, all fail.
    for (let i = 0; i < 5; i++) {
      fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    }

    const { result } = renderHook(() => useJobPolling("j1"));

    await waitFor(() => expect(result.current.job?.progress).toBe(47));

    // Next scheduled poll (2000ms) + 4 backoff retries (1000, 2000, 4000, 8000ms).
    for (const delay of [2000, 1000, 2000, 4000, 8000]) {
      await act(async () => {
        await jest.advanceTimersByTimeAsync(delay);
      });
    }

    await waitFor(() => expect(result.current.pollingFailed).toBe(true));
    expect(result.current.polling).toBe(false);
    // The stale job data is preserved rather than wiped -- callers must
    // check `pollingFailed` explicitly instead of trusting `job` alone.
    expect(result.current.job).toEqual({ id: "j1", status: "running", progress: 47 });
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });
});
