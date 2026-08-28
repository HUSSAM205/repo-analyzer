import { render, screen } from "@testing-library/react";
import { BrandNode } from "@/components/brand-node";

describe("BrandNode", () => {
  it("renders the ES Easy Solutions attribution line", () => {
    render(<BrandNode />);
    expect(screen.getByText(/managed & powered by/i)).toBeInTheDocument();
    expect(screen.getByText("ES Easy Solutions")).toBeInTheDocument();
  });

  it("renders a spinning 3D node with two SVG faces", () => {
    const { container } = render(<BrandNode />);
    expect(container.querySelectorAll("svg")).toHaveLength(2);
    expect(container.querySelector(".animate-spin-3d")).toBeInTheDocument();
  });
});
