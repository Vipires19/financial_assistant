import Link from "next/link";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { inputClass } from "@/components/ui/classes";
import type { Category } from "@/lib/types";

export function CategorySelect({
  id,
  categories,
  value,
  onChange,
  error,
  emptyLabel = "Selecione",
  disabled = false,
}: {
  id: string;
  categories: Category[];
  value: string;
  onChange: (value: string) => void;
  error?: string;
  emptyLabel?: string;
  disabled?: boolean;
}) {
  return (
    <Field id={id} label="Categoria" error={error}>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? fieldErrorId(id) : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      >
        <option value="">{emptyLabel}</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
            {category.archived_at ? " · arquivada" : ""}
          </option>
        ))}
      </select>
      {categories.length === 0 ? (
        <p className="mt-2 text-sm text-stone-600">
          Nenhuma categoria disponível.{" "}
          <Link href="/categories" className="font-medium text-emerald-800">
            Cadastrar categoria
          </Link>
        </p>
      ) : null}
    </Field>
  );
}
