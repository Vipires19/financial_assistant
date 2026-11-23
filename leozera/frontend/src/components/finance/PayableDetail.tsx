"use client";

import { accountName } from "@/lib/finance";
import { formatDateBr } from "@/lib/dates";
import { formatBrl } from "@/lib/money";
import { secondaryButtonClass } from "@/components/ui/classes";
import type { Account, ObligationDetail } from "@/lib/types";

const STATUS_LABEL = {
  open: "Em aberto",
  overdue: "Vencida",
  paid: "Paga",
  archived: "Arquivada",
} as const;

export function PayableDetail({
  obligation,
  accounts,
  onClose,
}: {
  obligation: ObligationDetail;
  accounts: Account[];
  onClose: () => void;
}) {
  const active = obligation.settlements.filter((item) => item.released_at === null);
  const released = obligation.settlements.filter((item) => item.released_at !== null);

  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm" aria-label="Detalhe da conta a pagar">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-950">{obligation.description}</h2>
          <p className="mt-1 text-sm text-stone-600">{STATUS_LABEL[obligation.status]}</p>
        </div>
        <button type="button" className={secondaryButtonClass} onClick={onClose}>
          Fechar
        </button>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-stone-500">Valor previsto</dt>
          <dd className="mt-1 font-medium text-stone-950">{formatBrl(obligation.expected_amount)}</dd>
        </div>
        <div>
          <dt className="text-stone-500">Vencimento</dt>
          <dd className="mt-1 font-medium text-stone-950">{formatDateBr(obligation.due_on)}</dd>
        </div>
        <div>
          <dt className="text-stone-500">Pago</dt>
          <dd className="mt-1 font-medium text-stone-950">{obligation.paid_amount ? formatBrl(obligation.paid_amount) : "—"}</dd>
        </div>
      </dl>
      <h3 className="mt-6 text-sm font-semibold text-stone-950">Pagamento vigente</h3>
      {active.length === 0 ? (
        <p className="mt-2 text-sm text-stone-600">Nenhum pagamento vigente.</p>
      ) : (
        <SettlementList items={active} accounts={accounts} released={false} />
      )}
      <h3 className="mt-6 text-sm font-semibold text-stone-950">Quitações liberadas</h3>
      {released.length === 0 ? (
        <p className="mt-2 text-sm text-stone-600">Nenhuma quitação liberada.</p>
      ) : (
        <SettlementList items={released} accounts={accounts} released />
      )}
    </section>
  );
}

function SettlementList({
  items,
  accounts,
  released,
}: {
  items: ObligationDetail["settlements"];
  accounts: Account[];
  released: boolean;
}) {
  return (
    <ul className="mt-2 grid gap-2">
      {items.map((item) => (
        <li key={item.id} className="rounded-xl border border-stone-200 px-3 py-2 text-sm">
          <p className="font-medium text-stone-950">
            {formatBrl(item.allocated_amount)}
            {released ? " · liberada" : ""}
            {item.entry_deleted_at ? " · despesa excluída" : ""}
          </p>
          <p className="text-stone-600">
            {formatDateBr(item.entry_occurred_on)} · {accountName(accounts, item.entry_account_id)}
          </p>
        </li>
      ))}
    </ul>
  );
}
