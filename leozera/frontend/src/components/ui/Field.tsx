import type { ReactNode } from "react";

export function fieldErrorId(id: string): string {
  return `${id}-error`;
}

export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      {children}
      {hint ? <p className="mt-1 text-sm text-stone-500">{hint}</p> : null}
      {error ? (
        <p id={fieldErrorId(id)} role="alert" className="mt-1 text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
