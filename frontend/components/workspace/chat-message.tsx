"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Element, ElementContent } from "hast";

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

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
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
      <pre className="font-mono text-xs leading-relaxed">
        <code>{children}</code>
      </pre>
    </div>
  );
}

export function ChatMessage({ role, content }: { role: "user" | "assistant"; content: string }) {
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
                code({ className, children, ...props }) {
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
                  return <CodeBlock>{text}</CodeBlock>;
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
