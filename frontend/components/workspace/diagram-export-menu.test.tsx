import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DiagramExportMenu } from "./diagram-export-menu";

Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

describe("DiagramExportMenu", () => {
  it("copies the raw Mermaid source when 'Copy Mermaid source' is selected", async () => {
    render(<DiagramExportMenu diagram={"flowchart TD\n  A --> B"} svg="<svg></svg>" filenamePrefix="test-diagram" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Copy Mermaid source" }));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("flowchart TD\n  A --> B");
  });

  it("triggers an SVG download when 'Download SVG' is selected", async () => {
    const createObjectURL = jest.fn().mockReturnValue("blob:mock");
    global.URL.createObjectURL = createObjectURL;
    global.URL.revokeObjectURL = jest.fn();
    const clickSpy = jest.fn();
    const realCreateElement = document.createElement.bind(document);
    jest.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = realCreateElement(tag);
      if (tag === "a") el.click = clickSpy;
      return el;
    });

    render(<DiagramExportMenu diagram="flowchart TD" svg="<svg></svg>" filenamePrefix="test-diagram" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Download SVG" }));

    expect(clickSpy).toHaveBeenCalled();
    (document.createElement as jest.Mock).mockRestore();
  });

  it("lists all three export options", async () => {
    render(<DiagramExportMenu diagram="flowchart TD" svg="<svg></svg>" filenamePrefix="test-diagram" />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    expect(screen.getByRole("menuitem", { name: "Download SVG" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Download PNG" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Copy Mermaid source" })).toBeInTheDocument();
  });
});
