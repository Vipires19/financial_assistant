import { Suspense } from "react";
import { PayablesView } from "@/components/finance/PayablesView";

export default function PayablesPage() {
  return (
    <Suspense fallback={<p className="text-stone-600">Carregando contas a pagar...</p>}>
      <PayablesView />
    </Suspense>
  );
}
