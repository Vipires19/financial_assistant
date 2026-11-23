export const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/transactions", label: "Movimentações" },
  { href: "/payables", label: "Contas a Pagar" },
  { href: "/accounts", label: "Contas" },
  { href: "/categories", label: "Categorias" },
] as const;

export function pageTitle(pathname: string): string {
  const match = NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  return match?.label ?? "Leozera";
}

export function isCurrentPath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
