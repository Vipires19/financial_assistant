import { quietButtonClass } from "@/components/ui/classes";
import { accountName } from "@/lib/finance";
import { formatDateBr } from "@/lib/dates";
import { formatBrl } from "@/lib/money";
import type { Account, Entry } from "@/lib/types";

const KIND_LABEL = {
  income: "Receita",
  expense: "Despesa",
  transfer: "Transferência",
  adjustment: "Ajuste",
} as const;

const KIND_CLASS = {
  income: "bg-emerald-50 text-emerald-900",
  expense: "bg-rose-50 text-rose-900",
  transfer: "bg-sky-50 text-sky-950",
  adjustment: "bg-amber-50 text-amber-950",
} as const;

export function EntryList({
  entries,
  accounts,
  onEdit,
  onDelete,
  onRestore,
  onDuplicate,
}: {
  entries: Entry[];
  accounts: Account[];
  onEdit?: (entry: Entry) => void;
  onDelete?: (entry: Entry) => void;
  onRestore?: (entry: Entry) => void;
  onDuplicate?: (entry: Entry) => void;
}) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <>
      <div className="hidden overflow-hidden rounded-2xl border border-stone-200 bg-white md:block">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Movimentações</caption>
          <thead className="border-b border-stone-200 text-stone-500">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Data</th>
              <th scope="col" className="px-4 py-3 font-medium">Descrição</th>
              <th scope="col" className="px-4 py-3 font-medium">Conta</th>
              <th scope="col" className="px-4 py-3 font-medium">Tipo</th>
              <th scope="col" className="px-4 py-3 font-medium">Valor</th>
              <th scope="col" className="px-4 py-3 font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id} className="border-b border-stone-100 last:border-0">
                <td className="px-4 py-3 whitespace-nowrap">{formatDateBr(entry.occurred_on)}</td>
                <td className="px-4 py-3">
                  <EntryText entry={entry} />
                </td>
                <td className="px-4 py-3">{movementAccount(entry, accounts)}</td>
                <td className="px-4 py-3">
                  <KindBadge entry={entry} />
                </td>
                <td className="px-4 py-3 font-medium whitespace-nowrap">{formatBrl(entry.amount)}</td>
                <td className="px-4 py-3">
                  <EntryActions
                    entry={entry}
                    onEdit={onEdit}
                    onDelete={onDelete}
                    onRestore={onRestore}
                    onDuplicate={onDuplicate}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="grid gap-3 md:hidden">
        {entries.map((entry) => (
          <li key={entry.id} className="rounded-2xl border border-stone-200 bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <KindBadge entry={entry} />
                <p className="mt-2 font-medium text-stone-950">
                  <EntryText entry={entry} />
                </p>
              </div>
              <p className="font-semibold whitespace-nowrap">{formatBrl(entry.amount)}</p>
            </div>
            <p className="mt-2 text-sm text-stone-600">{formatDateBr(entry.occurred_on)}</p>
            <p className="text-sm text-stone-600">{movementAccount(entry, accounts)}</p>
            <div className="mt-3">
              <EntryActions
                entry={entry}
                onEdit={onEdit}
                onDelete={onDelete}
                onRestore={onRestore}
                onDuplicate={onDuplicate}
              />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function EntryText({ entry }: { entry: Entry }) {
  return (
    <span>
      <span className={entry.deleted_at ? "text-stone-500 line-through" : undefined}>{entryLabel(entry)}</span>
      {entry.kind === "adjustment" ? (
        <span className="mt-1 block text-xs font-normal text-amber-900">Correção de saldo, sem ser receita ou despesa.</span>
      ) : null}
      {entry.kind === "transfer" ? (
        <span className="mt-1 block text-xs font-normal text-sky-950">Movimentação interna, sem ser receita ou despesa.</span>
      ) : null}
    </span>
  );
}

function KindBadge({ entry }: { entry: Entry }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${KIND_CLASS[entry.kind]}`}>
      {KIND_LABEL[entry.kind]}
      {entry.deleted_at ? " · excluída" : ""}
    </span>
  );
}

function EntryActions({
  entry,
  onEdit,
  onDelete,
  onRestore,
  onDuplicate,
}: {
  entry: Entry;
  onEdit?: (entry: Entry) => void;
  onDelete?: (entry: Entry) => void;
  onRestore?: (entry: Entry) => void;
  onDuplicate?: (entry: Entry) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {entry.deleted_at ? (
        onRestore ? (
          <button type="button" className={quietButtonClass} onClick={() => onRestore(entry)}>
            Restaurar
          </button>
        ) : null
      ) : (
        <>
          {onEdit ? (
            <button type="button" className={quietButtonClass} onClick={() => onEdit(entry)}>
              Editar
            </button>
          ) : null}
          {onDuplicate && (entry.kind === "income" || entry.kind === "expense") ? (
            <button type="button" className={quietButtonClass} onClick={() => onDuplicate(entry)}>
              Duplicar
            </button>
          ) : null}
          {onDelete ? (
            <button type="button" className={quietButtonClass} onClick={() => onDelete(entry)}>
              Excluir
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

function entryLabel(entry: Entry): string {
  if (entry.description) {
    return entry.description;
  }
  if (entry.kind === "transfer") {
    return "Transferência entre contas";
  }
  if (entry.kind === "adjustment") {
    return entry.category_name ?? "Ajuste de saldo";
  }
  return entry.category_name ?? "Sem descrição";
}

function movementAccount(entry: Entry, accounts: Account[]): string {
  if (entry.kind === "transfer") {
    return `${accountName(accounts, entry.account_id)} → ${accountName(accounts, entry.counter_account_id)}`;
  }
  const account = accounts.find((item) => item.id === entry.account_id);
  if (!account) {
    return "Conta";
  }
  return account.archived_at ? `${account.name} (arquivada)` : account.name;
}
