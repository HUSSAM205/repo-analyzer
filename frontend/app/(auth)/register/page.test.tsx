import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import RegisterPage from "./page";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

describe("RegisterPage error rendering", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders a plain-string fallback (not a crash) when the backend returns a FastAPI-shaped 422 with an array `detail`", async () => {
    // Same shape FastAPI sends for any unhandled Pydantic validation failure,
    // e.g. a password exceeding the backend's max_length=128 (not mirrored by
    // a client-side maxLength on this form).
    const validationErrorBody = {
      detail: [
        {
          loc: ["body", "password"],
          msg: "ensure this value has at most 128 characters",
          type: "value_error.any_str.max_length",
        },
      ],
    };

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => validationErrorBody,
    }) as unknown as typeof fetch;

    render(<RegisterPage />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a".repeat(200) } });

    const form = screen.getByRole("button", { name: /create account/i }).closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    // Would throw "Objects are not valid as a React child" before the fix,
    // since `detail` is an array being passed straight into setError/{error}.
    await waitFor(() => {
      expect(
        screen.getByText("Registration failed. Please check your email and password.")
      ).toBeInTheDocument();
    });

    // Only the register call should have been made — a 4xx from /api/auth/register
    // must not fall through to attempting /api/auth/login.
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
