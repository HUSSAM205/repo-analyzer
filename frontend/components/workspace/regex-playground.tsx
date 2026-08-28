"use client";

import { useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const FLAGS: { key: string; label: string; title: string }[] = [
  { key: "g", label: "g", title: "Global -- find all matches, not just the first" },
  { key: "i", label: "i", title: "Case-insensitive" },
  { key: "m", label: "m", title: "Multiline -- ^ and $ match at line breaks" },
  { key: "s", label: "s", title: "Dotall -- . also matches newlines" },
];

const DEFAULT_PATTERN = "\\b\\w+@\\w+\\.\\w+\\b";
const DEFAULT_TEST_STRING = "Contact us at support@example.com or sales@example.org for help.";

interface MatchResult {
  match: string;
  index: number;
  groups: string[];
}

function runRegex(pattern: string, flags: string, testString: string): { matches: MatchResult[]; error: string | null } {
  if (!pattern) return { matches: [], error: null };
  // "g" is added unconditionally for the highlighting pass below (matchAll
  // requires it) -- the user's own "g" toggle still controls whether more
  // than the first match is reported, applied separately.
  let regex: RegExp;
  try {
    regex = new RegExp(pattern, flags.includes("g") ? flags : flags + "g");
  } catch (err) {
    return { matches: [], error: err instanceof Error ? err.message : "Invalid regular expression" };
  }

  const matches: MatchResult[] = [];
  try {
    for (const m of testString.matchAll(regex)) {
      matches.push({ match: m[0], index: m.index ?? 0, groups: m.slice(1).map((g) => g ?? "") });
      if (!flags.includes("g")) break;
      // A zero-length match (e.g. pattern "a*" against "b") would otherwise
      // spin matchAll forever at the same index.
      if (m[0].length === 0) regex.lastIndex += 1;
    }
  } catch (err) {
    return { matches: [], error: err instanceof Error ? err.message : "Error while matching" };
  }
  return { matches, error: null };
}

function renderHighlighted(testString: string, matches: MatchResult[]) {
  if (matches.length === 0) return testString;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  matches.forEach((m, i) => {
    if (m.index > cursor) parts.push(testString.slice(cursor, m.index));
    parts.push(
      <mark key={i} className="rounded-sm bg-primary/30 text-foreground ring-1 ring-primary/50">
        {m.match || "​"}
      </mark>
    );
    cursor = m.index + m.match.length;
  });
  if (cursor < testString.length) parts.push(testString.slice(cursor));
  return parts;
}

export function RegexPlayground() {
  const [pattern, setPattern] = useState(DEFAULT_PATTERN);
  const [flags, setFlags] = useState("gi");
  const [testString, setTestString] = useState(DEFAULT_TEST_STRING);

  const { matches, error } = useMemo(() => runRegex(pattern, flags, testString), [pattern, flags, testString]);

  function toggleFlag(flag: string) {
    setFlags((prev) => (prev.includes(flag) ? prev.replace(flag, "") : prev + flag));
  }

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <div>
        <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-primary/80">Pattern</label>
        <div className="glass flex items-center gap-2 rounded-md p-2">
          <span className="font-mono text-sm text-muted-foreground">/</span>
          <input
            type="text"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            spellCheck={false}
            aria-label="Regular expression pattern"
            className="flex-1 bg-transparent font-mono text-sm text-foreground outline-none"
          />
          <span className="font-mono text-sm text-muted-foreground">/{flags}</span>
        </div>
        <div className="mt-2 flex items-center gap-1.5">
          {FLAGS.map((f) => (
            <button
              key={f.key}
              type="button"
              title={f.title}
              onClick={() => toggleFlag(f.key)}
              className={cn(
                "h-6 w-6 rounded-md border font-mono text-xs font-semibold transition-colors",
                flags.includes(f.key)
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-zinc-800/60 text-muted-foreground hover:text-foreground"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-primary/80">Test string</label>
        <textarea
          value={testString}
          onChange={(e) => setTestString(e.target.value)}
          spellCheck={false}
          aria-label="Test string"
          rows={4}
          className="glass w-full resize-none rounded-md p-2.5 font-mono text-sm text-foreground outline-none"
        />
      </div>

      {error ? (
        <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2.5 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {error}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto">
          <p className="text-xs text-muted-foreground">
            {matches.length} match{matches.length === 1 ? "" : "es"}
          </p>
          <div className="glass whitespace-pre-wrap rounded-md p-2.5 font-mono text-sm leading-relaxed text-zinc-300">
            {renderHighlighted(testString, matches)}
          </div>
          {matches.some((m) => m.groups.length > 0) && (
            <ul className="space-y-1 text-xs">
              {matches.map((m, i) =>
                m.groups.length === 0 ? null : (
                  <li key={i} className="rounded-md border border-zinc-800/60 px-2.5 py-1.5">
                    <span className="text-muted-foreground">Match {i + 1}:</span>{" "}
                    {m.groups.map((g, gi) => (
                      <span key={gi} className="mr-2 font-mono text-primary">
                        ${gi + 1}=&quot;{g}&quot;
                      </span>
                    ))}
                  </li>
                )
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
