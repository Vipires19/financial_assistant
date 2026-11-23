"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PayableDetail } from "@/components/finance/PayableDetail";
import { PayableForm } from "@/components/finance/PayableForm";
import { PaymentForm } from "@/components/finance/PaymentForm";
import { useCurrentUser } from "@/components/layout/AppShell";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { StatusMessage } from "@/components/ui/StatusMessage";
import { formatBrl } from "@/lib/money";
import { formatDateBr } from "@/lib/dates";
import { listAccounts, listCategories } from "@/lib/finance";
import { getPayable, getPayableSummary, listPayables } from "@/lib/payables";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { primaryButtonClass, quietButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import type { Account, Category, Obligation, ObligationDetail, PayableStatus, PayableSummary } from "@/lib/types";

const FILTERS: Array<{ value: "" | PayableStatus; label: string }> = [
  { value: "", label: "Todas" },
  { value: "open", label: "Em aberto" },
  { value: "overdue", label: "Vencidas" },
  { value: "paid", label: "Pagas" },
  { value: "archived", label: "Arquivadas" },
];

const STATUS_LABEL: Record<PayableStatus, string> = {
  open: "Em aberto",
  overdue: "Vencida",
  paid: "Paga",
  archived: "Arquivada",
};

const STATUS_CLASS: Record<PayableStatus, string> = {
  open: "bg-stone-100 text-stone-800",
  overdue: "bg-rose-50 text-rose-900",
  paid: "bg-emerald-50 text-emerald-900",
  archived: "bg-stone-100 text-stone-500",
};

export function PayablesView() {
  const user = useCurrentUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [summary, setSummary] = useState<PayableSummary | null>(null);
  const [items, setItems] = useState<Obligation[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [selected, setSelected] = useState<ObligationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pendingArchive, setPendingArchive] = useState<Obligation | null>(null);
  const [archiving, setArchiving] = useState(false);
  const hasLoaded = useRef(false);
  const requestId = useRef(0);
  const queryString = searchParams.toString();
  const filters = readFilters(searchParams);
  const mode = readMode(searchParams);

  const load = useCallback(async (initial: boolean) => {
    const current = ++requestId.current;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    const query = payableQuery(readFilters(new URLSearchParams(queryString)));
    const [summaryResult, listResult, accountResult, categoryResult] = await Promise.all([
      getPayableSummary(),
      listPayables(query),
      listAccounts(true),
      listCategories(true),
    ]);
    if (current !== requestId.current) {
      return;
    }
    const failure = [summaryResult, listResult, accountResult, categoryResult].find((result) => !result.ok);
    if (failure && !failure.ok) {
      if (!failure.aborted && !redirectIfUnauthorized(failure)) {
        setError(failure.message);
      }
      setLoading(false);
      setRefreshing(false);
      return;
    }
    if (summaryResult.ok && listResult.ok && accountResult.ok && categoryResult.ok) {
      setSummary(summaryResult.data);
      setItems(listResult.data.items);
      setNextCursor(listResult.data.next_cursor);
      setAccounts(accountResult.data);
      setCategories(categoryResult.data);
      setError("");
    }
    setLoading(false);
    setRefreshing(false);
  }, [queryString]);

  useEffect(() => {
    const initial = !hasLoaded.current;
    hasLoaded.current = true;
    void load(initial);
  }, [load]);

  useEffect(() => {
    function onFocus() {
      void load(false);
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  useEffect(() => {
    if (!mode.id) {
      setSelected(null);
      return;
    }
    const controller = new AbortController();
    void getPayable(mode.id, controller.signal).then((result) => {
      if (!result.ok) {
        if (!result.aborted && !redirectIfUnauthorized(result)) {
          setError(result.message);
        }
        return;
      }
      setSelected(result.data);
    });
    return () => controller.abort();
  }, [mode.id]);

  function replaceParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === "") {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    }
    const query = next.toString();
    router.replace(query ? `/payables?${query}` : "/payables");
  }

  async function confirmArchive() {
    if (!pendingArchive) {
      return;
    }
    setArchiving(true);
    const result = await apiSend<ObligationDetail>(`/api/payables/${pendingArchive.id}/archive`, "POST");
    setArchiving(false);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setPendingArchive(null);
    setMessage("Conta arquivada.");
    await load(false);
  }

  async function reactivate(obligation: Obligation) {
    const result = await apiSend<ObligationDetail>(`/api/payables/${obligation.id}/reactivate`, "POST");
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setMessage("Conta reativada.");
    await load(false);
  }

  async function saved(text: string) {
    setMessage(text);
    replaceParams({ nova: null, editar: null, pagar: null });
    await load(false);
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          className={primaryButtonClass}
          onClick={() => replaceParams({ nova: "1", editar: null, pagar: null, detalhe: null })}
        >
          Nova conta
        </button>
      </div>
      <StatusMessage message={message} />
      <ErrorBanner message={error} onRetry={() => void load(false)} />
      {refreshing ? <p className="text-sm text-stone-500">Atualizando dados...</p> : null}
      {summary ? <PayableIndicators summary={summary} /> : null}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filtros">
        {FILTERS.map((filter) => {
          const current = filters.status === filter.value;
          return (
            <button
              key={filter.label}
              type="button"
              aria-pressed={current}
              className={current ? primaryButtonClass : secondaryButtonClass}
              onClick={() => {
                setCursorStack([]);
                replaceParams({ status: filter.value || null, cursor: null });
              }}
            >
              {filter.label}
            </button>
          );
        })}
      </div>
      {!loading && mode.kind === "create" ? (
        <PayableForm
          categories={categories}
          onCancel={() => replaceParams({ nova: null })}
          onSaved={(text) => void saved(text)}
        />
      ) : null}
      {!loading && mode.kind === "edit" && selected ? (
        <PayableForm
          key={selected.id}
          categories={categories}
          editing={selected}
          onCancel={() => replaceParams({ editar: null })}
          onSaved={(text) => void saved(text)}
        />
      ) : null}
      {!loading && mode.kind === "pay" && selected && selected.status !== "paid" && selected.status !== "archived" ? (
        <PaymentForm
          key={selected.id}
          userId={user.id}
          obligation={selected}
          accounts={accounts}
          categories={categories}
          onCancel={() => replaceParams({ pagar: null })}
          onConfirmed={(text) => void saved(text)}
        />
      ) : null}
      {!loading && mode.kind === "detail" && selected ? (
        <PayableDetail obligation={selected} accounts={accounts} onClose={() => replaceParams({ detalhe: null })} />
      ) : null}
      {items && items.length === 0 ? (
        <EmptyState title="Nenhuma conta a pagar">
          <p>Nada encontrado neste filtro.</p>
        </EmptyState>
      ) : null}
      {items && items.length > 0 ? (
        <PayableList
          items={items}
          onPay={(item) => replaceParams({ pagar: item.id, nova: null, editar: null, detalhe: null })}
          onEdit={(item) => replaceParams({ editar: item.id, nova: null, pagar: null, detalhe: null })}
          onDetail={(item) => replaceParams({ detalhe: item.id, nova: null, pagar: null, editar: null })}
          onArchive={setPendingArchive}
          onReactivate={(item) => void reactivate(item)}
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={secondaryButtonClass}
          disabled={cursorStack.length === 0 || refreshing}
          onClick={() => {
            const previous = cursorStack[cursorStack.length - 1] ?? "";
            setCursorStack((stack) => stack.slice(0, -1));
            replaceParams({ cursor: previous || null });
          }}
        >
          Página anterior
        </button>
        <button
          type="button"
          className={secondaryButtonClass}
          disabled={!nextCursor || refreshing}
          onClick={() => {
            if (!nextCursor) {
              return;
            }
            setCursorStack((stack) => [...stack, filters.cursor]);
            replaceParams({ cursor: nextCursor });
          }}
        >
          Próxima página
        </button>
      </div>
      <ConfirmDialog
        open={pendingArchive !== null}
        title="Arquivar conta a pagar"
        description="A obrigação sai da lista ativa. A despesa já registrada permanece no histórico."
        confirmLabel="Arquivar"
        pending={archiving}
        onConfirm={() => void confirmArchive()}
        onCancel={() => {
          if (!archiving) {
            setPendingArchive(null);
          }
        }}
      />
    </div>
  );
}

function PayableIndicators({ summary }: { summary: PayableSummary }) {
  const cards = [
    { label: "Em aberto", value: summary.open_expected },
    { label: "Vencidas", value: summary.overdue_expected },
    { label: "Pagas", value: summary.paid_amount },
  ];
  return (
    <section aria-label="Indicadores" className="grid gap-3 sm:grid-cols-3">
      {cards.map((card) => (
        <article key={card.label} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-medium text-stone-500">{card.label}</h2>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-stone-950">{formatBrl(card.value)}</p>
        </article>
      ))}
    </section>
  );
}

function PayableList({
  items,
  onPay,
  onEdit,
  onDetail,
  onArchive,
  onReactivate,
}: {
  items: Obligation[];
  onPay: (item: Obligation) => void;
  onEdit: (item: Obligation) => void;
  onDetail: (item: Obligation) => void;
  onArchive: (item: Obligation) => void;
  onReactivate: (item: Obligation) => void;
}) {
  return (
    <>
      <div className="hidden overflow-hidden rounded-2xl border border-stone-200 bg-white md:block">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Contas a pagar</caption>
          <thead className="border-b border-stone-200 text-stone-500">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Descrição</th>
              <th scope="col" className="px-4 py-3 font-medium">Valor previsto</th>
              <th scope="col" className="px-4 py-3 font-medium">Vencimento</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="px-4 py-3 font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-stone-100 last:border-0">
                <td className="px-4 py-3">{item.description}</td>
                <td className="px-4 py-3 whitespace-nowrap">{formatBrl(item.expected_amount)}</td>
                <td className="px-4 py-3 whitespace-nowrap">{formatDateBr(item.due_on)}</td>
                <td className="px-4 py-3">
                  <StatusBadge item={item} />
                </td>
                <td className="px-4 py-3">
                  <RowActions item={item} onPay={onPay} onEdit={onEdit} onDetail={onDetail} onArchive={onArchive} onReactivate={onReactivate} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="grid gap-3 md:hidden">
        {items.map((item) => (
          <li key={item.id} className="rounded-2xl border border-stone-200 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <StatusBadge item={item} />
                <p className="mt-2 font-medium text-stone-950">{item.description}</p>
              </div>
              <p className="font-semibold whitespace-nowrap">{formatBrl(item.expected_amount)}</p>
            </div>
            <p className="mt-2 text-sm text-stone-600">{formatDateBr(item.due_on)}</p>
            <div className="mt-3">
              <RowActions item={item} onPay={onPay} onEdit={onEdit} onDetail={onDetail} onArchive={onArchive} onReactivate={onReactivate} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function StatusBadge({ item }: { item: Obligation }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[item.status]}`}>
      {STATUS_LABEL[item.status]}
    </span>
  );
}

function RowActions({
  item,
  onPay,
  onEdit,
  onDetail,
  onArchive,
  onReactivate,
}: {
  item: Obligation;
  onPay: (item: Obligation) => void;
  onEdit: (item: Obligation) => void;
  onDetail: (item: Obligation) => void;
  onArchive: (item: Obligation) => void;
  onReactivate: (item: Obligation) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <button type="button" className={quietButtonClass} onClick={() => onDetail(item)}>
        Detalhe
      </button>
      {item.status === "open" || item.status === "overdue" ? (
        <button type="button" className={quietButtonClass} onClick={() => onPay(item)}>
          Pagar
        </button>
      ) : null}
      {item.status !== "archived" ? (
        <button type="button" className={quietButtonClass} onClick={() => onEdit(item)}>
          Editar
        </button>
      ) : null}
      {item.status === "open" || item.status === "overdue" ? (
        <button type="button" className={quietButtonClass} onClick={() => onArchive(item)}>
          Arquivar
        </button>
      ) : null}
      {item.status === "archived" ? (
        <button type="button" className={quietButtonClass} onClick={() => onReactivate(item)}>
          Reativar
        </button>
      ) : null}
    </div>
  );
}

function readFilters(searchParams: { get: (name: string) => string | null }) {
  const status = searchParams.get("status");
  return {
    status: status === "open" || status === "overdue" || status === "paid" || status === "archived" ? status : "",
    cursor: searchParams.get("cursor") ?? "",
  };
}

function readMode(searchParams: { get: (name: string) => string | null }): { kind: "create" | "edit" | "pay" | "detail" | "none"; id: string | null } {
  if (searchParams.get("nova") === "1") {
    return { kind: "create", id: null };
  }
  const pay = searchParams.get("pagar");
  if (pay) {
    return { kind: "pay", id: pay };
  }
  const edit = searchParams.get("editar");
  if (edit) {
    return { kind: "edit", id: edit };
  }
  const detail = searchParams.get("detalhe");
  if (detail) {
    return { kind: "detail", id: detail };
  }
  return { kind: "none", id: null };
}

function payableQuery(filters: ReturnType<typeof readFilters>): URLSearchParams {
  const query = new URLSearchParams({ limit: "50" });
  if (filters.status) {
    query.set("status", filters.status);
  }
  if (filters.cursor) {
    query.set("cursor", filters.cursor);
  }
  return query;
}
