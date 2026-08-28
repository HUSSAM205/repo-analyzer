import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FaqSection } from "@/components/faq-section";

describe("FaqSection", () => {
  it("shows the first question expanded and toggles others on click", async () => {
    const user = userEvent.setup();
    render(<FaqSection />);

    const firstTrigger = screen.getByRole("button", {
      name: /how does repolens ai index large repositories/i,
    });
    expect(firstTrigger).toHaveAttribute("aria-expanded", "true");

    const secondTrigger = screen.getByRole("button", { name: /is my code secure/i });
    expect(secondTrigger).toHaveAttribute("aria-expanded", "false");

    await user.click(secondTrigger);
    expect(secondTrigger).toHaveAttribute("aria-expanded", "true");

    await user.click(secondTrigger);
    expect(secondTrigger).toHaveAttribute("aria-expanded", "false");
  });

  it("renders all four FAQ questions", () => {
    render(<FaqSection />);
    expect(screen.getByText(/how does repolens ai index large repositories/i)).toBeInTheDocument();
    expect(screen.getByText(/is my code secure/i)).toBeInTheDocument();
    expect(screen.getByText(/which programming languages and frameworks are supported/i)).toBeInTheDocument();
    expect(screen.getByText(/is there a limit on repo size/i)).toBeInTheDocument();
  });
});
