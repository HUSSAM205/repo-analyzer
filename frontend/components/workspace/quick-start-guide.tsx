"use client";

import { useEffect, useState } from "react";
import { Rocket } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import type { FileTreeEntry, FileTreeResponse } from "@/lib/types";

interface Step {
  label: string;
  command: string;
}

// Purely deterministic (manifest-filename detection over the file tree
// already fetched for the Files pane) -- no LLM call, so this is instant
// and never fails/degrades the way the other three (LLM-derived) flagship
// tools can.
function flattenFilePaths(entries: FileTreeEntry[]): string[] {
  const paths: string[] = [];
  for (const entry of entries) {
    if (entry.type === "file") {
      paths.push(entry.path);
    } else if (entry.children) {
      paths.push(...flattenFilePaths(entry.children));
    }
  }
  return paths;
}

function detectSteps(paths: string[]): Step[] {
  const topLevel = new Set(paths.filter((p) => !p.includes("/")));
  const steps: Step[] = [];

  if (topLevel.has("package.json")) {
    steps.push({ label: "Install dependencies", command: "npm install" });
    steps.push({ label: "Run the dev server", command: "npm run dev" });
  }
  if (topLevel.has("requirements.txt")) {
    steps.push({ label: "Create a virtual environment", command: "python -m venv venv && source venv/bin/activate" });
    steps.push({ label: "Install dependencies", command: "pip install -r requirements.txt" });
  } else if (topLevel.has("pyproject.toml")) {
    steps.push({ label: "Install dependencies", command: "pip install -e ." });
  }
  if (topLevel.has("go.mod")) {
    steps.push({ label: "Download dependencies", command: "go mod download" });
    steps.push({ label: "Run the project", command: "go run ." });
  }
  if (topLevel.has("Cargo.toml")) {
    steps.push({ label: "Build the project", command: "cargo build" });
    steps.push({ label: "Run the project", command: "cargo run" });
  }
  if (topLevel.has("docker-compose.yml") || topLevel.has("docker-compose.yaml")) {
    steps.push({ label: "Run with Docker Compose", command: "docker compose up" });
  } else if (topLevel.has("Dockerfile")) {
    steps.push({ label: "Build and run with Docker", command: "docker build -t app . && docker run app" });
  }
  if (topLevel.has("Makefile")) {
    steps.push({ label: "See available commands", command: "make help" });
  }

  return steps;
}

export function QuickStartGuide({ repoId }: { repoId: string }) {
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSteps(null);
    setError(false);

    apiFetch(`/api/repos/${repoId}/files`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load file tree");
        return res.json() as Promise<FileTreeResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        setSteps(detectSteps(flattenFilePaths(data.entries)));
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [repoId]);

  if (error) {
    return <p className="p-6 text-center text-sm text-destructive">Could not load the file tree.</p>;
  }

  if (steps === null) {
    return <p className="p-6 text-center text-sm text-muted-foreground">Detecting how to run this project...</p>;
  }

  if (steps.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-6 text-center">
        <Rocket className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          No recognized manifest file (package.json, requirements.txt, Dockerfile, ...) was found at the repo root.
        </p>
      </div>
    );
  }

  return (
    <ol className="space-y-3 p-3">
      {steps.map((step, i) => (
        <li key={i} className="glass rounded-md p-3">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-primary/80">
            {i + 1}. {step.label}
          </p>
          <code className="block overflow-x-auto rounded bg-black/30 px-2.5 py-1.5 font-mono text-xs text-zinc-200">
            {step.command}
          </code>
        </li>
      ))}
    </ol>
  );
}
