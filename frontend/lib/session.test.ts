const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
    set: (name: string, value: string) => {
      store.set(name, value);
    },
    delete: (name: string) => {
      store.delete(name);
    },
  }),
}));

import { clearSessionToken, getSessionToken, setSessionToken } from "./session";

describe("session token helpers", () => {
  afterEach(() => {
    store.clear();
  });

  it("returns undefined when no token is set", () => {
    expect(getSessionToken()).toBeUndefined();
  });

  it("round-trips a token through set/get", () => {
    setSessionToken("abc123");
    expect(getSessionToken()).toBe("abc123");
  });

  it("clears a token", () => {
    setSessionToken("abc123");
    clearSessionToken();
    expect(getSessionToken()).toBeUndefined();
  });
});
