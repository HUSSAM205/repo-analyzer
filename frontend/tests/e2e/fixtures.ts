import { randomUUID } from "crypto";

export function uniqueEmail(): string {
  return `e2e-${randomUUID()}@example.com`;
}

export const TEST_PASSWORD = "supersecret123";
export const FIXTURE_REPO_URL = "https://github.com/octocat/Hello-World";
