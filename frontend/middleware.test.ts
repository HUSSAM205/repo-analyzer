/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

describe("middleware", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("does zero I/O -- never calls fetch, regardless of whether a session cookie is present", () => {
    // The whole point of this middleware: it used to `await fetch(...)`
    // the backend directly, which caused real 504
    // MIDDLEWARE_INVOCATION_TIMEOUT failures whenever the backend was
    // slow. It must now be provably synchronous/in-memory only.
    global.fetch = jest.fn();

    middleware(new NextRequest("http://localhost:3000/repos"));
    middleware(
      new NextRequest("http://localhost:3000/repos", {
        headers: new Headers({ cookie: "session_token=existing-token" }),
      })
    );

    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes the request through unchanged when a session cookie already exists", () => {
    const request = new NextRequest("http://localhost:3000/repos", {
      headers: new Headers({ cookie: "session_token=existing-token" }),
    });

    const response = middleware(request);

    // NextResponse.next() carries no redirect/location header.
    expect(response.headers.get("location")).toBeNull();
  });

  it("redirects to the bootstrap route, preserving the original destination, when no cookie exists", () => {
    const request = new NextRequest("http://localhost:3000/repos/abc?job=123");

    const response = middleware(request);

    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/api/auth/bootstrap");
    expect(location.searchParams.get("next")).toBe("/repos/abc?job=123");
  });

  it("excludes the bootstrap route itself from the matcher (would otherwise redirect to itself forever)", () => {
    const middlewareModule = require("./middleware");
    expect(middlewareModule.config.matcher[0]).toContain("api/auth/bootstrap");
  });

  it("excludes health and keepalive from the matcher (a stateless pinger must never mint a guest account)", () => {
    const middlewareModule = require("./middleware");
    expect(middlewareModule.config.matcher[0]).toContain("api/health");
    expect(middlewareModule.config.matcher[0]).toContain("api/keepalive");
  });
});
