export interface ParsedSSEEvent {
  type: string;
  data: unknown;
}

export function parseSSEChunk(buffer: string): { events: ParsedSSEEvent[]; remainder: string } {
  const events: ParsedSSEEvent[] = [];
  const frames = buffer.split("\n\n");
  const remainder = frames.pop() ?? "";

  for (const frame of frames) {
    if (!frame.trim()) continue;
    const lines = frame.split("\n");
    const eventLine = lines.find((l) => l.startsWith("event: "));
    const dataLine = lines.find((l) => l.startsWith("data: "));
    if (!eventLine || !dataLine) continue;
    const type = eventLine.slice("event: ".length);
    const rawData = dataLine.slice("data: ".length);
    try {
      events.push({ type, data: JSON.parse(rawData) });
    } catch {
      // Malformed frame -- skip it rather than crash the stream.
    }
  }

  return { events, remainder };
}
