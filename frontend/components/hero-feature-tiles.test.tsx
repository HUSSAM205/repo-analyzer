import { render, screen } from "@testing-library/react";
import { HeroFeatureTiles } from "./hero-feature-tiles";

describe("HeroFeatureTiles", () => {
  it("renders all three feature tiles with their labels and detail copy", () => {
    render(<HeroFeatureTiles />);

    expect(screen.getByText("AST Deep Mapping")).toBeInTheDocument();
    expect(screen.getByText(/tree-sitter parsing/i)).toBeInTheDocument();

    expect(screen.getByText("Token-Compressed Chat")).toBeInTheDocument();
    expect(screen.getByText(/rolling conversation summary/i)).toBeInTheDocument();

    expect(screen.getByText("Security & Architectural Radar")).toBeInTheDocument();
    expect(screen.getByText(/secret detection/i)).toBeInTheDocument();
  });
});
