import { randomUUID } from "crypto";

export function uniqueEmail(): string {
  return `e2e-${randomUUID()}@example.com`;
}

export const TEST_PASSWORD = "supersecret123";

// Set by tests/e2e/global-setup.ts, which spins up a local git server (the
// same fixture files sub-project 1's worker tests use, see
// fixture-git-server.ts) instead of relying on github.com being reachable --
// the spec requires no live GitHub or LLM calls in this suite by default.
const fixtureRepoUrl = process.env.E2E_FIXTURE_REPO_URL;
if (!fixtureRepoUrl) {
  throw new Error(
    "E2E_FIXTURE_REPO_URL is not set. This suite's Playwright config must run tests/e2e/global-setup.ts " +
      "(via the `globalSetup` option) before any spec that imports FIXTURE_REPO_URL."
  );
}
export const FIXTURE_REPO_URL = fixtureRepoUrl;
