"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AdjustmentForm } from "@/components/finance/AdjustmentForm";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { MoneyField } from "@/components/ui/MoneyField";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { StatusMessage } from "@/components/ui/StatusMessage";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { appToday } from "@/lib/dates";
import { listAccounts } from "@/lib/finance";
import { formatBrl, isNegativeMoney, moneyToInput, parseMoneyInput } from "@/lib/money";
import type { Account } from "@/lib/types";

export function AccountsView() {
  const requestId = useRef(0);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<"create" | "edit" | "adjust" | null>(null);
  const [selected, setSelected] = useState<Account | null>(null);
  const [confirmArchive, setConfirmArchive] = useState<Account | null>(null);
  const [pendingArchive, setPendingArchive] = useState(false);

  const load = useCallback(async (initial: boolean) => {
    const request = ++requestId.current;
    if (initial) {
      setLoading(true);
    }
    const result = await listAccounts(true);
    if (request !== requestId.current) {
      return;
    }
    if (!result.ok) {
      if (!result.aborted && !redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      setLoading(false);
      return;
    }
    setAccounts(result.data);
    setError("");
    setLoading(false);
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

  async function archive(account: Account) {
    setPendingArchive(true);
    const result = await apiSend<Account>(`/api/accounts/${account.id}/archive`, "POST");
    setPendingArchive(false);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setConfirmArchive(null);
    setMessage("Conta arquivada.");
    setMode(null);
    await load(false);
  }

  async function reactivate(account: Account) {
    const result = await apiSend<Account>(`/api/accounts/${account.id}/reactivate`, "POST");
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setMessage("Conta reativada.");
    await load(false);
  }

  const active = accounts.filter((account) => account.archived_at === null);
  const archived = accounts.filter((account) => account.archived_at !== null);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-stone-600">
          O saldo exibido é a posição atual calculada pelo sistema. Arquivar guarda a conta e o histórico.
        </p>
        <button
          type="button"
          className={primaryButtonClass}
          onClick={() => {
            setSelected(null);
            setMode("create");
            setMessage("");
          }}
        >
          Nova conta
        </button>
      </div>
      <StatusMessage message={message} />
      <ErrorBanner message={error} onRetry={() => void load(false)} />
      {mode === "create" || (mode === "edit" && selected) ? (
        <AccountForm
          account={mode === "edit" ? selected : null}
          onCancel={() => setMode(null)}
          onSaved={async (text) => {
            setMode(null);
            setMessage(text);
            await load(false);
          }}
        />
      ) : null}
      {mode === "adjust" && selected ? (
        <AdjustmentForm
          accounts={accounts}
          accountId={selected.id}
          onCancel={() => setMode(null)}
          onSaved={async (text) => {
            setMode(null);
            setMessage(text);
            await load(false);
          }}
        />
      ) : null}
      {loading ? <p className="text-stone-600">Carregando contas...</p> : null}
      <AccountSection
        title="Ativas"
        accounts={active}
        onEdit={(account) => {
          setSelected(account);
          setMode("edit");
        }}
        onAdjust={(account) => {
          setSelected(account);
          setMode("adjust");
        }}
        onArchive={setConfirmArchive}
      />
      <AccountSection
        title="Arquivadas"
        accounts={archived}
        onReactivate={(account) => void reactivate(account)}
      />
      <ConfirmDialog
        open={confirmArchive !== null}
        title="Arquivar conta"
        description={
          confirmArchive
            ? `${confirmArchive.name} sai dos novos lançamentos e continua no histórico e no saldo total.`
            : ""
        }
        confirmLabel="Arquivar"
        pending={pendingArchive}
        onConfirm={() => {
          if (confirmArchive) {
            void archive(confirmArchive);
          }
        }}
        onCancel={() => {
          if (!pendingArchive) {
            setConfirmArchive(null);
          }
        }}
      />
    </div>
  );
}

function AccountSection({
  title,
  accounts,
  onEdit,
  onAdjust,
  onArchive,
  onReactivate,
}: {
  title: string;
  accounts: Account[];
  onEdit?: (account: Account) => void;
  onAdjust?: (account: Account) => void;
  onArchive?: (account: Account) => void;
  onReactivate?: (account: Account) => void;
}) {
  if (accounts.length === 0) {
    return null;
  }
  return (
    <section>
      <h2 className="text-base font-semibold text-stone-950">{title}</h2>
      <ul className="mt-3 grid gap-3">
        {accounts.map((account) => (
          <li key={account.id} className="rounded-2xl border border-stone-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium text-stone-950">{account.name}</p>
                <p className="mt-1 text-sm text-stone-500">
                  {account.archived_at ? "Arquivada" : "Ativa"}
                  {account.is_default ? " · Padrão" : ""}
                  {" · "}início em {account.opened_on.split("-").reverse().join("/")}
                </p>
                {isNegativeMoney(account.balance) ? (
                  <p className="mt-2 text-sm text-amber-800">Saldo negativo. Você ainda pode registrar movimentações.</p>
                ) : null}
              </div>
              <p className="text-lg font-semibold">{formatBrl(account.balance)}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {onEdit ? (
                <button type="button" className={secondaryButtonClass} onClick={() => onEdit(account)}>
                  Editar
                </button>
              ) : null}
              {onAdjust ? (
                <button type="button" className={secondaryButtonClass} onClick={() => onAdjust(account)}>
                  Ajustar saldo
                </button>
              ) : null}
              {onArchive ? (
                <button type="button" className={secondaryButtonClass} onClick={() => onArchive(account)}>
                  Arquivar
                </button>
              ) : null}
              {onReactivate ? (
                <button type="button" className={secondaryButtonClass} onClick={() => onReactivate(account)}>
                  Reativar
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AccountForm({
  account,
  onCancel,
  onSaved,
}: {
  account: Account | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const [name, setName] = useState(account?.name ?? "");
  const [initialBalance, setInitialBalance] = useState(account ? moneyToInput(account.initial_balance) : "0,00");
  const [openedOn, setOpenedOn] = useState(account?.opened_on ?? appToday());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) {
      return;
    }
    const nextErrors: Record<string, string> = {};
    if (!name.trim()) {
      nextErrors.name = "Informe o nome da conta.";
    }
    const parsed = parseMoneyInput(initialBalance);
    if (!parsed.ok) {
      nextErrors.initialBalance = parsed.message;
    }
    if (!openedOn) {
      nextErrors.openedOn = "Informe a data de início.";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || !parsed.ok) {
      return;
    }
    setPending(true);
    setFormError("");
    const payload = {
      name: name.trim(),
      initial_balance: parsed.value,
      opened_on: openedOn,
    };
    const result = account
      ? await apiSend<Account>(`/api/accounts/${account.id}`, "PATCH", payload)
      : await apiSend<Account>("/api/accounts", "POST", payload);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    onSaved(account ? "Conta atualizada." : "Conta criada.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{account ? "Editar conta" : "Nova conta"}</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field id="account-name" label="Nome" error={errors.name}>
          <input
            id="account-name"
            value={name}
            maxLength={80}
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={errors.name ? fieldErrorId("account-name") : undefined}
            onChange={(event) => setName(event.target.value)}
            className={inputClass}
          />
        </Field>
        <MoneyField
          id="account-initial"
          label="Saldo inicial"
          value={initialBalance}
          onChange={setInitialBalance}
          error={errors.initialBalance}
        />
        <Field id="account-opened" label="Início do controle" error={errors.openedOn}>
          <input
            id="account-opened"
            type="date"
            value={openedOn}
            aria-invalid={errors.openedOn ? true : undefined}
            aria-describedby={errors.openedOn ? fieldErrorId("account-opened") : undefined}
            onChange={(event) => setOpenedOn(event.target.value)}
            className={inputClass}
          />
        </Field>
      </div>
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending}>
          {pending ? "Salvando..." : "Salvar conta"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
