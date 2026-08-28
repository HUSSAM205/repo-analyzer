import { render, screen } from "@testing-library/react";
import { AnalysisProgress } from "./analysis-progress";

describe("AnalysisProgress", () => {
  it("renders all four stage labels in order", () => {
    render(<AnalysisProgress stage="cloning" />);

    expect(screen.getByText("Cloning repository...")).toBeInTheDocument();
    expect(screen.getByText("Detecting domain & parsing AST...")).toBeInTheDocument();
    expect(screen.getByText("Generating CodeBERT embeddings...")).toBeInTheDocument();
    expect(screen.getByText("Ready!")).toBeInTheDocument();
  });

  it("marks the current stage as in progress and later stages as upcoming", () => {
    render(<AnalysisProgress stage="cloning" />);

    expect(screen.getByLabelText("Cloning repository... (in progress)")).toBeInTheDocument();
    expect(screen.getByLabelText("Detecting domain & parsing AST... (upcoming)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generating CodeBERT embeddings... (upcoming)")).toBeInTheDocument();
    expect(screen.getByLabelText("Ready! (upcoming)")).toBeInTheDocument();
  });

  it("checks off completed stages and marks the current one as parsing progresses", () => {
    render(<AnalysisProgress stage="parsing" />);

    expect(screen.getByLabelText("Cloning repository... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Detecting domain & parsing AST... (in progress)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generating CodeBERT embeddings... (upcoming)")).toBeInTheDocument();
  });

  it("checks off cloning and parsing once embedding is the current stage", () => {
    render(<AnalysisProgress stage="embedding" />);

    expect(screen.getByLabelText("Cloning repository... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Detecting domain & parsing AST... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generating CodeBERT embeddings... (in progress)")).toBeInTheDocument();
    expect(screen.getByLabelText("Ready! (upcoming)")).toBeInTheDocument();
  });

  it("marks every prior stage done once the completed stage is reached", () => {
    render(<AnalysisProgress stage="completed" />);

    expect(screen.getByLabelText("Cloning repository... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Detecting domain & parsing AST... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generating CodeBERT embeddings... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Ready! (in progress)")).toBeInTheDocument();
  });

  it("transitions from one stage to the next on rerender", () => {
    const { rerender } = render(<AnalysisProgress stage="cloning" />);
    expect(screen.getByLabelText("Cloning repository... (in progress)")).toBeInTheDocument();

    rerender(<AnalysisProgress stage="embedding" />);

    expect(screen.getByLabelText("Cloning repository... (done)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generating CodeBERT embeddings... (in progress)")).toBeInTheDocument();
  });

  it("defaults to the first stage when stage is null/undefined (older backend response)", () => {
    render(<AnalysisProgress stage={null} />);
    expect(screen.getByLabelText("Cloning repository... (in progress)")).toBeInTheDocument();
  });
});
