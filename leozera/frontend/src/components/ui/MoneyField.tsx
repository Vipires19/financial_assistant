import { Field, fieldErrorId } from "@/components/ui/Field";
import { inputClass } from "@/components/ui/classes";

export function MoneyField({
  id,
  label,
  value,
  onChange,
  error,
  hint,
  disabled = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <Field id={id} label={label} error={error} hint={hint}>
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? fieldErrorId(id) : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </Field>
  );
}
