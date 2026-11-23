"use client";

import { createContext, useContext } from "react";
import { usePathname } from "next/navigation";
import { LogoutButton } from "@/components/LogoutButton";
import { MobileNav } from "@/components/layout/MobileNav";
import { pageTitle } from "@/components/layout/navigation";
import { SideNav } from "@/components/layout/SideNav";
import type { PublicUser } from "@/lib/types";

const UserContext = createContext<PublicUser | null>(null);

export function CurrentUserProvider({ user, children }: { user: PublicUser; children: React.ReactNode }) {
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function useCurrentUser(): PublicUser {
  const user = useContext(UserContext);
  if (!user) {
    throw new Error("Usuário autenticado indisponível.");
  }
  return user;
}

export function AppShell({ user, children }: { user: PublicUser; children: React.ReactNode }) {
  const pathname = usePathname();
  const title = pageTitle(pathname);

  return (
    <CurrentUserProvider user={user}>
      <div className="min-h-screen bg-stone-50 text-stone-900">
        <a
          href="#conteudo"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-3 focus:py-2"
        >
          Ir para o conteúdo
        </a>
        <div className="md:grid md:grid-cols-[13.5rem_minmax(0,1fr)] lg:grid-cols-[15rem_minmax(0,1fr)]">
          <aside className="hidden border-r border-stone-200 bg-white md:flex md:min-h-screen md:flex-col md:px-3 md:py-6">
            <p className="px-3 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-800">Leozera</p>
            <div className="mt-8">
              <SideNav />
            </div>
          </aside>
          <div className="min-w-0">
            <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-stone-200 bg-white/95 px-4 py-3 backdrop-blur">
              <div className="flex min-w-0 items-center gap-3">
                <MobileNav />
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800 md:hidden">Leozera</p>
                  <h1 className="truncate text-lg font-semibold text-stone-950">{title}</h1>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="hidden max-w-40 truncate text-sm text-stone-600 sm:inline">{user.name}</span>
                <LogoutButton />
              </div>
            </header>
            <main id="conteudo" className="mx-auto w-full max-w-6xl px-4 py-6">
              {children}
            </main>
          </div>
        </div>
      </div>
    </CurrentUserProvider>
  );
}
