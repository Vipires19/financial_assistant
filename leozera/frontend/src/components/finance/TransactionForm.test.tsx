import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TransactionForm } from "@/components/finance/TransactionForm";
import type { Account, Category, Entry } from "@/lib/types";

const account: Account = {
  id: "acc-1",
  name: "Dinheiro",
  initial_balance: "0.00",
  opened_on: "2026-11-01",
  is_default: true,
  archived_at: null,
  balance: "10.00",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const category: Category = {
  id: "cat-1",
  name: "Salário",
  group_code: null,
  code: null,
  is_internal: false,
  archived_at: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const archivedCategory: Category = { ...category, id: "cat-old", name: "Antiga", archived_at: "2026-11-02T00:00:00Z" };
const internalCategory: Category = {
  ...category,
  id: "cat-adj",
  name: "Ajuste de saldo",
  code: "balance_adjustment",
  is_internal: true,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TransactionForm", () => {
  it("mostra erro de valor e não chama a API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <TransactionForm
        userId="user-1"
        accounts={[account]}
        categories={[category, archivedCategory, internalCategory]}
        kind="income"
        onCancel={() => undefined}
        onSaved={() => undefined}
      />,
    );

    expect(screen.getByRole("option", { name: "Salário" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Antiga · arquivada" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Ajuste de saldo" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Salvar receita" }));
    expect(screen.getByRole("alert").textContent).toContain("Informe o valor");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("envia o valor como string e impede o segundo clique enquanto salva", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    let resolveFetch: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <TransactionForm
        userId="user-1"
        accounts={[account]}
        categories={[category]}
        kind="expense"
        onCancel={() => undefined}
        onSaved={() => undefined}
      />,
    );

    await user.type(screen.getByLabelText("Valor"), "10,50");
    const button = screen.getByRole("button", { name: "Salvar despesa" });
    const pendingClick = user.click(button);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await user.click(button);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body)) as { amount: unknown; kind: string };
    expect(body.kind).toBe("expense");
    expect(body.amount).toBe("10.50");
    expect(typeof body.amount).toBe("string");
    resolveFetch(Response.json({ id: "entry-1" }));
    await pendingClick;
  });

  it("na edição preserva o tipo e o texto digitado quando a API recusa", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ detail: "Nenhuma alteração informada." }, { status: 422 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const entry: Entry = {
      id: "entry-1",
      kind: "income",
      account_id: account.id,
      counter_account_id: null,
      category_id: category.id,
      category_name: category.name,
      amount: "8.00",
      effect: "8.00",
      occurred_on: "2026-11-16",
      description: "Salário",
      deleted_at: null,
      created_at: "2026-11-16T00:00:00Z",
      updated_at: "2026-11-16T00:00:00Z",
    };
    const user = userEvent.setup();
    render(
      <TransactionForm
        userId="user-1"
        accounts={[account]}
        categories={[category]}
        editing={entry}
        onCancel={() => undefined}
        onSaved={() => undefined}
      />,
    );

    const amount = screen.getByLabelText("Valor");
    await user.clear(amount);
    await user.type(amount, "9,00");
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body)) as Record<string, unknown>;
    expect(body.kind).toBeUndefined();
    expect(body.amount).toBe("9.00");
    expect(screen.getByRole("alert").textContent).toContain("Nenhuma alteração informada.");
    expect((screen.getByLabelText("Valor") as HTMLInputElement).value).toBe("9,00");
  });
});
