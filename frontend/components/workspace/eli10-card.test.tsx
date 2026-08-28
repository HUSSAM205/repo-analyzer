import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Eli10Card } from "./eli10-card";
import type { DomainBriefing } from "@/lib/types";

const BRIEFING: DomainBriefing = {
  primary_field: "Web SaaS",
  target_audience: "Backend engineers",
  architecture_overview: "A FastAPI backend talks to Postgres.",
  tech_stack_badges: [],
  file_type_distribution: [],
  beginner_summary: "Think of this like a restaurant: the frontend is the dining room.",
};

describe("Eli10Card", () => {
  it("renders nothing when there is no beginner_summary", () => {
    const { container } = render(<Eli10Card briefing={{ ...BRIEFING, beginner_summary: undefined }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when briefing is null", () => {
    const { container } = render(<Eli10Card briefing={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("starts collapsed and expands to show the analogy on click", async () => {
    render(<Eli10Card briefing={BRIEFING} />);

    expect(screen.queryByText(/dining room/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /explain like i'm 10/i }));

    await waitFor(() => expect(screen.getByText(/dining room/i)).toBeInTheDocument());
  });
});
