import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BootstrapPanel } from "./bootstrap-panel";

Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

describe("BootstrapPanel", () => {
  it("fetches automatically on mount and shows the Dockerfile by default", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        stacks_detected: ["python"],
        services_detected: ["postgres"],
        dockerfile: "FROM python:3.12-slim AS python",
        docker_compose: "services:\n  python:",
        setup_script: "#!/usr/bin/env bash",
      }),
    }) as unknown as typeof fetch;

    render(<BootstrapPanel repoId="r1" />);

    expect(await screen.findByText(/FROM python:3\.12-slim/)).toBeInTheDocument();
    expect(screen.getByText((_, el) => el?.textContent === "Detected: python + postgres")).toBeInTheDocument();
  });

  it("switches between Dockerfile, docker-compose.yml, and setup.sh tabs", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        stacks_detected: ["node"],
        services_detected: [],
        dockerfile: "FROM node:20-alpine AS node",
        docker_compose: "services:\n  node:",
        setup_script: "#!/usr/bin/env bash\nnpm install",
      }),
    }) as unknown as typeof fetch;

    render(<BootstrapPanel repoId="r1" />);
    await screen.findByText(/FROM node:20-alpine/);

    await userEvent.click(screen.getByRole("tab", { name: "docker-compose.yml" }));
    expect(screen.getByText(/services:/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "setup.sh" }));
    expect(screen.getByText(/npm install/)).toBeInTheDocument();
  });

  it("copies the active file's content to the clipboard", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        stacks_detected: ["node"],
        services_detected: [],
        dockerfile: "FROM node:20-alpine AS node",
        docker_compose: "services:\n  node:",
        setup_script: "#!/usr/bin/env bash",
      }),
    }) as unknown as typeof fetch;

    render(<BootstrapPanel repoId="r1" />);
    await screen.findByText(/FROM node:20-alpine/);

    await userEvent.click(screen.getByRole("button", { name: /^copy$/i }));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("FROM node:20-alpine AS node");
  });

  it("shows an explanatory empty state when no supported stack is detected", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        stacks_detected: [],
        services_detected: [],
        dockerfile: "",
        docker_compose: "",
        setup_script: "",
      }),
    }) as unknown as typeof fetch;

    render(<BootstrapPanel repoId="r1" />);

    expect(await screen.findByText(/couldn't detect a supported stack/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "This repository hasn't finished analyzing yet." }),
    }) as unknown as typeof fetch;

    render(<BootstrapPanel repoId="r1" />);

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });
});
