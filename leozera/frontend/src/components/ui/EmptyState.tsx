import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-stone-300 bg-white px-6 py-10 text-center">
      <h2 className="text-lg font-semibold text-stone-950">{title}</h2>
      <div className="mx-auto mt-2 max-w-md text-sm text-stone-600">{children}</div>
    </div>
  );
}
