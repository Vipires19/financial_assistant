"use client";

import { FormEvent, useEffect, useState } from "react";
import { AccountSelect } from "@/components/finance/AccountSelect";
import { CategorySelect } from "@/components/finance/CategorySelect";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { MoneyField } from "@/components/ui/MoneyField";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { redirectIfUnauthorized } from "@/lib/api";
import { appToday } from "@/lib/dates";
import { preferredAccountId, selectableAccounts, selectableCategories } from "@/lib/finance";
import { moneyToInput, parseMoneyInput } from "@/lib/money";
import {
  PAYMENT_TIMEOUT_MS,
  clearPaymentAttempt,
  payObligation,
  paymentResultIsUnknown,
  readPaymentAttempt,
  writePaymentAttempt,
  type PaymentBody,
} from "@/lib/payables";
import { writeLastAccount } from "@/lib/preferences";
import type { Account, Category, Obligation } from "@/lib/types";

const UNKNOWN_MESSAGE = "Não foi possível confirmar o pagamento. A mesma tentativa continua disponível.";

export function PaymentForm({
  userId,
  obligation,
  accounts,
  categories,
  onCancel,
  onConfirmed,
}: {
  userId: string;
  obligation: Obligation;
  accounts: Account[];
  categories: Category[];
  onCancel: () => void;
  onConfirmed: (message: string) => void;
}) {
  const activeAccounts = selectableAccounts(accounts);
  const activeCategories = withCurrent(selectableCategories(categories), categories, obligation.category_id);
  const [ready, setReady] = useState(false);
  const [key, setKey] = useState("");
  const [frozen, setFrozen] = useState<PaymentBody | null>(null);
  const [accountId, setAccountId] = useState(preferredAccountId(userId, accounts));
  const [categoryId, setCategoryId] = useState(obligation.category_id ?? "");
  const [amount, setAmount] = useState(moneyToInput(obligation.expected_amount));
  const [occurredOn, setOccurredOn] = useState(appToday());
  const [description, setDescription] = useState(obligation.description);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);
  const [needsNewIntention, setNeedsNewIntention] = useState(false);

  useEffect(() => {
    const stored = readPaymentAttempt(userId, obligation.id);
    if (stored) {
      setKey(stored.key);
      setFrozen(stored.body);
      setAccountId(stored.body.account_id);
      setCategoryId(stored.body.category_id ?? "");
      setAmount(moneyToInput(stored.body.amount));
      setOccurredOn(stored.body.occurred_on);
      setDescription(stored.body.description ?? "");
      setFormError(UNKNOWN_MESSAGE);
    } else {
      setKey((current) => current || crypto.randomUUID());
    }
    setReady(true);
  }, [obligation.id, userId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || needsNewIntention) {
      return;
    }
    const body = frozen ?? buildBody();
    if (!body) {
      return;
    }
    const attempt = { key, body };
    writePaymentAttempt(userId, obligation.id, attempt);
    setFrozen(body);
    setPending(true);
    setFormError("");
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), PAYMENT_TIMEOUT_MS);
    const result = await payObligation(obligation.id, body, key, controller.signal);
    window.clearTimeout(timer);
    if (!result.ok) {
      const timedOut = Boolean(result.aborted) && controller.signal.aborted;
      if (paymentResultIsUnknown(result.status, Boolean(result.aborted), timedOut)) {
        setFormError(UNKNOWN_MESSAGE);
        setPending(false);
        return;
      }
      if (redirectIfUnauthorized(result)) {
        setPending(false);
        return;
      }
      clearPaymentAttempt(userId, obligation.id);
      setFrozen(null);
      if (result.status === 409 && result.message.includes("já está paga")) {
        onConfirmed(result.message);
        return;
      }
      if (result.status === 409 && result.message.includes("já foi usada com outros dados")) {
        setNeedsNewIntention(true);
      }
      setFormError(result.message);
      setPending(false);
      return;
    }
    clearPaymentAttempt(userId, obligation.id);
    writeLastAccount(userId, body.account_id);
    onConfirmed(result.data.replayed ? "Pagamento já estava registrado." : "Pagamento registrado.");
  }

  function buildBody(): PaymentBody | null {
    const nextErrors: Record<string, string> = {};
    const parsed = parseMoneyInput(amount, { positive: true });
    if (!parsed.ok) {
      nextErrors.amount = parsed.message;
    }
    if (!accountId) {
      nextErrors.accountId = "Selecione a conta.";
    }
    if (!categoryId && !obligation.category_id) {
      nextErrors.categoryId = "Selecione a categoria.";
    }
    if (!occurredOn) {
      nextErrors.occurredOn = "Informe a data.";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || !parsed.ok) {
      return null;
    }
    const body: PaymentBody = {
      account_id: accountId,
      amount: parsed.value,
      occurred_on: occurredOn,
      description: description.trim() ? description.trim() : null,
    };
    if (categoryId) {
      body.category_id = categoryId;
    }
    return body;
  }

  function startNewIntention() {
    clearPaymentAttempt(userId, obligation.id);
    setKey(crypto.randomUUID());
    setFrozen(null);
    setNeedsNewIntention(false);
    setFormError("");
  }

  if (!ready) {
    return null;
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label="Pagar conta">
      <h2 className="text-lg font-semibold text-stone-950">Pagar</h2>
      <p className="mt-1 text-sm text-stone-600">{obligation.description}</p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <MoneyField id="payment-amount" label="Valor" value={amount} onChange={setAmount} error={errors.amount} disabled={frozen !== null} />
        <AccountSelect
          id="payment-account"
          label="Conta"
          accounts={activeAccounts}
          value={accountId}
          onChange={setAccountId}
          error={errors.accountId}
          disabled={frozen !== null}
        />
        <CategorySelect
          id="payment-category"
          categories={activeCategories}
          value={categoryId}
          onChange={setCategoryId}
          error={errors.categoryId}
          emptyLabel="Sem categoria"
          disabled={frozen !== null}
        />
        <Field id="payment-date" label="Data do pagamento" error={errors.occurredOn}>
          <input
            id="payment-date"
            type="date"
            required
            max={appToday()}
            value={occurredOn}
            aria-invalid={errors.occurredOn ? true : undefined}
            aria-describedby={errors.occurredOn ? fieldErrorId("payment-date") : undefined}
            onChange={(event) => setOccurredOn(event.target.value)}
            className={inputClass}
            disabled={frozen !== null}
          />
        </Field>
        <div className="md:col-span-2">
          <Field id="payment-description" label="Descrição">
            <input
              id="payment-description"
              value={description ?? ""}
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
              className={inputClass}
              disabled={frozen !== null}
            />
          </Field>
        </div>
      </div>
      {frozen ? (
        <fieldset disabled className="mt-4 text-sm text-stone-600">
          <legend className="font-medium text-stone-800">Tentativa preservada</legend>
          <p className="mt-2">Valor {moneyToInput(frozen.amount)} · conta já escolhida · {frozen.occurred_on}</p>
        </fieldset>
      ) : null}
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending || needsNewIntention}>
          {pending ? "Pagando..." : frozen ? "Confirmar novamente" : "Confirmar pagamento"}
        </button>
        {frozen || needsNewIntention ? (
          <button type="button" className={secondaryButtonClass} onClick={startNewIntention} disabled={pending}>
            Nova tentativa
          </button>
        ) : null}
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

function withCurrent(options: Category[], all: Category[], currentId: string | null): Category[] {
  if (!currentId || options.some((item) => item.id === currentId)) {
    return options;
  }
  const current = all.find((item) => item.id === currentId);
  return current ? [...options, current] : options;
}
