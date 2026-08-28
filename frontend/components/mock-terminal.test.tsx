import { render, screen } from "@testing-library/react";
import { MockTerminal } from "./mock-terminal";

describe("MockTerminal", () => {
  it("renders fully revealed (no animation) when prefers-reduced-motion is set", () => {
    window.matchMedia = jest.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      // framer-motion's own prefers-reduced-motion detection (triggered by
      // any <motion.*> element, not just this component's own matchMedia
      // check) uses the legacy addListener/removeListener API, not
      // addEventListener -- omitting these throws inside framer-motion's
      // mount effect, not this component's code.
      addListener: jest.fn(),
      removeListener: jest.fn(),
    })) as unknown as typeof window.matchMedia;

    render(<MockTerminal />);

    expect(screen.getByText("repolens -- analysis")).toBeInTheDocument();
    expect(screen.getByText("$ repolens analyze ./your-repo")).toBeInTheDocument();
    expect(screen.getByText(/1,138 files parsed/)).toBeInTheDocument();
  });
});
