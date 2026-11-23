import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PayableDetail } from "@/components/finance/PayableDetail";
import { PayableForm } from "@/components/finance/PayableForm";
import { PayablesView } from "@/components/finance/PayablesView";
import { PaymentForm } from "@/components/finance/PaymentForm";
import { CurrentUserProvider } from "@/components/layout/AppShell";
import { paymentResultIsUnknown, writePaymentAttempt } from "@/lib/payables";
import type { Account, Category, Obligation, ObligationDetail } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/payables",
}));

const account: Account = {
  id: "acc-1",
  name: "Dinheiro",
  initial_balance: "0.00",
  opened_on: "2026-11-01",
  is_default: true,
  archived_at: null,
  balance: "0.00",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const category: Category = {
  id: "cat-1",
  name: "Internet",
  group_code: null,
  code: null,
  is_internal: false,
  archived_at: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const obligation: Obligation = {
  id: "ob-1",
  description: "Internet",
  expected_amount: "80.00",
  due_on: "2026-11-19",
  category_id: "cat-1",
  category_name: "Internet",
  status: "open",
  archived_at: null,
  active_settlement_id: null,
  paid_amount: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

function requestAt(mock: object, index: number): RequestInit {
  const calls = (mock as { mock: { calls: Array<[unknown, RequestInit]> } }).mock.calls;
  return calls[index][1];
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  replace.mockClear();
});

describe("indicadores e atualização", () => {
  it("mostra os totais do resumo, sem somar a página, e recarrega ao receber foco", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url.includes("/api/payables/summary")) {
          return Response.json({ open_expected: "450.00", overdue_expected: "120.00", paid_amount: "780.00" });
        }
        if (url.includes("/api/accounts")) {
          return Response.json([account]);
        }
        if (url.includes("/api/categories")) {
          return Response.json([category]);
        }
        if (url.includes("/api/payables")) {
          return Response.json({
            items: [{ ...obligation, expected_amount: "10.00" }],
            next_cursor: null,
          });
        }
        return Response.json({ detail: "não encontrado" }, { status: 404 });
      }),
    );
    render(
      <CurrentUserProvider user={{ id: "user-1", name: "Vinícius", email: "vini@example.com" }}>
        <PayablesView />
      </CurrentUserProvider>,
    );

    expect(await screen.findByText("R$ 450,00")).toBeTruthy();
    expect(screen.getByText("R$ 120,00")).toBeTruthy();
    expect(screen.getByText("R$ 780,00")).toBeTruthy();
    expect(screen.getAllByText("R$ 10,00").length).toBeGreaterThan(0);
    const summaryCalls = () => calls.filter((call) => call.includes("/api/payables/summary")).length;
    expect(summaryCalls()).toBe(1);
    window.dispatchEvent(new Event("focus"));
    await vi.waitFor(() => expect(summaryCalls()).toBe(2));
  });

  it("cadastra a obrigação sem conta financeira", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    const fetchMock = vi.fn(async () => Response.json({ ...obligation }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<PayableForm categories={[category]} onCancel={() => undefined} onSaved={() => undefined} />);
    await user.type(screen.getByLabelText("Descrição"), "Aluguel");
    await user.type(screen.getByLabelText("Valor previsto"), "200,00");
    await user.click(screen.getByRole("button", { name: "Cadastrar" }));
    const body = JSON.parse(String(requestAt(fetchMock, 0).body)) as Record<string, unknown>;
    expect(body.account_id).toBeUndefined();
    expect(body.expected_amount).toBe("200.00");
    expect(body.description).toBe("Aluguel");
  });
});

