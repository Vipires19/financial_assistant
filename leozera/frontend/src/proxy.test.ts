import { describe, expect, it } from "vitest";
import { isProtectedPath } from "@/proxy";

describe("proteção de rotas", () => {
  it("exige sessão nas páginas financeiras e deixa o login público", () => {
    expect(isProtectedPath("/dashboard")).toBe(true);
    expect(isProtectedPath("/transactions")).toBe(true);
    expect(isProtectedPath("/payables")).toBe(true);
    expect(isProtectedPath("/payables/detalhe")).toBe(true);
    expect(isProtectedPath("/accounts")).toBe(true);
    expect(isProtectedPath("/categories")).toBe(true);
    expect(isProtectedPath("/login")).toBe(false);
    expect(isProtectedPath("/register")).toBe(false);
  });
});
