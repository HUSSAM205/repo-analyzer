import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TextEncoder, TextDecoder } from "util";
import { ChatPanel } from "./chat-panel";

// This jsdom test environment doesn't provide TextEncoder/TextDecoder as
// globals (unlike a real browser), but chat-panel.tsx's streaming reader
// loop calls `new TextDecoder()` directly. Polyfill from Node's `util` so
// the real handleSend code path -- not a mock of it -- runs in this suite.
// Node's `util` types for these differ slightly from the DOM lib types
// (e.g. TextDecoder#decode's `input` parameter), so this assigns through
// `any` rather than fighting the two declaration sets into alignment.
(global as any).TextEncoder = TextEncoder;
(global as any).TextDecoder = TextDecoder;

function sseFrame(type: string, data: unknown) {
  return `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
}

// A minimal stand-in for a fetch Response's streaming `body`: just enough of
// the ReadableStream reader surface (`getReader().read()`) for chat-panel's
// reader loop to consume, without depending on a real ReadableStream global
// (also missing in this test environment).
function makeStreamingBody(frames: string[]) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    getReader() {
      return {
        async read() {
          if (i < frames.length) {
            const chunk = encoder.encode(frames[i]);
            i += 1;
            return { done: false, value: chunk };
          }
          return { done: true, value: undefined };
        },
      };
    },
  };
}

describe("ChatPanel streaming", () => {
  const conversation = { id: "c1", repo_id: "repo-1", title: "New conversation", created_at: "" };

  it("refetches messages instead of rendering a blank bubble when 'done' arrives with no token events", async () => {
    // Mirrors the backend's agent give-up path (max tool-call iterations
    // with no textual answer): "done" fires with zero preceding "token"
    // events, so the client's locally-accumulated finalText is empty even
    // though the backend actually persisted real explanatory text.
    const persistedMessages = [
      { id: "m1", role: "user", content: "Find the answer", created_at: "" },
      {
        id: "m2",
        role: "assistant",
        content: "I couldn't find a definitive answer after searching the code.",
        created_at: "",
      },
    ];

    let messagesGetCount = 0;

    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";

      if (url === "/api/repos/repo-1/conversations" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [conversation] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "GET") {
        messagesGetCount += 1;
        // 1st call: initial history load for the newly-active conversation
        // (empty). 2nd call: the post-"done" refetch triggered by the empty
        // finalText -- this is the one that should surface the real
        // persisted text instead of a blank bubble.
        return Promise.resolve({
          ok: true,
          json: async () => (messagesGetCount === 1 ? [] : persistedMessages),
        } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "POST") {
        return Promise.resolve({
          ok: true,
          body: makeStreamingBody([sseFrame("done", { message_id: "m2" })]),
        } as unknown as Response);
      }
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    }) as unknown as typeof fetch;

    render(<ChatPanel repoId="repo-1" />);

    // Wait for the fetched conversation to become active -- the chat input
    // is disabled until then.
    const textbox = screen.getByPlaceholderText("Ask about this repo...");
    await waitFor(() => expect(textbox).not.toBeDisabled());

    await userEvent.type(textbox, "Find the answer");
    await userEvent.click(screen.getByLabelText("Send message"));

    expect(
      await screen.findByText("I couldn't find a definitive answer after searching the code.")
    ).toBeInTheDocument();
    expect(messagesGetCount).toBeGreaterThanOrEqual(2);
  });
});
