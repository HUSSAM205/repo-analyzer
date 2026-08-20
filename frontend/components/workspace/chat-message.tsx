"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, FileCode2 } from "lucide-react";
import { highlightCode } from "@/lib/highlight";
import { cn } from "@/lib/utils";
import type { Element, ElementContent } from "hast";

// Matches the backend agent's citation format (see
// backend/app/core/agent.py's system prompt): an inline code span like
// `path/to/file.py:12-18` -- a file path plus a 1-based line or line-range
// suffix. Rendered as a clickable pill instead of a plain inline-code span.
const CITATION_PATTERN = /^[\w./-]+\.\w+:\d+(-\d+)?$/;

// Recursively collect the raw text content of a hast node — used to read a
// fenced code block's literal text straight from the tree, regardless of
// whether react-markdown gave the <code> element a `language-xxx` className
// (it only does that when the fence has a language tag, e.g. ```python;
// a plain ``` fence with no language produces a <code> with no className
// at all, so className presence can't be used to detect "this is a block").
function getNodeText(node: Element | ElementContent | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value;
  if ("children" in node) {
    return node.children.map(getNodeText).join("");
  }
  return "";
}

// `language` is the fence's language tag (e.g. "python"), already stripped
// of the `language-` className prefix by the `pre` renderer below -- or
// `undefined` for an untagged ``` fence, in which case this intentionally
// never calls Shiki at all and just renders plain text, matching prior
// behavior (cheaper, and there's no language to highlight against anyway).
function CodeBlock({ children, language }: { children: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  // Effect-driven, same pattern as code-viewer.tsx: `highlightCode` is
  // async, so start out showing the plain-text version and swap in the
  // highlighted HTML once it resolves.
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    if (!language) {
      setHtml(null);
      return;
    }
    let cancelled = false;
    highlightCode(children, language)
      .then((highlighted) => {
        if (!cancelled) setHtml(highlighted);
      })
      .catch(() => {
        if (!cancelled) setHtml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [children, language]);

  async function handleCopy() {
    // Always copies the raw, un-highlighted text -- unaffected by whether
    // Shiki has resolved yet.
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="group relative my-2 overflow-x-auto rounded-md border border-border bg-black/30 p-3">
      <button
        type="button"
        onClick={handleCopy}
        aria-label="Copy code"
        className="absolute right-2 top-2 rounded-md border border-border bg-card p-1 opacity-0 transition-opacity group-hover:opacity-100"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      {html ? (
        <div
          className="shiki-chat-block font-mono text-xs leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className="font-mono text-xs leading-relaxed">
          <code>{children}</code>
        </pre>
      )}
    </div>
  );
}

export function ChatMessage({
  role,
  content,
  onCitationClick,
}: {
  role: "user" | "assistant";
  content: string;
  onCitationClick?: (path: string) => void;
}) {
  const isUser = role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[90%] rounded-lg px-3 py-2 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "border border-border bg-card"
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none prose-p:my-1.5 prose-pre:my-0 prose-pre:bg-transparent prose-pre:p-0">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // A fenced code block always produces a <pre><code> pair in the
                // hast tree; an inline code span never has a <pre> ancestor. So
                // `pre` is the structurally reliable place to detect "this is a
                // block" — unlike checking the <code> element's `className`,
                // which is only set when the fence has a language tag.
                code({ className, children, node, ...props }) {
                  const text = getNodeText(node).trim();
                  if (CITATION_PATTERN.test(text)) {
                    const path = text.replace(/:\d+(-\d+)?$/, "");
                    return (
                      <button
                        type="button"
                        onClick={() => onCitationClick?.(path)}
                        className="mx-0.5 inline-flex items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 align-middle font-mono text-[11px] text-primary transition-colors hover:bg-primary/20"
                      >
                        <FileCode2 className="h-3 w-3 shrink-0" />
                        {text}
                      </button>
                    );
                  }
                  return (
                    <code className={cn("rounded bg-black/30 px-1 py-0.5 font-mono text-xs", className)} {...props}>
                      {children}
                    </code>
                  );
                },
                pre({ node }) {
                  const codeNode = node?.children.find(
                    (child): child is Element => child.type === "element" && child.tagName === "code"
                  );
                  const text = getNodeText(codeNode ?? node).replace(/\n$/, "");
                  const classNames = codeNode?.properties?.className;
                  const langClass = Array.isArray(classNames)
                    ? classNames.find((c): c is string => typeof c === "string" && c.startsWith("language-"))
                    : undefined;
                  const language = langClass?.slice("language-".length);
                  return <CodeBlock language={language}>{text}</CodeBlock>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
