import { highlightCode, languageForPath } from "./highlight";

describe("languageForPath", () => {
  it("maps known extensions to Shiki language ids", () => {
    expect(languageForPath("app/main.py")).toBe("python");
    expect(languageForPath("src/index.ts")).toBe("typescript");
  });

  it("falls back to 'text' for unknown extensions", () => {
    expect(languageForPath("README")).toBe("text");
  });
});

describe("highlightCode", () => {
  it("produces highlighted HTML for a known language", async () => {
    const html = await highlightCode("def foo():\n    return 1\n", "main.py");
    expect(html).toContain("<pre");
    expect(html).toContain("foo");
  }, 15000);

  it("falls back gracefully for an unsupported language without throwing", async () => {
    const html = await highlightCode("plain text content", "notes.txt");
    expect(html).toContain("plain text content");
  }, 15000);
});
