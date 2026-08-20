import { render, screen } from "@testing-library/react";
import NotFound from "./not-found";

describe("NotFound", () => {
  it("shows a themed not-found message with a link back to /repos", () => {
    render(<NotFound />);

    expect(screen.getByText("Page not found")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /back to your repositories/i });
    expect(link).toHaveAttribute("href", "/repos");
  });
});
