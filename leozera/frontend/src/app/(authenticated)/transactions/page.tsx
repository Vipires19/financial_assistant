import { Suspense } from "react";
import { TransactionsView } from "@/components/finance/TransactionsView";

export default function TransactionsPage() {
  return (
    <Suspense fallback={<p className="text-stone-600">Carregando movimentações...</p>}>
      <TransactionsView />
    </Suspense>
  );
}
