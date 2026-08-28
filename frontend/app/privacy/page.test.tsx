import { render, screen } from "@testing-library/react";
import PrivacyPage from "./page";

describe("PrivacyPage", () => {
  it("renders the privacy policy heading and a link back to the workspace", () => {
    render(<PrivacyPage />);

    expect(screen.getByRole("heading", { name: "Privacy Policy" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /back to workspace/i });
    expect(link).toHaveAttribute("href", "/repos");
  });

  it("addresses guest sessions, localStorage, and public GitHub data handling", () => {
    render(<PrivacyPage />);

    expect(screen.getByText(/guest sessions, not accounts/i)).toBeInTheDocument();
    expect(screen.getByText(/local preferences/i)).toBeInTheDocument();
    expect(screen.getByText(/public github repository data/i)).toBeInTheDocument();
  });
});
