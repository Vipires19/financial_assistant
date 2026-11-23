"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AccountSelect } from "@/components/finance/AccountSelect";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { MoneyField } from "@/components/ui/MoneyField";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { appToday } from "@/lib/dates";
import { preferredAccountId, selectableAccounts } from "@/lib/finance";
import { moneyToInput, parseMoneyInput } from "@/lib/money";
import { writeLastAccount } from "@/lib/preferences";
import type { Account, Entry } from "@/lib/types";

export function TransferForm({
  userId,
  accounts,
  editing,
  onCancel,
  onSaved,
}: {
  userId: string;
  accounts: Account[];
  editing?: Entry | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const active = selectableAccounts(accounts);
  const originOptions = withCurrent(active, accounts, editing?.account_id);
  const destinationOptions = withCurrent(active, accounts, editing?.counter_account_id);
  const [fromAccountId, setFromAccountId] = useState(editing?.account_id ?? preferredAccountId(userId, accounts));
  const [toAccountId, setToAccountId] = useState(editing?.counter_account_id ?? "");
  const [amount, setAmount] = useState(editing ? moneyToInput(editing.amount) : "");
  const [occurredOn, setOccurredOn] = useState(editing?.occurred_on ?? appToday());
  const [description, setDescription] = useState(editing?.description ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);

  if (!editing && active.length < 2) {
    return (
      <div className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-stone-950">Nova transferência</h2>
        <p className="mt-2 text-sm text-stone-600">
          Uma transferência precisa de duas contas ativas.{" "}
          <Link href="/accounts" className="font-medium text-emerald-800">
            Criar outra conta
          </Link>
        </p>
      </div>
    );
  }

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
    if (!fromAccountId) {
      nextErrors.fromAccountId = "Selecione a conta de origem.";
    }
    if (!toAccountId) {
      nextErrors.toAccountId = "Selecione a conta de destino.";
    }
    if (fromAccountId && fromAccountId === toAccountId) {
      nextErrors.toAccountId = "A origem e o destino devem ser diferentes.";
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
      from_account_id: fromAccountId,
      to_account_id: toAccountId,
      amount: parsed.value,
      occurred_on: occurredOn,
      description: description.trim() ? description.trim() : null,
    };
    const result = editing
      ? await apiSend<Entry>(`/api/transfers/${editing.id}`, "PATCH", payload)
      : await apiSend<Entry>("/api/transfers", "POST", payload);
    if (!result.ok) {
      if (!result.aborted && !redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    writeLastAccount(userId, fromAccountId);
    onSaved(editing ? "Transferência atualizada." : "Transferência registrada.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label="Transferência">
      <h2 className="text-lg font-semibold text-stone-950">{editing ? "Editar transferência" : "Nova transferência"}</h2>
      <p className="mt-1 text-sm text-stone-600">
        A transferência move valor entre suas contas. Ela não é uma receita nem uma despesa.
      </p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <AccountSelect
          id="transfer-from"
          label="Conta de origem"
          accounts={originOptions}
          value={fromAccountId}
          onChange={setFromAccountId}
          error={errors.fromAccountId}
        />
        <AccountSelect
          id="transfer-to"
          label="Conta de destino"
          accounts={destinationOptions}
          value={toAccountId}
          onChange={setToAccountId}
          error={errors.toAccountId}
        />
        <MoneyField id="transfer-amount" label="Valor" value={amount} onChange={setAmount} error={errors.amount} />
        <Field id="transfer-date" label="Data" error={errors.occurredOn}>
          <input
            id="transfer-date"
            type="date"
            required
            value={occurredOn}
            aria-invalid={errors.occurredOn ? true : undefined}
            aria-describedby={errors.occurredOn ? fieldErrorId("transfer-date") : undefined}
            onChange={(event) => setOccurredOn(event.target.value)}
            className={inputClass}
          />
        </Field>
        <div className="md:col-span-2">
          <Field id="transfer-description" label="Descrição" hint="Opcional">
            <input
              id="transfer-description"
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
          {pending ? "Salvando..." : editing ? "Salvar alterações" : "Salvar transferência"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function withCurrent(options: Account[], all: Account[], currentId: string | null | undefined): Account[] {
  if (!currentId || options.some((item) => item.id === currentId)) {
    return options;
  }
  const current = all.find((item) => item.id === currentId);
  return current ? [...options, current] : options;
}
