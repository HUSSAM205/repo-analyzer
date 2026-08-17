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
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
