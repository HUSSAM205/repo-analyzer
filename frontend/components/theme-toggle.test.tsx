import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeToggle } from "./theme-toggle";

const setTheme = jest.fn();
let resolvedTheme = "dark";

jest.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme, setTheme }),
}));

describe("ThemeToggle", () => {
  beforeEach(() => {
    resolvedTheme = "dark";
    setTheme.mockClear();
  });

  it("shows a button that switches to light mode from dark", async () => {
    render(<ThemeToggle />);
    const button = await screen.findByRole("button", { name: /switch to light mode/i });
    await userEvent.click(button);
    expect(setTheme).toHaveBeenCalledWith("light");
  });

  it("shows a button that switches to dark mode from light", async () => {
    resolvedTheme = "light";
    render(<ThemeToggle />);
    const button = await screen.findByRole("button", { name: /switch to dark mode/i });
    await userEvent.click(button);
    expect(setTheme).toHaveBeenCalledWith("dark");
  });
});
