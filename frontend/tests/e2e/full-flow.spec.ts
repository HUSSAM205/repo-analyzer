import { test, expect } from "@playwright/test";
import { FIXTURE_REPO_URL, TEST_PASSWORD, uniqueEmail } from "./fixtures";

test("full user loop: register, analyze a repo, browse it, and chat", async ({ page }) => {
  const email = uniqueEmail();

  // Register
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(TEST_PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/repos$/, { timeout: 15000 });

  // Submit a repo for analysis
  await page.getByLabel("GitHub repository URL").fill(FIXTURE_REPO_URL);
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page).toHaveURL(/\/repos\/[^/]+\?job=/, { timeout: 15000 });

  // Wait for analysis to complete (poll indicator turns from yellow to green)
  await expect(page.locator("header .bg-emerald-400")).toBeVisible({ timeout: 60000 });

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
