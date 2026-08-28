import { test, expect } from "@playwright/test";
import { FIXTURE_REPO_URL } from "./fixtures";

test("full guest loop: analyze a repo, browse it, and chat", async ({ page }) => {
  // Visiting the app lands directly in the workspace -- a guest session is
  // minted transparently, no registration or login required.
  await page.goto("/");
  await expect(page).toHaveURL(/\/repos$/, { timeout: 15000 });

  // Submit a repo for analysis
  await page.getByLabel("GitHub repository URL").fill(FIXTURE_REPO_URL);
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page).toHaveURL(/\/repos\/[^/]+\?job=/, { timeout: 15000 });

  // Wait for analysis to complete (poll indicator turns from yellow to green).
  // Uses a dedicated testid (rather than a CSS-class locator) so this can't
  // accidentally match AppHeader's unrelated backend-health dot, which also
  // renders as a `header .bg-emerald-400` element once the global header
  // is on every page.
  await expect(page.getByTestId("repo-status")).toBeVisible({ timeout: 60000 });

  // Browse the file tree and open a file
  const fileNode = page.getByText("README", { exact: false }).first();
  await fileNode.click();
  await expect(page.locator("pre")).toBeVisible({ timeout: 10000 });

  // Start a conversation and send a message
  await page.getByLabel("New conversation").click();
  await page.getByPlaceholder("Ask about this repo...").fill("What does this repository contain?");
  await page.getByLabel("Send message").click();

  // Expect the fake provider's scripted response to appear
  await expect(page.getByText(/fake LLM provider/i)).toBeVisible({ timeout: 20000 });

  // Reload and confirm the conversation persisted
  await page.reload();
  await expect(page.getByText(/fake LLM provider/i)).toBeVisible({ timeout: 10000 });
});
