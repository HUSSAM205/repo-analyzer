import { createHighlighter, type Highlighter } from "shiki";

const EXTENSION_TO_LANG: Record<string, string> = {
  py: "python",
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  go: "go",
  java: "java",
  json: "json",
  md: "markdown",
  yml: "yaml",
  yaml: "yaml",
  sh: "bash",
  css: "css",
  html: "html",
};

const SUPPORTED_LANGS = Array.from(new Set(Object.values(EXTENSION_TO_LANG)));

// Shiki's codeToHtml() is a synchronous tokenize-and-render pass. Run on a
// large generated/minified/vendored file with no guard, it can noticeably
// freeze the tab with no warning to the user. ~300KB is comfortably above
// any normal hand-written source file while still catching the worst
// offenders (bundles, lockfiles, minified vendor drops, etc).
export const MAX_HIGHLIGHT_LENGTH = 300_000;

export function exceedsHighlightLimit(content: string): boolean {
  return content.length > MAX_HIGHLIGHT_LENGTH;
}

let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({ themes: ["tokyo-night"], langs: SUPPORTED_LANGS });
  }
  return highlighterPromise;
}

export function languageForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TO_LANG[ext] ?? "text";
}

export async function highlightCode(code: string, pathOrLanguage: string): Promise<string> {
  const lang = pathOrLanguage.includes(".") ? languageForPath(pathOrLanguage) : pathOrLanguage;
  const highlighter = await getHighlighter();
  const loadedLangs = highlighter.getLoadedLanguages();
  const effectiveLang = loadedLangs.includes(lang) ? lang : "text";
  return highlighter.codeToHtml(code, { lang: effectiveLang, theme: "tokyo-night" });
}
