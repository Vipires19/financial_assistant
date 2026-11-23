import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardView } from "@/components/finance/DashboardView";
import { CurrentUserProvider } from "@/components/layout/AppShell";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/dashboard",
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DashboardView", () => {
  it("mostra o estado vazio sem inventar movimentações", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/summary")) {
          return Response.json({
            as_of: "2026-11-16",
            period_from: "2026-11-01",
            period_to: "2026-11-16",
            total_balance: "0.00",
            period_income: "0.00",
            period_expense: "0.00",
            period_result: "0.00",
          });
        }
        if (url.includes("/api/accounts")) {
          return Response.json([
            {
              id: "acc-1",
              name: "Dinheiro",
              initial_balance: "0.00",
              opened_on: "2026-11-16",
              is_default: true,
              archived_at: null,
              balance: "0.00",
              created_at: "2026-11-16T00:00:00Z",
              updated_at: "2026-11-16T00:00:00Z",
            },
          ]);
        }
        if (url.includes("/api/categories")) {
          return Response.json([]);
        }
        return Response.json({ items: [], next_cursor: null });
      }),
    );

    render(
      <CurrentUserProvider user={{ id: "user-1", name: "Vinícius", email: "vini@example.com" }}>
        <DashboardView />
      </CurrentUserProvider>,
    );

    expect(await screen.findByText("Comece pelo primeiro lançamento")).toBeTruthy();
    expect(screen.getByText("Nenhuma movimentação registrada.")).toBeTruthy();
    expect(screen.getAllByText("R$ 0,00").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Nova receita" }).getAttribute("href")).toBe("/transactions?novo=receita");
  });
});
