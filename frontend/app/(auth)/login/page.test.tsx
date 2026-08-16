import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import LoginPage from "./page";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

describe("LoginPage error rendering", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders a plain-string fallback (not a crash) when the backend returns a FastAPI-shaped 422 with an array `detail`", async () => {
    // FastAPI's default RequestValidationError shape: `detail` is an array of
    // error objects, not a string. Triggered by e.g. an email that passes the
    // browser's type="email" check but fails the backend's Pydantic EmailStr.
    const validationErrorBody = {
      detail: [
        {
          loc: ["body", "email"],
          msg: "value is not a valid email address",
          type: "value_error.email",
        },
      ],
    };

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => validationErrorBody,
    }) as unknown as typeof fetch;

    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@b" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });

    const form = screen.getByRole("button", { name: /sign in/i }).closest("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form as HTMLFormElement);

    // Would throw "Objects are not valid as a React child" before the fix,
    // since `detail` is an array being passed straight into setError/{error}.
    await waitFor(() => {
      expect(
        screen.getByText("Login failed. Please check your email and password.")
      ).toBeInTheDocument();
    });

    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
