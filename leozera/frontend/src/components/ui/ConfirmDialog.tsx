"use client";

import { useEffect, useId, useRef } from "react";
import { primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  pending,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) {
      return;
    }
    if (open && !dialog.open) {
      dialog.showModal();
    }
    if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className="w-[min(100%,28rem)] rounded-2xl border border-stone-200 p-0 text-stone-900 backdrop:bg-stone-950/40"
      onClose={onCancel}
    >
      <form
        method="dialog"
        className="p-6"
        onSubmit={(event) => {
          event.preventDefault();
          onConfirm();
        }}
      >
        <h2 id={titleId} className="text-lg font-semibold text-stone-950">
          {title}
        </h2>
        <p className="mt-2 text-sm text-stone-600">{description}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
            Cancelar
          </button>
          <button type="submit" className={primaryButtonClass} disabled={pending}>
            {pending ? "Aguarde..." : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
