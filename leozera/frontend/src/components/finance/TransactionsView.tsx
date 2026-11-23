"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AdjustmentForm } from "@/components/finance/AdjustmentForm";
import { EntryList } from "@/components/finance/EntryList";
import { TransactionForm } from "@/components/finance/TransactionForm";
import { TransferForm } from "@/components/finance/TransferForm";
import { useCurrentUser } from "@/components/layout/AppShell";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { StatusMessage } from "@/components/ui/StatusMessage";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { redirectIfUnauthorized } from "@/lib/api";
import { currentMonthRange } from "@/lib/dates";
import { getTransaction, listAccounts, listCategories, listTransactions, removeEntry, restoreEntry } from "@/lib/finance";
import type { Account, Category, Entry, EntryKind } from "@/lib/types";

const KINDS: Array<{ value: "" | EntryKind; label: string }> = [
  { value: "", label: "Todos os tipos" },
  { value: "income", label: "Receitas" },
  { value: "expense", label: "Despesas" },
  { value: "transfer", label: "Transferências" },
  { value: "adjustment", label: "Ajustes" },
];

export function TransactionsView() {
  const user = useCurrentUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [editing, setEditing] = useState<Entry | null>(null);
  const [draft, setDraft] = useState<Entry | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Entry | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [filterForm, setFilterForm] = useState(() => readFilters(searchParams));
  const hasLoaded = useRef(false);

  const queryString = searchParams.toString();
  const filters = readFilters(searchParams);
  const novo = searchParams.get("novo");
  const editingId = searchParams.get("editar");

  const load = useCallback(async (initial: boolean) => {
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    const query = transactionQuery(readFilters(new URLSearchParams(queryString)));
    const [accountResult, categoryResult, entryResult] = await Promise.all([
      listAccounts(true),
      listCategories(true),
      listTransactions(query),
    ]);
    const failure = [accountResult, categoryResult, entryResult].find((result) => !result.ok);
    if (failure && !failure.ok) {
      if (!failure.aborted && !redirectIfUnauthorized(failure)) {
        setError(failure.message);
      }
      setLoading(false);
      setRefreshing(false);
      return;
    }
    if (accountResult.ok && categoryResult.ok && entryResult.ok) {
      setAccounts(accountResult.data);
      setCategories(categoryResult.data);
      setEntries(entryResult.data.items);
      setNextCursor(entryResult.data.next_cursor);
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
    setFilterForm(readFilters(new URLSearchParams(queryString)));
  }, [queryString]);

  useEffect(() => {
    if (!editingId) {
      setEditing(null);
      return;
    }
    const controller = new AbortController();
    void getTransaction(editingId, controller.signal).then((result) => {
      if (!result.ok) {
        if (!result.aborted && !redirectIfUnauthorized(result)) {
          setError(result.message);
        }
        return;
      }
      setEditing(result.data);
      setDraft(null);
    });
    return () => controller.abort();
  }, [editingId]);

  useEffect(() => {
    function onFocus() {
      void load(false);
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

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
    router.replace(query ? `/transactions?${query}` : "/transactions");
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCursorStack([]);
    replaceParams({
      from: filterForm.from,
      to: filterForm.to,
      account: filterForm.account,
      category: filterForm.category,
      kind: filterForm.kind,
      q: filterForm.q,
      order: filterForm.order,
      deleted: filterForm.deleted ? "1" : null,
      cursor: null,
      novo: null,
      editar: null,
    });
  }

  async function confirmDelete() {
    if (!pendingDelete) {
      return;
    }
    setDeleting(true);
    const result = await removeEntry(pendingDelete);
    setDeleting(false);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setPendingDelete(null);
    setMessage("Lançamento excluído.");
    await load(false);
  }

  async function restore(entry: Entry) {
    const result = await restoreEntry(entry);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setMessage("Lançamento restaurado.");
    await load(false);
  }

  function closeForm() {
    setDraft(null);
    replaceParams({ novo: null, editar: null });
  }

  const showTransactionForm =
    draft !== null || novo === "receita" || novo === "despesa" || (editing !== null && (editing.kind === "income" || editing.kind === "expense"));
  const showTransferForm = !draft && (novo === "transferencia" || editing?.kind === "transfer");
  const showAdjustmentForm = !draft && editing?.kind === "adjustment";
  const formKind = draft?.kind === "expense" || novo === "despesa" || editing?.kind === "expense" ? "expense" : "income";

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={primaryButtonClass} onClick={() => { setDraft(null); replaceParams({ novo: "receita", editar: null }); }}>
          Nova receita
        </button>
        <button type="button" className={secondaryButtonClass} onClick={() => { setDraft(null); replaceParams({ novo: "despesa", editar: null }); }}>
          Nova despesa
        </button>
        <button type="button" className={secondaryButtonClass} onClick={() => { setDraft(null); replaceParams({ novo: "transferencia", editar: null }); }}>
          Transferir
        </button>
      </div>
      <StatusMessage message={message} />
      <ErrorBanner message={error} onRetry={() => void load(false)} />
      {refreshing ? <p className="text-sm text-stone-500">Atualizando dados...</p> : null}
      {!loading && showTransactionForm ? (
        <TransactionForm
          key={editing?.id ?? draft?.id ?? novo ?? "new"}
          userId={user.id}
          accounts={accounts}
          categories={categories}
          kind={formKind}
          editing={draft ? null : editing}
          draft={draft}
          onCancel={closeForm}
          onSaved={async (text) => {
            setDraft(null);
            setMessage(text);
            replaceParams({ novo: null, editar: null });
            await load(false);
          }}
        />
      ) : null}
      {!loading && showTransferForm ? (
        <TransferForm
          key={editing?.id ?? "transfer"}
          userId={user.id}
          accounts={accounts}
          editing={editing?.kind === "transfer" ? editing : null}
          onCancel={closeForm}
          onSaved={async (text) => {
            setMessage(text);
            replaceParams({ novo: null, editar: null });
            await load(false);
          }}
        />
      ) : null}
      {!loading && showAdjustmentForm && editing ? (
        <AdjustmentForm
          key={editing.id}
          accounts={accounts}
          editing={editing}
          onCancel={closeForm}
          onSaved={async (text) => {
            setMessage(text);
            replaceParams({ novo: null, editar: null });
            await load(false);
          }}
        />
      ) : null}
      <form onSubmit={applyFilters} className="grid gap-3 rounded-2xl border border-stone-200 bg-white p-4 md:grid-cols-3">
        <label className="text-sm font-medium text-stone-700">
          De
          <input type="date" value={filterForm.from} onChange={(event) => setFilterForm({ ...filterForm, from: event.target.value })} className={inputClass} />
        </label>
        <label className="text-sm font-medium text-stone-700">
          Até
          <input type="date" value={filterForm.to} onChange={(event) => setFilterForm({ ...filterForm, to: event.target.value })} className={inputClass} />
        </label>
        <label className="text-sm font-medium text-stone-700">
          Conta
          <select value={filterForm.account} onChange={(event) => setFilterForm({ ...filterForm, account: event.target.value })} className={inputClass}>
            <option value="">Todas</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
                {account.archived_at ? " · arquivada" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-stone-700">
          Categoria
          <select value={filterForm.category} onChange={(event) => setFilterForm({ ...filterForm, category: event.target.value })} className={inputClass}>
            <option value="">Todas</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
                {category.is_internal ? " · interna" : ""}
                {category.archived_at ? " · arquivada" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-stone-700">
          Tipo
          <select value={filterForm.kind} onChange={(event) => setFilterForm({ ...filterForm, kind: event.target.value })} className={inputClass}>
            {KINDS.map((kind) => (
              <option key={kind.label} value={kind.value}>
                {kind.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-stone-700">
          Descrição
          <input value={filterForm.q} onChange={(event) => setFilterForm({ ...filterForm, q: event.target.value })} className={inputClass} />
        </label>
        <label className="text-sm font-medium text-stone-700">
          Ordem
          <select value={filterForm.order} onChange={(event) => setFilterForm({ ...filterForm, order: event.target.value })} className={inputClass}>
            <option value="desc">Mais recentes</option>
            <option value="asc">Mais antigas</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-stone-700 md:mt-7">
          <input
            type="checkbox"
            checked={filterForm.deleted}
            onChange={(event) => setFilterForm({ ...filterForm, deleted: event.target.checked })}
            className="size-4 accent-emerald-800"
          />
          Incluir excluídas
        </label>
        <div className="flex flex-wrap items-end gap-2">
          <button type="submit" className={primaryButtonClass}>
            Filtrar
          </button>
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={() => {
              const month = currentMonthRange();
              setFilterForm({ ...filterForm, from: month.from, to: month.to });
            }}
          >
            Mês atual
          </button>
        </div>
      </form>
      {loading ? <p className="text-stone-600">Carregando movimentações...</p> : null}
      {!loading && entries && entries.length === 0 ? (
        <EmptyState title="Nenhuma movimentação neste recorte">
          <p>Ajuste os filtros ou registre uma receita, despesa ou transferência.</p>
        </EmptyState>
      ) : null}
      {entries && entries.length > 0 ? (
        <EntryList
          entries={entries}
          accounts={accounts}
          onEdit={(entry) => {
            setDraft(null);
            replaceParams({ editar: entry.id, novo: null });
          }}
          onDelete={setPendingDelete}
          onRestore={(entry) => void restore(entry)}
          onDuplicate={(entry) => {
            setDraft(entry);
            replaceParams({ novo: null, editar: null });
          }}
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
        open={pendingDelete !== null}
        title="Excluir lançamento"
        description="A exclusão é lógica. O lançamento sai dos saldos e pode ser restaurado em Incluir excluídas."
        confirmLabel="Excluir"
        pending={deleting}
        onConfirm={() => void confirmDelete()}
        onCancel={() => {
          if (!deleting) {
            setPendingDelete(null);
          }
        }}
      />
    </div>
  );
}

function readFilters(searchParams: { get: (name: string) => string | null }) {
  return {
    from: searchParams.get("from") ?? "",
    to: searchParams.get("to") ?? "",
    account: searchParams.get("account") ?? "",
    category: searchParams.get("category") ?? "",
    kind: searchParams.get("kind") ?? "",
    q: searchParams.get("q") ?? "",
    order: searchParams.get("order") === "asc" ? "asc" : "desc",
    deleted: searchParams.get("deleted") === "1",
    cursor: searchParams.get("cursor") ?? "",
  };
}

function transactionQuery(filters: ReturnType<typeof readFilters>): URLSearchParams {
  const query = new URLSearchParams({ limit: "20", order: filters.order });
  if (filters.from) {
    query.set("occurred_from", filters.from);
  }
  if (filters.to) {
    query.set("occurred_to", filters.to);
  }
  if (filters.account) {
    query.set("account_id", filters.account);
  }
  if (filters.category) {
    query.set("category_id", filters.category);
  }
  if (filters.kind) {
    query.set("kind", filters.kind);
  }
  if (filters.q.trim()) {
    query.set("description", filters.q.trim());
  }
  if (filters.deleted) {
    query.set("include_deleted", "true");
  }
  if (filters.cursor) {
    query.set("cursor", filters.cursor);
  }
  return query;
}
