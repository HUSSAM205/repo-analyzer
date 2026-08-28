import { render, screen, waitFor } from "@testing-library/react";
import { FileTree } from "./file-tree";
import type { FileTreeEntry } from "@/lib/types";

const readmeEntry: FileTreeEntry = { name: "README", path: "README", type: "file", children: null };

describe("FileTree", () => {
  it("re-fetches the file list when `polling` transitions from true to false", async () => {
    // Mirrors a freshly-submitted repo: the page mounts FileTree while the
    // analysis job is still running (`polling=true`), so the first fetch
    // races the background worker and comes back empty. Before the fix,
    // nothing re-triggered the fetch once the job actually finished, so the
    // tree stayed stuck on "No files found" forever. `polling` flipping to
    // false (the same signal RepoHeader uses for its status dot) must
    // trigger a real re-fetch that picks up the now-ingested files.
    let callCount = 0;
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      expect(url).toBe("/api/repos/repo-1/files");
      callCount += 1;
      return Promise.resolve({
        ok: true,
        json: async () => ({ entries: callCount === 1 ? [] : [readmeEntry] }),
      } as Response);
    }) as unknown as typeof fetch;

    const { rerender } = render(
      <FileTree repoId="repo-1" polling={true} selectedPath={null} onSelectFile={jest.fn()} />
    );

    await waitFor(() => expect(screen.getByText("No files found for this repository.")).toBeInTheDocument());
    expect(callCount).toBe(1);

    rerender(<FileTree repoId="repo-1" polling={false} selectedPath={null} onSelectFile={jest.fn()} />);

    await waitFor(() => expect(screen.getByText("README")).toBeInTheDocument());
    expect(callCount).toBe(2);
  });

  it("clears a stale error once a later re-fetch (triggered by polling going terminal) succeeds", async () => {
    // Regression test: a transient failure on the first (too-early) fetch
    // used to leave `error` set permanently -- even after the later
    // re-fetch succeeded and populated `entries`, the `if (error) return`
    // check still won and the tree stayed stuck showing the error.
    let callCount = 0;
    global.fetch = jest.fn(() => {
      callCount += 1;
      if (callCount === 1) {
        return Promise.resolve({ ok: false, status: 500 } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => ({ entries: [readmeEntry] }) } as Response);
    }) as unknown as typeof fetch;

    const { rerender } = render(
      <FileTree repoId="repo-1" polling={true} selectedPath={null} onSelectFile={jest.fn()} />
    );

    await waitFor(() => expect(screen.getByText("Could not load the file tree.")).toBeInTheDocument());

    rerender(<FileTree repoId="repo-1" polling={false} selectedPath={null} onSelectFile={jest.fn()} />);

    await waitFor(() => expect(screen.getByText("README")).toBeInTheDocument());
    expect(screen.queryByText("Could not load the file tree.")).not.toBeInTheDocument();
  });

  it("fetches once and renders entries when there is no in-flight job (polling starts and stays false)", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ entries: [readmeEntry] }),
    }) as unknown as typeof fetch;

    render(<FileTree repoId="repo-1" polling={false} selectedPath={null} onSelectFile={jest.fn()} />);

    expect(await screen.findByText("README")).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("re-fetches on a 'parsing' -> 'embedding' stage transition, well before the job reaches a terminal status", async () => {
    // The backend now commits `File` rows in their own transaction right
    // after parsing -- before the (slower) embedding step runs -- so the
    // file tree can be fully populated in the database while the job is
    // still non-terminal (`polling` stays true throughout this whole test:
    // the job never finishes). Before this fix, nothing re-triggered the
    // fetch until `polling` itself flipped to false at the very end of the
    // job, so this earlier "files already exist" moment was invisible to
    // the UI. Passing `stage` through and including it in the effect's
    // dependency list is what picks it up right when it actually happens.
    let callCount = 0;
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      expect(url).toBe("/api/repos/repo-1/files");
      callCount += 1;
      return Promise.resolve({
        ok: true,
        json: async () => ({ entries: callCount === 1 ? [] : [readmeEntry] }),
      } as Response);
    }) as unknown as typeof fetch;

    const { rerender } = render(
      <FileTree repoId="repo-1" polling={true} stage="parsing" selectedPath={null} onSelectFile={jest.fn()} />
    );

    await waitFor(() => expect(screen.getByText("No files found for this repository.")).toBeInTheDocument());
    expect(callCount).toBe(1);

    // Stage transitions to "embedding" -- `polling` stays true (the job
    // itself is nowhere near terminal), only `stage` changes.
    rerender(<FileTree repoId="repo-1" polling={true} stage="embedding" selectedPath={null} onSelectFile={jest.fn()} />);

    await waitFor(() => expect(screen.getByText("README")).toBeInTheDocument());
    expect(callCount).toBe(2);
  });

  it("does not re-fetch on a re-render where neither `polling` nor `stage` actually changed", async () => {
    let callCount = 0;
    global.fetch = jest.fn(() => {
      callCount += 1;
      return Promise.resolve({ ok: true, json: async () => ({ entries: [readmeEntry] }) } as Response);
    }) as unknown as typeof fetch;

    const { rerender } = render(
      <FileTree repoId="repo-1" polling={true} stage="parsing" selectedPath={null} onSelectFile={jest.fn()} />
    );

    await waitFor(() => expect(screen.getByText("README")).toBeInTheDocument());
    expect(callCount).toBe(1);

    // Same repoId/polling/stage, only the selection callback identity
    // changed -- a real re-render, but not one that should trigger a fetch.
    rerender(<FileTree repoId="repo-1" polling={true} stage="parsing" selectedPath={null} onSelectFile={jest.fn()} />);

    expect(callCount).toBe(1);
  });
});
