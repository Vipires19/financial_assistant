import { Field, fieldErrorId } from "@/components/ui/Field";
import { inputClass } from "@/components/ui/classes";
import type { Account } from "@/lib/types";

export function AccountSelect({
  id,
  label,
  accounts,
  value,
  onChange,
  error,
  disabled = false,
}: {
  id: string;
  label: string;
  accounts: Account[];
  value: string;
  onChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
}) {
  return (
    <Field id={id} label={label} error={error}>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? fieldErrorId(id) : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      >
        <option value="">Selecione</option>
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>
            {account.name}
            {account.is_default ? " · padrão" : ""}
            {account.archived_at ? " · arquivada" : ""}
          </option>
        ))}
      </select>
    </Field>
  );
}
