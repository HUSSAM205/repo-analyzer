import { render } from "@testing-library/react";
import { HeroGlowBackground } from "./hero-glow-background";

describe("HeroGlowBackground", () => {
  it("renders as a decorative, non-interactive layer", () => {
    const { container } = render(<HeroGlowBackground />);
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root).toHaveClass("pointer-events-none");
  });

  it("updates the glow position on mousemove", () => {
    const { container } = render(<HeroGlowBackground />);
    const root = container.firstElementChild as HTMLElement;
    root.getBoundingClientRect = () => ({
      left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => {},
    });

    root.dispatchEvent(new MouseEvent("mousemove", { clientX: 100, clientY: 50, bubbles: true }));

    expect(root.style.getPropertyValue("--glow-x")).toBe("50%");
    expect(root.style.getPropertyValue("--glow-y")).toBe("50%");
  });
});
