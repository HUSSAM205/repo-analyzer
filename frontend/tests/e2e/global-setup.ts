import type { FullConfig } from "@playwright/test";
import { startFixtureRepoServer } from "./fixture-git-server";

// Starts the local fixture-repo git server once for the whole Playwright
// run and publishes its URL via an env var so tests/e2e/fixtures.ts can pick
// it up. Playwright spawns test worker processes only after this function
// (and any globalSetup across the config) resolves, and those workers
// inherit `process.env` as of that spawn -- the same mechanism Playwright's
// own docs use for passing global-setup state to tests. The returned
// function is Playwright's supported way to run teardown logic tied to this
// setup, in place of a separate `globalTeardown` config entry.
export default async function globalSetup(_config: FullConfig) {
  const fixtureServer = await startFixtureRepoServer();
  process.env.E2E_FIXTURE_REPO_URL = fixtureServer.url;

  return async () => {
    await fixtureServer.stop();
  };
}