describe("pagamento e idempotência", () => {
  it("repete a mesma chave e o mesmo corpo quando a rede falha", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(
        Response.json({
          obligation: { ...obligation, status: "paid", paid_amount: "80.00", settlements: [] },
          entry_id: "entry-1",
          settlement_id: "set-1",
          amount: "80.00",
          replayed: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <PaymentForm
        userId="user-1"
        obligation={obligation}
        accounts={[account]}
        categories={[category]}
        onCancel={() => undefined}
        onConfirmed={() => undefined}
      />,
    );

    const button = await screen.findByRole("button", { name: "Confirmar pagamento" });
    await user.click(button);
    await screen.findByRole("button", { name: "Confirmar novamente" });
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível confirmar o pagamento");
    await user.click(screen.getByRole("button", { name: "Confirmar novamente" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const first = requestAt(fetchMock, 0);
    const second = requestAt(fetchMock, 1);
    const firstHeaders = new Headers(first.headers);
    const secondHeaders = new Headers(second.headers);
    expect(firstHeaders.get("Idempotency-Key")).toBe(secondHeaders.get("Idempotency-Key"));
    expect(first.body).toBe(second.body);
    await vi.waitFor(() => expect(window.sessionStorage.length).toBe(0));
  });

  it("recupera a tentativa gravada depois de atualizar a página", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    writePaymentAttempt("user-1", obligation.id, {
      key: "chave-preservada",
      body: {
        account_id: account.id,
        amount: "70.00",
        occurred_on: "2026-11-18",
        description: "Internet",
        category_id: category.id,
      },
    });
    const fetchMock = vi.fn(async () =>
      Response.json({
        obligation: { ...obligation, status: "paid", settlements: [] },
        entry_id: "entry-1",
        settlement_id: "set-1",
        amount: "70.00",
        replayed: true,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <PaymentForm
        userId="user-1"
        obligation={obligation}
        accounts={[account]}
        categories={[category]}
        onCancel={() => undefined}
        onConfirmed={() => undefined}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Confirmar novamente" }));
    expect((screen.getByLabelText("Valor") as HTMLInputElement).disabled).toBe(true);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const init = requestAt(fetchMock, 0);
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("chave-preservada");
    expect(JSON.parse(String(init.body))).toMatchObject({ amount: "70.00", account_id: "acc-1" });
    expect((screen.getByLabelText("Valor") as HTMLInputElement).disabled).toBe(true);
  });

  it("classifica timeout e falha de rede como resultado desconhecido", () => {
    expect(paymentResultIsUnknown(0, true, true)).toBe(true);
    expect(paymentResultIsUnknown(0, false, false)).toBe(true);
    expect(paymentResultIsUnknown(500, false, false)).toBe(true);
    expect(paymentResultIsUnknown(409, false, false)).toBe(false);
    expect(paymentResultIsUnknown(201, false, false)).toBe(false);
  });
});

describe("edição de obrigação paga e histórico", () => {
  it("envia somente a descrição quando a obrigação está paga", async () => {
    document.cookie = "leozera_csrf=token-csrf";
    const fetchMock = vi.fn(async () => Response.json({ ...obligation, status: "paid", description: "Fibra" }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <PayableForm
        categories={[category]}
        editing={{ ...obligation, status: "paid", paid_amount: "80.00", active_settlement_id: "set-1" }}
        onCancel={() => undefined}
        onSaved={() => undefined}
      />,
    );

    expect(screen.queryByLabelText("Valor previsto")).toBeNull();
    const description = screen.getByLabelText("Descrição");
    await user.clear(description);
    await user.type(description, "Fibra");
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));
    const body = JSON.parse(String(requestAt(fetchMock, 0).body)) as Record<string, unknown>;
    expect(body).toEqual({ description: "Fibra" });
  });

  it("mostra quitação liberada fora do pagamento vigente", () => {
    const detail: ObligationDetail = {
      ...obligation,
      status: "paid",
      paid_amount: "55.00",
      active_settlement_id: "set-new",
      settlements: [
        {
          id: "set-old",
          obligation_id: obligation.id,
          entry_id: "entry-old",
          allocated_amount: "80.00",
          released_at: "2026-11-18T12:00:00Z",
          entry_deleted_at: "2026-11-18T12:00:00Z",
          entry_occurred_on: "2026-11-10",
          entry_account_id: account.id,
          created_at: "2026-11-10T00:00:00Z",
        },
        {
          id: "set-new",
          obligation_id: obligation.id,
          entry_id: "entry-new",
          allocated_amount: "55.00",
          released_at: null,
          entry_deleted_at: null,
          entry_occurred_on: "2026-11-19",
          entry_account_id: account.id,
          created_at: "2026-11-19T00:00:00Z",
        },
      ],
    };
    render(<PayableDetail obligation={detail} accounts={[account]} onClose={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Pagamento vigente" })).toBeTruthy();
    expect(screen.getAllByText("R$ 55,00").length).toBeGreaterThan(0);
    expect(screen.getByText(/R\$ 80,00 · liberada/)).toBeTruthy();
  });
});
