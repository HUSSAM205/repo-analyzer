import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegexPlayground } from "./regex-playground";

describe("RegexPlayground", () => {
  it("renders with a default pattern and highlights matches immediately", async () => {
    render(<RegexPlayground />);

    expect(await screen.findByText(/2 matches/i)).toBeInTheDocument();
    expect(screen.getByText("support@example.com")).toBeInTheDocument();
    expect(screen.getByText("sales@example.org")).toBeInTheDocument();
  });

  it("updates matches live as the pattern changes", async () => {
    render(<RegexPlayground />);
    const patternInput = screen.getByLabelText("Regular expression pattern");

    await userEvent.clear(patternInput);
    await userEvent.type(patternInput, "example\\.com");

    expect(await screen.findByText("1 match")).toBeInTheDocument();
  });

  it("shows an error message for an invalid pattern instead of crashing", async () => {
    render(<RegexPlayground />);
    const patternInput = screen.getByLabelText("Regular expression pattern");

    await userEvent.clear(patternInput);
    await userEvent.type(patternInput, "(unterminated");

    expect(await screen.findByText(/invalid|unterminated|error/i)).toBeInTheDocument();
  });

  it("toggling the global flag off limits matching to the first occurrence", async () => {
    render(<RegexPlayground />);

    // Default flags are "gi" -- turn off "g".
    await userEvent.click(screen.getByTitle(/global/i));

    expect(await screen.findByText("1 match")).toBeInTheDocument();
  });

  it("updates the test string and re-evaluates matches", async () => {
    render(<RegexPlayground />);
    const testStringInput = screen.getByLabelText("Test string");

    await userEvent.clear(testStringInput);
    await userEvent.type(testStringInput, "no emails here");

    expect(await screen.findByText("0 matches")).toBeInTheDocument();
  });
});
