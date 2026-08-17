import postcss from "postcss";
import tailwindcss from "tailwindcss";
import tailwindConfig from "./tailwind.config";

// Regression test for the finding that every `prose*` class used to style
// assistant chat markdown (components/workspace/chat-message.tsx) was dead
// CSS: `@tailwindcss/typography` was never registered in
// tailwind.config.ts's `plugins` array, so Tailwind emitted nothing for
// `prose`/`prose-invert`/etc, and Preflight's reset then made every heading
// and list in an AI answer render as unstyled, unmarked, unindented text.
//
// A test that only checks `tailwind.config.ts`'s `plugins` array is
// non-empty would pass even if the wrong plugin were registered, or if the
// content globs didn't pick up chat-message.tsx's classes. Instead this runs
// the *real* Tailwind/PostCSS build (the same pipeline `next build` and `next
// dev` use, see postcss.config.js) against chat-message.tsx and asserts the
// generated CSS contains rules that only `@tailwindcss/typography` produces
// -- proving the plugin is wired up and actually emitting the styles that
// make headings and bulleted lists render correctly, not just that a
// `require(...)` call for it exists somewhere.
describe("Tailwind typography plugin", () => {
  it("emits real CSS for the prose classes chat-message.tsx renders assistant markdown with", async () => {
    const result = await postcss([tailwindcss(tailwindConfig)]).process(
      "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
      { from: undefined }
    );
    const css = result.css;

    // Unordered lists get a visible marker and are indented -- exactly the
    // "renders unmarked/unindented" symptom from the finding.
    expect(css).toMatch(/\.prose\s*:where\(ul\)[^{]*\{[^}]*list-style-type:\s*disc/);
    expect(css).toMatch(/\.prose\s*:where\(ul[^)]*\)[^{]*\{[^}]*padding-inline-start/);

    // Headings get real font-weight/font-size, not plain body text -- the
    // other symptom from the finding.
    expect(css).toMatch(/\.prose\s*:where\(h1\)[^{]*\{[^}]*font-weight:\s*800/);

    // `prose-invert` (used for the dark chat bubble) resolves its custom
    // properties -- this selector only exists when the typography plugin is
    // actually registered, not e.g. a leftover unused import.
    expect(css).toMatch(/\.prose-invert\s*\{[^}]*--tw-prose-body/);
  });
});
