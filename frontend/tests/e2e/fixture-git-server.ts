import { execFileSync } from "child_process";
import { randomUUID } from "crypto";
import fs from "fs";
import http from "http";
import os from "os";
import path from "path";

// Sub-project 1's worker integration tests (backend/tests/integration/test_worker_tasks.py)
// avoid a live GitHub clone by initializing a real local git repo from the
// checked-in fixture files at backend/tests/fixtures/sample_repo and pointing
// `analyze_repo` at that local path directly. This suite can't do quite the
// same thing: it drives the app through the real HTTP API, and
// `RepoAnalyzeRequest.repo_url` (backend/app/schemas/repos.py) is a pydantic
// `HttpUrl`, which only accepts `http`/`https` schemes -- a bare filesystem
// path or `file://` URL would fail validation before the request ever
// reaches `clone_repo`.
//
// So this mirrors the same underlying fixture (same files, same "git init +
// commit a local repo" mechanism) but serves it over git's "dumb HTTP"
// transport: a bare repo with `git update-server-info` run against it is
// just a directory of static files that any static file server can serve,
// and the system `git` binary (which `GitPython`'s `clone_from` shells out
// to, see backend/app/core/ingestion.py) knows how to clone from a plain
// HTTP URL pointing at one -- no live network, no GitHub, no smart-HTTP
// server needed.

const FIXTURE_SAMPLE_REPO = path.resolve(__dirname, "../../../backend/tests/fixtures/sample_repo");

export interface FixtureRepoServer {
  url: string;
  stop: () => Promise<void>;
}

function git(args: string[], cwd: string): void {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

function copyDirRecursive(src: string, dest: string): void {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDirRecursive(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function startStaticServer(rootDir: string, host: string): Promise<http.Server> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      try {
        const requestUrl = new URL(req.url ?? "/", "http://localhost");
        const relativePath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, "");
        const resolved = path.resolve(rootDir, relativePath);
        // Dumb-HTTP git only ever needs plain, non-traversing GETs for files
        // under the served repo (HEAD, info/refs, objects/**); reject
        // anything that would resolve outside rootDir.
        if (!resolved.startsWith(path.resolve(rootDir)) || req.method !== "GET") {
          res.writeHead(404).end();
          return;
        }
        const stat = fs.existsSync(resolved) ? fs.statSync(resolved) : null;
        if (!stat || !stat.isFile()) {
          res.writeHead(404).end();
          return;
        }
        res.writeHead(200, { "Content-Type": "application/octet-stream", "Content-Length": stat.size });
        fs.createReadStream(resolved).pipe(res);
      } catch {
        res.writeHead(500).end();
      }
    });
    server.on("error", reject);
    server.listen(0, host, () => resolve(server));
  });
}

// Starts a local, deterministic stand-in for a GitHub remote: a bare git repo
// (containing the same fixture files sub-project 1's worker tests use),
// served over dumb HTTP from an ephemeral local port. Returns the clone URL
// to submit through the app and a `stop()` to tear the server + temp files
// down afterwards.
export async function startFixtureRepoServer(): Promise<FixtureRepoServer> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "repo-analyzer-e2e-fixture-"));
  const workDir = path.join(root, "work");
  const serveDir = path.join(root, "serve");
  const bareRepoDir = path.join(serveDir, "sample-repo.git");

  copyDirRecursive(FIXTURE_SAMPLE_REPO, workDir);

  git(["init", "-b", "main", "-q"], workDir);
  git(["-c", "user.email=e2e@example.com", "-c", "user.name=e2e", "add", "-A"], workDir);
  git(["-c", "user.email=e2e@example.com", "-c", "user.name=e2e", "commit", "-q", "-m", "initial commit"], workDir);

  fs.mkdirSync(serveDir, { recursive: true });
  git(["clone", "--bare", "-q", workDir, bareRepoDir], root);
  git(["update-server-info"], bareRepoDir);

  // Bind on all interfaces so a containerized worker (e.g. docker-compose's
  // `worker` service, reaching the host via `host.docker.internal`) can
  // clone from it too, not just processes on localhost.
  const server = await startStaticServer(serveDir, "0.0.0.0");
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Fixture git server did not bind to a TCP port");
  }

  const host = process.env.E2E_FIXTURE_REPO_HOST ?? "127.0.0.1";
  const url = `http://${host}:${address.port}/sample-repo.git`;

  return {
    url,
    async stop() {
      await new Promise<void>((resolve, reject) => {
        server.close((err) => (err ? reject(err) : resolve()));
      });
      fs.rmSync(root, { recursive: true, force: true });
    },
  };
}
