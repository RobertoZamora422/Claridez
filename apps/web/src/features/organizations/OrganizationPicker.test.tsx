import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OrganizationPicker } from "./OrganizationPicker";

afterEach(cleanup);

describe("selección de organización", () => {
  it("activa la organización elegida", async () => {
    const organization = { id: "org-2", name: "Casa Jardín", slug: "casa-jardin" };
    const onSelect = vi.fn(() => Promise.resolve());

    render(<OrganizationPicker organizations={[organization]} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Casa Jardín/ }));

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith(organization);
    });
  });
});
