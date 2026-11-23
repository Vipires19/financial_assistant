import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SideNav } from "@/components/layout/SideNav";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/accounts",
}));

afterEach(() => {
  cleanup();
});

describe("SideNav", () => {
  it("marca a página atual e expõe as áreas financeiras", () => {
    render(<SideNav />);
    expect(screen.getByRole("link", { name: "Contas" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Dashboard" }).getAttribute("href")).toBe("/dashboard");
    expect(screen.getByRole("link", { name: "Movimentações" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "Categorias" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Contas a Pagar" }).getAttribute("href")).toBe("/payables");
    expect(screen.getByRole("link", { name: "Contas a Pagar" }).getAttribute("aria-current")).toBeNull();
  });
});
