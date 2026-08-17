const nextJest = require("next/jest");

const createJestConfig = nextJest({ dir: "./" });

const customJestConfig = {
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
  testEnvironment: "jest-environment-jsdom",
  // The plain "<rootDir>/tests/e2e/" pattern silently failed to match in
  // this checkout. On Windows, Jest's own path-sep normalization
  // (replacePathSepForRegex) does correctly turn the "/" in a pattern like
  // this into "\\" so it lines up with the backslashed resolved test path
  // -- that part works fine in an ordinary checkout. What breaks it here is
  // this worktree's path containing a dot-directory (".worktrees"): that
  // normalization walks the pattern converting "/" to "\\" but skips a
  // separator when it's immediately followed by a regex-special character,
  // so the "/" right before ".worktrees" survives as a literal "\." instead
  // of becoming "\\" -- producing a regex that can't match the actual
  // (fully backslashed) resolved path, so tests/e2e/*.spec.ts files fell
  // through to being run as Jest tests instead of being excluded for
  // `npx playwright test`. A character class matching either separator
  // sidesteps the normalization step entirely and is robust regardless of
  // dot-directories in the path. Note: the pre-existing "<rootDir>/node_modules/"
  // pattern just below, and "<rootDir>/.next/" in modulePathIgnorePatterns,
  // carry this same latent hazard in any dot-prefixed checkout path -- they
  // happen to still work here only because no test files ever live inside
  // node_modules/.next for that pattern's failure mode to surface.
  testPathIgnorePatterns: ["<rootDir>/node_modules/", "[\\\\/]tests[\\\\/]e2e[\\\\/]"],
  modulePathIgnorePatterns: ["<rootDir>/.next/"],
};

// next/jest's own generated config always includes an unconditional
// "node_modules" ignore pattern alongside whatever we pass in, and
// transformIgnorePatterns entries are OR'd — so appending a negated
// pattern via customJestConfig has no effect. shiki (and its @shikijs/*
// deps), react-markdown, remark-gfm, and their whole unified/mdast/hast/
// micromark/vfile dependency tree ship ESM-only builds with no CJS entry
// point, so they must be run through the SWC transform instead of being
// left as raw node_modules.
// We override the merged patterns after the fact so only ours applies.
const ESM_PACKAGES =
  "shiki|@shikijs|react-markdown|remark-.*|rehype-.*|mdast-.*|micromark.*|unist-util-.*|unified|vfile.*|hast-util-.*|hast-.*|bail|trough|is-plain-obj|is-alphabetical|is-alphanumerical|is-decimal|is-hexadecimal|zwitch|ccount|longest-streak|markdown-table|property-information|space-separated-tokens|comma-separated-tokens|trim-lines|decode-named-character-reference|character-entities.*|character-reference-invalid|parse-entities|stringify-entities|html-url-attributes|estree-util-is-identifier-name|devlop|escape-string-regexp|@ungap/structured-clone";

module.exports = async () => {
  const config = await createJestConfig(customJestConfig)();
  config.transformIgnorePatterns = [`/node_modules/(?!(${ESM_PACKAGES})/)`];
  return config;
};
