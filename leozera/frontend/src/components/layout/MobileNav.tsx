"use client";

import { useEffect, useId, useRef, useState } from "react";
import { SideNav } from "@/components/layout/SideNav";

export function MobileNav() {
  const [open, setOpen] = useState(false);
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
    <>
      <button
        type="button"
        className="rounded-xl border border-stone-300 px-3 py-2 text-sm font-medium text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800 md:hidden"
        aria-expanded={open}
        aria-controls="mobile-navigation"
        onClick={() => setOpen(true)}
      >
        Menu
      </button>
      <dialog
        id="mobile-navigation"
        ref={ref}
        aria-labelledby={titleId}
        className="m-0 mt-0 h-full max-h-none w-[min(100%,18rem)] rounded-none border-r border-stone-200 p-0 backdrop:bg-stone-950/40 md:hidden"
        onClose={() => setOpen(false)}
      >
        <div className="flex items-center justify-between border-b border-stone-200 px-4 py-4">
          <p id={titleId} className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Leozera
          </p>
          <button
            type="button"
            className="rounded-lg px-2 py-1 text-sm text-stone-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800"
            onClick={() => setOpen(false)}
          >
            Fechar
          </button>
        </div>
        <div className="p-3">
          <SideNav onNavigate={() => setOpen(false)} />
        </div>
      </dialog>
    </>
  );
}
