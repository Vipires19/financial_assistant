"use client";

import { FormEvent, useState } from "react";
import { CategorySelect } from "@/components/finance/CategorySelect";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { MoneyField } from "@/components/ui/MoneyField";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { appToday, formatDateBr } from "@/lib/dates";
import { selectableCategories } from "@/lib/finance";
import { moneyToInput, parseMoneyInput } from "@/lib/money";
import type { Category, Obligation, ObligationDetail } from "@/lib/types";

export function PayableForm({
  categories,
  editing,
  onCancel,
  onSaved,
}: {
  categories: Category[];
  editing?: Obligation | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const paid = editing?.status === "paid";
  const available = withCurrent(selectableCategories(categories), categories, editing?.category_id);
  const [description, setDescription] = useState(editing?.description ?? "");
  const [amount, setAmount] = useState(editing ? moneyToInput(editing.expected_amount) : "");
  const [dueOn, setDueOn] = useState(editing?.due_on ?? appToday());
  const [categoryId, setCategoryId] = useState(editing?.category_id ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) {
      return;
    }
    const nextErrors: Record<string, string> = {};
    if (!description.trim()) {
      nextErrors.description = "Informe a descrição.";
    }
    const parsed = parseMoneyInput(amount, { positive: true });
    if (!paid && !parsed.ok) {
      nextErrors.amount = parsed.message;
    }
    if (!paid && !dueOn) {
      nextErrors.dueOn = "Informe o vencimento.";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setPending(true);
    setFormError("");
    const payload = paid
      ? { description: description.trim() }
      : {
          description: description.trim(),
          expected_amount: parsed.ok ? parsed.value : amount,
          due_on: dueOn,
          category_id: categoryId || null,
        };
    const result = editing
      ? await apiSend<ObligationDetail>(`/api/payables/${editing.id}`, "PATCH", payload)
      : await apiSend<ObligationDetail>("/api/payables", "POST", payload);
    if (!result.ok) {
      if (!result.aborted && !redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    onSaved(editing ? "Conta a pagar atualizada." : "Conta a pagar cadastrada.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label={editing ? "Editar conta a pagar" : "Nova conta a pagar"}>
      <h2 className="text-lg font-semibold text-stone-950">{editing ? "Editar conta" : "Nova conta"}</h2>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="md:col-span-2">
          <Field id="payable-description" label="Descrição" error={errors.description}>
            <input
              id="payable-description"
              value={description}
              maxLength={160}
              aria-invalid={errors.description ? true : undefined}
              aria-describedby={errors.description ? fieldErrorId("payable-description") : undefined}
              onChange={(event) => setDescription(event.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
        {paid ? (
          <>
            <p className="text-sm text-stone-700">
              Valor previsto
              <span className="mt-1 block font-medium text-stone-950">{editing ? moneyToInput(editing.expected_amount) : ""}</span>
            </p>
            <p className="text-sm text-stone-700">
              Vencimento
              <span className="mt-1 block font-medium text-stone-950">{editing ? formatDateBr(editing.due_on) : ""}</span>
            </p>
            <p className="text-sm text-stone-700">
              Categoria
              <span className="mt-1 block font-medium text-stone-950">{editing?.category_name ?? "Sem categoria"}</span>
            </p>
          </>
        ) : (
          <>
            <MoneyField id="payable-amount" label="Valor previsto" value={amount} onChange={setAmount} error={errors.amount} />
            <Field id="payable-due" label="Vencimento" error={errors.dueOn}>
              <input
                id="payable-due"
                type="date"
                required
                value={dueOn}
                aria-invalid={errors.dueOn ? true : undefined}
                aria-describedby={errors.dueOn ? fieldErrorId("payable-due") : undefined}
                onChange={(event) => setDueOn(event.target.value)}
                className={inputClass}
              />
            </Field>
            <CategorySelect
              id="payable-category"
              categories={available}
              value={categoryId}
              onChange={setCategoryId}
              emptyLabel="Sem categoria"
            />
          </>
        )}
      </div>
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending}>
          {pending ? "Salvando..." : editing ? "Salvar alterações" : "Cadastrar"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function withCurrent(options: Category[], all: Category[], currentId: string | null | undefined): Category[] {
  if (!currentId || options.some((item) => item.id === currentId)) {
    return options;
  }
  const current = all.find((item) => item.id === currentId);
  return current ? [...options, current] : options;
}
