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
