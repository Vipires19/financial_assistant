"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { EntryList } from "@/components/finance/EntryList";
import { SummaryCards } from "@/components/finance/SummaryCards";
import { useCurrentUser } from "@/components/layout/AppShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { redirectIfUnauthorized } from "@/lib/api";
import { currentMonthRange, formatMonthLabel } from "@/lib/dates";
import { getSummary, listAccounts, listCategories, listTransactions, selectableCategories } from "@/lib/finance";
import { formatBrl, isNegativeMoney } from "@/lib/money";
import type { Account, Category, EntryPage, Summary } from "@/lib/types";

export function DashboardView() {
  const user = useCurrentUser();
  const router = useRouter();
  const requestId = useRef(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [recent, setRecent] = useState<EntryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (initial: boolean) => {
    const request = ++requestId.current;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    const { from, to } = currentMonthRange();
    const query = new URLSearchParams({ limit: "5", order: "desc" });
    const [summaryResult, accountResult, categoryResult, recentResult] = await Promise.all([
      getSummary(from, to),
      listAccounts(true),
      listCategories(true),
      listTransactions(query),
    ]);
    if (request !== requestId.current) {
      return;
    }
    const failure = [summaryResult, accountResult, categoryResult, recentResult].find((result) => !result.ok);
    if (failure && !failure.ok) {
      if (!failure.aborted && !redirectIfUnauthorized(failure)) {
        setError(failure.message);
      }
      setLoading(false);
      setRefreshing(false);
      return;
    }
    if (summaryResult.ok && accountResult.ok && categoryResult.ok && recentResult.ok) {
      setSummary(summaryResult.data);
      setAccounts(accountResult.data);
      setCategories(categoryResult.data);
      setRecent(recentResult.data);
      setError("");
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void load(true);
    return () => {
      requestId.current += 1;
    };
  }, [load]);

  useEffect(() => {
    function onFocus() {
      void load(false);
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  if (loading) {
    return <p className="text-stone-600">Carregando suas finanças...</p>;
  }

  const month = summary ? formatMonthLabel(summary.period_from) : "";
  const noMovement =
    summary?.period_income === "0.00" &&
    summary.period_expense === "0.00" &&
    (recent?.items.length ?? 0) === 0;
  const needsCategory = selectableCategories(categories).length === 0;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-stone-500">Olá, {user.name}</p>
          <p className="mt-1 text-sm text-stone-600">Os valores vêm do seu registro financeiro{month ? ` · ${month}` : ""}.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/transactions?novo=receita" className={primaryButtonClass}>
            Nova receita
          </Link>
          <Link href="/transactions?novo=despesa" className={secondaryButtonClass}>
            Nova despesa
          </Link>
          <Link href="/transactions?novo=transferencia" className={secondaryButtonClass}>
            Transferir
          </Link>
        </div>
      </div>
      {refreshing ? <p className="text-sm text-stone-500">Atualizando dados...</p> : null}
      <ErrorBanner message={error} onRetry={() => void load(false)} />
      {summary ? <SummaryCards summary={summary} /> : null}
      {noMovement ? (
        <EmptyState title="Comece pelo primeiro lançamento">
          <p>Registre uma receita ou uma despesa para ver o mês ganhar forma. O saldo das contas continua vindo do sistema.</p>
          {needsCategory ? (
            <p className="mt-3">
              <Link href="/categories" className="font-medium text-emerald-800">
                Cadastre uma categoria
              </Link>{" "}
              antes da primeira receita ou despesa.
            </p>
          ) : null}
        </EmptyState>
      ) : null}
      <section className="grid gap-6 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <div>
          <h2 className="text-base font-semibold text-stone-950">Contas</h2>
          <ul className="mt-3 grid gap-3">
            {accounts.map((account) => (
              <li key={account.id} className="rounded-2xl border border-stone-200 bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-stone-950">{account.name}</p>
                    <p className="mt-1 text-xs text-stone-500">
                      {account.archived_at ? "Arquivada" : "Ativa"}
                      {account.is_default ? " · Padrão" : ""}
                    </p>
                  </div>
                  <p className="font-semibold">{formatBrl(account.balance)}</p>
                </div>
                {isNegativeMoney(account.balance) ? (
                  <p className="mt-2 text-sm text-amber-800">Esta conta está com saldo negativo.</p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-stone-950">Movimentações recentes</h2>
            <Link href="/transactions" className="text-sm font-medium text-emerald-800">
              Ver histórico
            </Link>
          </div>
          <div className="mt-3">
            {recent && recent.items.length > 0 ? (
              <EntryList
                entries={recent.items}
                accounts={accounts}
                onEdit={(entry) => router.push(`/transactions?editar=${entry.id}`)}
              />
            ) : (
              <p className="text-sm text-stone-600">Nenhuma movimentação registrada.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
