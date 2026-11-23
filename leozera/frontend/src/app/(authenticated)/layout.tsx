import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AppShell } from "@/components/layout/AppShell";
import type { PublicUser } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const session = cookieStore.get("leozera_session")?.value;
  if (!session) {
    redirect("/login");
  }

  const apiUrl = (process.env.API_URL ?? "http://backend:8000").replace(/\/$/, "");
  const response = await fetch(`${apiUrl}/auth/me`, {
    headers: { Cookie: `leozera_session=${session}` },
    cache: "no-store",
  });
  if (!response.ok) {
    redirect("/login");
  }

  const user = (await response.json()) as PublicUser;
  return <AppShell user={user}>{children}</AppShell>;
}
