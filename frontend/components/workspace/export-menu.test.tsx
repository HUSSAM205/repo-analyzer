import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportMenu } from "./export-menu";

describe("ExportMenu", () => {
  it("opens on click and closes after selecting an option, calling its handler", async () => {
    const onSelect = jest.fn();
    render(<ExportMenu options={[{ label: "Markdown", onSelect }]} />);

    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(screen.getByRole("menuitem", { name: "Markdown" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("menuitem", { name: "Markdown" }));
    expect(onSelect).toHaveBeenCalled();
  });

  it("closes when clicking outside the menu", async () => {
    render(
      <div>
        <ExportMenu options={[{ label: "JSON", onSelect: jest.fn() }]} />
        <button type="button">Outside</button>
      </div>
    );

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(screen.getByRole("menuitem")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    render(<ExportMenu options={[{ label: "SVG", onSelect: jest.fn() }]} />);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    expect(screen.getByRole("menuitem")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  });

  it("renders multiple options and only calls the selected one's handler", async () => {
    const onSelectA = jest.fn();
    const onSelectB = jest.fn();
    render(
      <ExportMenu
        options={[
          { label: "Option A", onSelect: onSelectA },
          { label: "Option B", onSelect: onSelectB },
        ]}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: /export/i }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Option B" }));

    expect(onSelectA).not.toHaveBeenCalled();
    expect(onSelectB).toHaveBeenCalled();
  });
});
