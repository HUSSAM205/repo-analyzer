import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KnowledgeQuiz } from "./knowledge-quiz";

const QUESTIONS = [
  {
    question: "What does the entry point do?",
    options: ["Starts the server", "Runs tests", "Builds docs", "Deploys to prod"],
    correct_index: 0,
    explanation: "main.py boots the app.",
  },
  {
    question: "Where is auth handled?",
    options: ["auth.py", "db.py", "utils.py", "config.py"],
    correct_index: 0,
    explanation: "auth.py owns the login flow.",
  },
  {
    question: "How are routes registered?",
    options: ["Via a router", "Via a global dict", "Via env vars", "Via a CLI flag"],
    correct_index: 0,
    explanation: "Routes are registered through the router.",
  },
];

function mockFetchOnce(body: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    json: async () => body,
  }) as unknown as typeof fetch;
}

describe("KnowledgeQuiz", () => {
  it("fetches and renders 3 questions after starting", async () => {
    mockFetchOnce({ questions: QUESTIONS });
    render(<KnowledgeQuiz repoId="r1" />);

    await userEvent.click(screen.getByRole("button", { name: /start quiz/i }));

    expect(await screen.findByText(/what does the entry point do\?/i)).toBeInTheDocument();
    expect(screen.getByText(/where is auth handled\?/i)).toBeInTheDocument();
    expect(screen.getByText(/how are routes registered\?/i)).toBeInTheDocument();
  });

  it("gives instant feedback and locks in the answer after a selection", async () => {
    mockFetchOnce({ questions: QUESTIONS });
    render(<KnowledgeQuiz repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /start quiz/i }));
    await screen.findByText(/what does the entry point do\?/i);

    await userEvent.click(screen.getByRole("button", { name: "Starts the server" }));

    expect(await screen.findByText(/main\.py boots the app\./i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Starts the server" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Runs tests" })).toBeDisabled();
  });

  it("shows a final score once all questions are answered, and lets you retake", async () => {
    mockFetchOnce({ questions: QUESTIONS });
    render(<KnowledgeQuiz repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /start quiz/i }));
    await screen.findByText(/what does the entry point do\?/i);

    await userEvent.click(screen.getByRole("button", { name: "Starts the server" }));
    await userEvent.click(screen.getByRole("button", { name: "auth.py" }));
    await userEvent.click(screen.getByRole("button", { name: "Via a router" }));

    expect(await screen.findByText(/you scored 3 \/ 3/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retake/i }));
    expect(screen.queryByText(/you scored/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Starts the server" })).toBeEnabled();
  });

  it("shows the backend's error message on failure", async () => {
    mockFetchOnce({ detail: "Could not generate the quiz." }, false);
    render(<KnowledgeQuiz repoId="r1" />);

    await userEvent.click(screen.getByRole("button", { name: /start quiz/i }));

    expect(await screen.findByText("Could not generate the quiz.")).toBeInTheDocument();
  });
});
