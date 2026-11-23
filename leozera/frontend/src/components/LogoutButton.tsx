"use client";

import { useState } from "react";
import { secondaryButtonClass } from "@/components/ui/classes";
import { readCookie } from "@/lib/api";

export function LogoutButton() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function logout() {
    setPending(true);
    setError("");
    const csrf = readCookie("leozera_csrf");
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: csrf ? { "X-CSRF-Token": csrf } : {},
      });
      if (!response.ok) {
        setError("Não foi possível encerrar a sessão.");
        setPending(false);
        return;
      }
      window.location.assign("/login");
    } catch {
      setError("Não foi possível encerrar a sessão.");
      setPending(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      {error ? <span className="text-sm text-red-700">{error}</span> : null}
      <button
        type="button"
        onClick={logout}
        disabled={pending}
        className={secondaryButtonClass}
      >
        {pending ? "Saindo..." : "Sair"}
      </button>
    </div>
  );
}
