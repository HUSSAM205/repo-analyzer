import { render, screen } from "@testing-library/react";
import { SiteFooter } from "@/components/site-footer";

describe("SiteFooter", () => {
  it("renders the ES Easy Solutions attribution signature", () => {
    render(<SiteFooter />);
    expect(screen.getByText(/managed and powered by es easy solutions/i)).toBeInTheDocument();
  });

  it("links to the privacy and terms pages", () => {
    render(<SiteFooter />);

    expect(screen.getByRole("link", { name: /privacy policy/i })).toHaveAttribute("href", "/privacy");
    expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute("href", "/terms");
  });
});
