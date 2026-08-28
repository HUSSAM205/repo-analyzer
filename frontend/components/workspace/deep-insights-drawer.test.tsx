import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeepInsightsDrawer } from "./deep-insights-drawer";
import type { DomainBriefing } from "@/lib/types";

const baseBriefing: DomainBriefing = {
  primary_field: "Full-Stack Web SaaS",
  target_audience: "Backend engineers",
  architecture_overview: "Overview.",
  tech_stack_badges: ["FastAPI"],
  file_type_distribution: [],
};

const beginnerBriefing: DomainBriefing = {
  ...baseBriefing,
  beginner_summary: "Think of it like a restaurant: the frontend takes orders, the backend cooks.",
  tech_stack_explained: [
    { name: "React", role: "Builds what you see and click on." },
    { name: "FastAPI", role: "The brain/server that handles requests." },
  ],
  learning_path: [
    { file_or_topic: "README.md", why: "Gives you the big picture first." },
    { file_or_topic: "app/main.py", why: "This is where the server starts." },
  ],
  key_takeaways: ["Routes are grouped by feature.", "Config comes from environment variables."],
};

describe("DeepInsightsDrawer", () => {
  it("renders nothing when the briefing has no beginner-guide content", () => {
    const { container } = render(<DeepInsightsDrawer briefing={baseBriefing} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when briefing is null/undefined", () => {
    const { container } = render(<DeepInsightsDrawer briefing={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is collapsed by default and opens the full onboarding guide on click", async () => {
    render(<DeepInsightsDrawer briefing={beginnerBriefing} />);

    expect(screen.queryByText(/restaurant: the frontend takes orders/)).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: /deep insights/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/what is this project/i)).toBeInTheDocument();
    expect(screen.getByText(/restaurant: the frontend takes orders/)).toBeInTheDocument();
    expect(screen.getByText(/tech stack explained/i)).toBeInTheDocument();
    expect(screen.getByText("React")).toBeInTheDocument();
    expect(screen.getByText(/Builds what you see and click on/)).toBeInTheDocument();
    expect(screen.getByText(/where should i start/i)).toBeInTheDocument();
    expect(screen.getByText("README.md")).toBeInTheDocument();
    expect(screen.getByText(/key takeaways/i)).toBeInTheDocument();
    expect(screen.getByText("Routes are grouped by feature.")).toBeInTheDocument();
  });

  it("closes when clicking the trigger again", async () => {
    render(<DeepInsightsDrawer briefing={beginnerBriefing} />);
    const trigger = screen.getByRole("button", { name: /deep insights/i });

    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(trigger);
    // aria-expanded flips immediately; the panel itself may still be
    // mid-exit-animation (framer-motion's AnimatePresence) for a moment.
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(screen.queryByText(/what is this project/i)).not.toBeInTheDocument());
  });
});
