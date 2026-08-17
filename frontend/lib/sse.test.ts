import { parseSSEChunk } from "./sse";

describe("parseSSEChunk", () => {
  it("parses a single complete frame", () => {
    const { events, remainder } = parseSSEChunk('event: token\ndata: {"text": "hi"}\n\n');
    expect(events).toEqual([{ type: "token", data: { text: "hi" } }]);
    expect(remainder).toBe("");
  });

  it("parses multiple frames in one buffer", () => {
    const buf = 'event: token\ndata: {"text": "a"}\n\nevent: token\ndata: {"text": "b"}\n\n';
    const { events } = parseSSEChunk(buf);
    expect(events).toHaveLength(2);
    expect(events[1].data).toEqual({ text: "b" });
  });

  it("holds back an incomplete trailing frame as remainder", () => {
    const { events, remainder } = parseSSEChunk('event: token\ndata: {"text": "a"}\n\nevent: to');
    expect(events).toHaveLength(1);
    expect(remainder).toBe("event: to");
  });

  it("skips a malformed frame without throwing", () => {
    const { events } = parseSSEChunk("event: token\ndata: not-json\n\n");
    expect(events).toEqual([]);
  });

  it("returns the whole buffer as remainder when nothing is complete yet", () => {
    const { events, remainder } = parseSSEChunk("event: tok");
    expect(events).toEqual([]);
    expect(remainder).toBe("event: tok");
  });
});
