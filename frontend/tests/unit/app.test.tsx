import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { theme } from "@/theme/theme";

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme}>
        <App />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Response(JSON.stringify({ detail: "not authenticated" }), { status: 401 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the login screen when unauthenticated", async () => {
    renderApp();
    expect(await screen.findByText("NAS-OS")).toBeInTheDocument();
    // Mantine appends a required-field marker to the label text, so match loosely.
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });
});
