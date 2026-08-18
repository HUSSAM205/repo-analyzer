import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileTreeNode } from "./file-tree-node";
import type { FileTreeEntry } from "@/lib/types";

const fileEntry: FileTreeEntry = { name: "main.py", path: "main.py", type: "file", children: null };
const dirEntry: FileTreeEntry = {
  name: "src",
  path: "src",
  type: "directory",
  children: [{ name: "utils.py", path: "src/utils.py", type: "file", children: null }],
};

describe("FileTreeNode", () => {
  it("calls onSelectFile with the file's path when clicked", async () => {
    const onSelectFile = jest.fn();
    render(<FileTreeNode entry={fileEntry} depth={0} selectedPath={null} onSelectFile={onSelectFile} />);
    await userEvent.click(screen.getByText("main.py"));
    expect(onSelectFile).toHaveBeenCalledWith("main.py");
  });

  it("expands a directory to reveal its children on click", async () => {
    const onSelectFile = jest.fn();
    render(<FileTreeNode entry={dirEntry} depth={1} selectedPath={null} onSelectFile={onSelectFile} />);
    expect(screen.queryByText("utils.py")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("src"));
    expect(await screen.findByText("utils.py")).toBeInTheDocument();
  });

  it("highlights the selected file", () => {
    render(<FileTreeNode entry={fileEntry} depth={0} selectedPath="main.py" onSelectFile={jest.fn()} />);
    expect(screen.getByText("main.py").closest("button")).toHaveClass("bg-accent");
  });

  it("shows a JSON-specific icon for a .json file", () => {
    const entry = { name: "package.json", path: "package.json", type: "file" as const, children: null };
    render(<FileTreeNode entry={entry} depth={0} selectedPath={null} onSelectFile={jest.fn()} />);
    expect(screen.getByTestId("file-icon-json")).toBeInTheDocument();
  });

  it("falls back to a generic file icon for an unrecognized extension", () => {
    const entry = { name: "data.xyz", path: "data.xyz", type: "file" as const, children: null };
    render(<FileTreeNode entry={entry} depth={0} selectedPath={null} onSelectFile={jest.fn()} />);
    expect(screen.getByTestId("file-icon-default")).toBeInTheDocument();
  });

  it("adds an accent border to the active file", () => {
    const entry = { name: "main.py", path: "src/main.py", type: "file" as const, children: null };
    render(<FileTreeNode entry={entry} depth={0} selectedPath="src/main.py" onSelectFile={jest.fn()} />);
    expect(screen.getByRole("button")).toHaveClass("border-l-2");
  });
});
