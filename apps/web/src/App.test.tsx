import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("bootstrap técnico del frontend", () => {
  it("renderiza el estado técnico mínimo de Claridez", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Claridez" })).toBeInTheDocument();
    expect(screen.getByText("Estado técnico: frontend inicializado correctamente.")).toBeVisible();
  });
});
