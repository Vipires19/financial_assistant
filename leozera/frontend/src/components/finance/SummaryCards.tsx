import { formatBrl, isNegativeMoney } from "@/lib/money";
import { formatDateBr, formatMonthLabel } from "@/lib/dates";
import type { Summary } from "@/lib/types";

export function SummaryCards({ summary }: { summary: Summary }) {
  const period = `${formatMonthLabel(summary.period_from)} · ${formatDateBr(summary.period_from)} a ${formatDateBr(summary.period_to)}`;
  const cards = [
    { label: "Saldo total", value: summary.total_balance, hint: "Posição atual de todas as contas" },
    { label: "Receitas do período", value: summary.period_income, hint: period },
    { label: "Despesas do período", value: summary.period_expense, hint: period },
    { label: "Resultado do período", value: summary.period_result, hint: "Receitas menos despesas" },
  ];

  return (
    <section aria-label="Indicadores" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <article key={card.label} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-medium text-stone-500">{card.label}</h2>
          <p
            className={`mt-3 text-2xl font-semibold tracking-tight ${
              isNegativeMoney(card.value) ? "text-rose-800" : "text-stone-950"
            }`}
          >
            {formatBrl(card.value)}
          </p>
          <p className="mt-2 text-sm text-stone-500">{card.hint}</p>
        </article>
      ))}
    </section>
  );
}
