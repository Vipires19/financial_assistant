"use client";

import { FormEvent, useState } from "react";
import { AccountSelect } from "@/components/finance/AccountSelect";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { MoneyField } from "@/components/ui/MoneyField";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { appToday } from "@/lib/dates";
import { selectableAccounts } from "@/lib/finance";
import { formatBrl, parseMoneyInput } from "@/lib/money";
import type { Account, Entry } from "@/lib/types";

export function AdjustmentForm({
  accounts,
  accountId,
  editing,
  onCancel,
  onSaved,
}: {
  accounts: Account[];
  accountId?: string;
  editing?: Entry | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const active = selectableAccounts(accounts);
  const fixedAccountId = editing?.account_id ?? accountId ?? "";
  const fixedAccount = accounts.find((account) => account.id === fixedAccountId);
  const [selectedAccountId, setSelectedAccountId] = useState(fixedAccountId || active[0]?.id || "");
  const [balance, setBalance] = useState("");
  const [occurredOn, setOccurredOn] = useState(editing?.occurred_on ?? appToday());
  const [description, setDescription] = useState(editing?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);
  const targetAccountId = editing || accountId ? fixedAccountId : selectedAccountId;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) {
      return;
    }
    const nextErrors: Record<string, string> = {};
    const parsed = parseMoneyInput(balance);
    if (!parsed.ok) {
      nextErrors.balance = parsed.message;
    }
    if (!targetAccountId) {
      nextErrors.accountId = "Selecione a conta.";
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
      balance: parsed.value,
      occurred_on: occurredOn,
      description: description.trim() ? description.trim() : null,
    };
    const path = editing
      ? `/api/accounts/${targetAccountId}/adjustments/${editing.id}`
      : `/api/accounts/${targetAccountId}/adjustments`;
    const result = await apiSend<Entry>(path, editing ? "PATCH" : "POST", payload);
    if (!result.ok) {
      if (!result.aborted && !redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    onSaved(editing ? "Ajuste atualizado." : "Saldo ajustado.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label="Ajuste de saldo">
      <h2 className="text-lg font-semibold text-stone-950">{editing ? "Editar ajuste" : "Ajustar saldo"}</h2>
      <p className="mt-1 text-sm text-stone-600">
        Informe o saldo correto da conta. O sistema calcula a diferença. Um ajuste corrige a posição financeira e não
        representa uma receita ou despesa.
      </p>
      {editing ? (
        <p className="mt-3 text-sm text-stone-700">
          Correção já registrada: <strong>{formatBrl(editing.amount)}</strong>. Informe novamente o saldo correto.
        </p>
      ) : null}
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        {editing || accountId ? (
          <Field id="adjustment-account" label="Conta">
            <input id="adjustment-account" value={fixedAccount?.name ?? "Conta"} readOnly className={inputClass} />
          </Field>
        ) : (
          <AccountSelect
            id="adjustment-account"
            label="Conta"
            accounts={active}
            value={selectedAccountId}
            onChange={setSelectedAccountId}
            error={errors.accountId}
          />
        )}
        <MoneyField
          id="adjustment-balance"
          label="Saldo correto"
          value={balance}
          onChange={setBalance}
          error={errors.balance}
          hint="Pode ser zero ou negativo."
        />
        <Field id="adjustment-date" label="Data do ajuste" error={errors.occurredOn}>
          <input
            id="adjustment-date"
            type="date"
            required
            value={occurredOn}
            aria-invalid={errors.occurredOn ? true : undefined}
            aria-describedby={errors.occurredOn ? fieldErrorId("adjustment-date") : undefined}
            onChange={(event) => setOccurredOn(event.target.value)}
            className={inputClass}
          />
        </Field>
        <Field id="adjustment-description" label="Descrição" hint="Opcional">
          <input
            id="adjustment-description"
            value={description}
            maxLength={500}
            onChange={(event) => setDescription(event.target.value)}
            className={inputClass}
          />
        </Field>
      </div>
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending}>
          {pending ? "Salvando..." : "Salvar ajuste"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
