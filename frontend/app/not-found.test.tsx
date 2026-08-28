import { render, screen } from "@testing-library/react";
import NotFound from "./not-found";

describe("NotFound", () => {
  it("shows the specified 404 header with a gradient CTA link back to /repos", () => {
    render(<NotFound />);

    expect(screen.getByText("404 - Repository or Page Not Found")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /back to workspace/i });
    expect(link).toHaveAttribute("href", "/repos");
  });
});
