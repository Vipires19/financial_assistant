"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { postAuth, type PublicUser } from "@/lib/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const result = await postAuth<PublicUser>("/api/auth/login", { email, password });
    if (!result.ok) {
      setError(result.message);
      setPending(false);
      return;
    }
    window.location.assign("/dashboard");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl items-center px-4 py-10">
      <section className="grid w-full items-center gap-10 md:grid-cols-2">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-emerald-800">Leozera</p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-stone-950">Entre na sua conta</h1>
          <p className="mt-4 max-w-md text-stone-600">O painel mostra apenas os dados da sessão autenticada.</p>
        </div>
        <form onSubmit={onSubmit} className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
          <label className="block text-sm font-medium text-stone-700" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-2 w-full rounded-xl border border-stone-300 px-3 py-2 outline-none ring-emerald-700 focus:ring-2"
          />
          <label className="mt-4 block text-sm font-medium text-stone-700" htmlFor="password">
            Senha
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full rounded-xl border border-stone-300 px-3 py-2 outline-none ring-emerald-700 focus:ring-2"
          />
          {error ? (
            <p role="alert" className="mt-4 text-sm text-red-700">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={pending}
            className="mt-6 w-full rounded-xl bg-emerald-800 px-4 py-2.5 font-medium text-white transition hover:bg-emerald-900 disabled:opacity-60"
          >
            {pending ? "Entrando..." : "Entrar"}
          </button>
          <p className="mt-4 text-sm text-stone-600">
            Ainda não tem conta?{" "}
            <Link href="/register" className="font-medium text-emerald-800">
              Criar conta
            </Link>
          </p>
        </form>
      </section>
    </main>
  );
}
