import { render, screen } from "@testing-library/react";
import TermsPage from "./page";

describe("TermsPage", () => {
  it("renders the terms of service heading and a link back to the workspace", () => {
    render(<TermsPage />);

    expect(screen.getByRole("heading", { name: "Terms of Service" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /back to workspace/i });
    expect(link).toHaveAttribute("href", "/repos");
  });

  it("addresses acceptable use for automated analysis and AI chat", () => {
    render(<TermsPage />);

    expect(screen.getByText(/acceptable use/i)).toBeInTheDocument();
    expect(screen.getByText(/automated analysis and ai output/i)).toBeInTheDocument();
  });
});
