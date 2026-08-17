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
});
