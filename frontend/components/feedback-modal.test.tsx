import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FeedbackModal } from "./feedback-modal";

describe("FeedbackModal", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("submits a bug report with the typed message", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<FeedbackModal onClose={jest.fn()} />);

    await userEvent.type(screen.getByLabelText(/what went wrong/i), "the compare modal flickers");
    await userEvent.click(screen.getByRole("button", { name: /send feedback/i }));

    expect(await screen.findByText(/thanks for the feedback/i)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/feedback");
    const body = JSON.parse(init.body);
    expect(body).toEqual({ type: "bug", message: "the compare modal flickers", rating: null, contact_email: null });
  });

  it("disables submit for a bug report until a message is typed", () => {
    render(<FeedbackModal onClose={jest.fn()} />);
    expect(screen.getByRole("button", { name: /send feedback/i })).toBeDisabled();
  });

  it("switches to the rating type and requires stars, not a message", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<FeedbackModal onClose={jest.fn()} />);

    await userEvent.click(screen.getByRole("tab", { name: "Rating" }));
    expect(screen.getByRole("button", { name: /send feedback/i })).toBeDisabled();

    await userEvent.click(screen.getByRole("radio", { name: "4 stars" }));
    expect(screen.getByRole("button", { name: /send feedback/i })).not.toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /send feedback/i }));

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({ type: "rating", message: "", rating: 4, contact_email: null });
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Not authenticated" }),
    }) as unknown as typeof fetch;

    render(<FeedbackModal onClose={jest.fn()} />);
    await userEvent.type(screen.getByLabelText(/what went wrong/i), "x");
    await userEvent.click(screen.getByRole("button", { name: /send feedback/i }));

    expect(await screen.findByText("Not authenticated")).toBeInTheDocument();
  });

  it("calls onClose when the backdrop is clicked", async () => {
    const onClose = jest.fn();
    render(<FeedbackModal onClose={onClose} />);

    await userEvent.click(screen.getByRole("dialog", { name: /feedback/i }).parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});
