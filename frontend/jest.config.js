const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

const customJestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testEnvironment: "jest-environment-jsdom",
  testPathIgnorePatterns: ["<rootDir>/node_modules/", "<rootDir>/tests/e2e/"],
  modulePathIgnorePatterns: ["<rootDir>/.next/"],
};

// next/jest's own generated config always includes an unconditional
// "node_modules" ignore pattern alongside whatever we pass in, and
// transformIgnorePatterns entries are OR'd — so appending a negated
// pattern via customJestConfig has no effect. shiki (and its @shikijs/*
// deps) ship ESM-only builds with no CJS entry point, so they must be
// run through the SWC transform instead of being left as raw node_modules.
// We override the merged patterns after the fact so only ours applies.
module.exports = async () => {
  const config = await createJestConfig(customJestConfig)();
  config.transformIgnorePatterns = ["/node_modules/(?!(shiki|@shikijs)/)"];
  return config;
};
