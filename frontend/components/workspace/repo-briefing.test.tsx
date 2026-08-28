import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepoBriefing } from "./repo-briefing";
import type { DomainBriefing } from "@/lib/types";

const briefing: DomainBriefing = {
  primary_field: "Full-Stack Web SaaS",
  target_audience: "Backend engineers building async pipelines",
  architecture_overview: "A FastAPI backend paired with a Next.js frontend, orchestrated with Docker Compose.",
  tech_stack_badges: ["FastAPI", "PostgreSQL", "Docker", "React"],
  file_type_distribution: [
    { label: "Python backend files", count: 14 },
    { label: "TypeScript/React files", count: 6 },
  ],
};

describe("RepoBriefing", () => {
  it("renders the primary field, audience, badges, distribution, and overview", () => {
    render(<RepoBriefing briefing={briefing} />);

    expect(screen.getByText("Full-Stack Web SaaS")).toBeInTheDocument();
    expect(screen.getByText("Backend engineers building async pipelines")).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("Docker")).toBeInTheDocument();
    expect(screen.getByText("React")).toBeInTheDocument();
    expect(screen.getByText(/14 Python backend files/)).toBeInTheDocument();
    expect(screen.getByText(/6 TypeScript\/React files/)).toBeInTheDocument();
    expect(screen.getByText(/FastAPI backend paired with a Next\.js frontend/)).toBeInTheDocument();
  });

  it("is expanded by default and can be collapsed", async () => {
    render(<RepoBriefing briefing={briefing} />);

    const toggle = screen.getByRole("button", { name: /toggle repo briefing/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/FastAPI backend paired with a Next\.js frontend/)).toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a subtle placeholder instead of an empty card when briefing is null", () => {
    render(<RepoBriefing briefing={null} />);
    expect(screen.getByText(/briefing not available yet/i)).toBeInTheDocument();
  });

  it("shows a subtle placeholder when briefing is undefined (older backend response)", () => {
    render(<RepoBriefing briefing={undefined} />);
    expect(screen.getByText(/briefing not available yet/i)).toBeInTheDocument();
  });

  it("does not render the beginner onboarding guide -- that's DeepInsightsDrawer's job now", () => {
    render(<RepoBriefing briefing={briefing} />);
    expect(screen.queryByText(/what is this project/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/tech stack explained/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/where should i start/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/key takeaways/i)).not.toBeInTheDocument();
  });
});
