"use client";

import { FormEvent, useState } from "react";
import { AccountSelect } from "@/components/finance/AccountSelect";
import { CategorySelect } from "@/components/finance/CategorySelect";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { MoneyField } from "@/components/ui/MoneyField";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { appToday } from "@/lib/dates";
import { preferredAccountId, selectableAccounts, selectableCategories } from "@/lib/finance";
import { moneyToInput, parseMoneyInput } from "@/lib/money";
import { writeLastAccount } from "@/lib/preferences";
import type { Account, Category, Entry } from "@/lib/types";

export function TransactionForm({
  userId,
  accounts,
  categories,
  kind = "income",
  editing,
  draft,
  onCancel,
  onSaved,
}: {
  userId: string;
  accounts: Account[];
  categories: Category[];
  kind?: "income" | "expense";
  editing?: Entry | null;
  draft?: Entry | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const draftKind = draft?.kind === "income" || draft?.kind === "expense" ? draft.kind : undefined;
  const lockedKind =
    editing?.kind === "income" || editing?.kind === "expense" ? editing.kind : draftKind ?? kind;
  const activeAccounts = withCurrent(selectableAccounts(accounts), accounts, editing?.account_id);
  const activeCategories = withCurrent(
    selectableCategories(categories),
    categories.filter((category) => !category.is_internal),
    editing?.category_id,
  );
  const [accountId, setAccountId] = useState(
    editing?.account_id ?? draft?.account_id ?? preferredAccountId(userId, accounts),
  );
  const [categoryId, setCategoryId] = useState(editing?.category_id ?? draft?.category_id ?? activeCategories[0]?.id ?? "");
  const [amount, setAmount] = useState(editing ? moneyToInput(editing.amount) : draft?.amount ? moneyToInput(draft.amount) : "");
  const [occurredOn, setOccurredOn] = useState(editing?.occurred_on ?? appToday());
  const [description, setDescription] = useState(editing?.description ?? draft?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);
  const title = editing ? "Editar lançamento" : lockedKind === "income" ? "Nova receita" : "Nova despesa";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) {
      return;
    }
    const nextErrors: Record<string, string> = {};
    const parsed = parseMoneyInput(amount, { positive: true });
    if (!parsed.ok) {
      nextErrors.amount = parsed.message;
    }
    if (!accountId) {
      nextErrors.accountId = "Selecione a conta.";
    }
    if (!categoryId) {
      nextErrors.categoryId = "Selecione a categoria.";
    }
    if (!occurredOn) {
      nextErrors.occurredOn = "Informe a data.";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || !parsed.ok) {
      return;
    }

    setPending(true);
    setFormError("");
    const payload = {
      account_id: accountId,
      category_id: categoryId,
      amount: parsed.value,
      occurred_on: occurredOn,
      description: description.trim() ? description.trim() : null,
    };
    const result = editing
      ? await apiSend<Entry>(`/api/transactions/${editing.id}`, "PATCH", payload)
      : await apiSend<Entry>("/api/transactions", "POST", { ...payload, kind: lockedKind });
    if (!result.ok) {
      if (result.aborted) {
        return;
      }
      if (!redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    writeLastAccount(userId, accountId);
    onSaved(editing ? "Lançamento atualizado." : lockedKind === "income" ? "Receita registrada." : "Despesa registrada.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label={title}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-950">{title}</h2>
          <p className="mt-1 text-sm text-stone-600">
            {lockedKind === "income" ? "Receita" : "Despesa"}
            {editing ? " · o tipo permanece o mesmo" : ""}
          </p>
        </div>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <MoneyField id="transaction-amount" label="Valor" value={amount} onChange={setAmount} error={errors.amount} />
        <AccountSelect
          id="transaction-account"
          label="Conta"
          accounts={activeAccounts}
          value={accountId}
          onChange={setAccountId}
          error={errors.accountId}
        />
        <CategorySelect
          id="transaction-category"
          categories={activeCategories}
          value={categoryId}
          onChange={setCategoryId}
          error={errors.categoryId}
        />
        <Field id="transaction-date" label="Data" error={errors.occurredOn}>
          <input
            id="transaction-date"
            type="date"
            required
            value={occurredOn}
            aria-invalid={errors.occurredOn ? true : undefined}
            aria-describedby={errors.occurredOn ? fieldErrorId("transaction-date") : undefined}
            onChange={(event) => setOccurredOn(event.target.value)}
            className={inputClass}
          />
        </Field>
        <div className="md:col-span-2">
          <Field id="transaction-description" label="Descrição" hint="Opcional">
            <input
              id="transaction-description"
              value={description}
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
      </div>
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending}>
          {pending ? "Salvando..." : editing ? "Salvar alterações" : lockedKind === "income" ? "Salvar receita" : "Salvar despesa"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function withCurrent<T extends { id: string }>(options: T[], all: T[], currentId: string | null | undefined): T[] {
  if (!currentId || options.some((item) => item.id === currentId)) {
    return options;
  }
  const current = all.find((item) => item.id === currentId);
  return current ? [...options, current] : options;
}
