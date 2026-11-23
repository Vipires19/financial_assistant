import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Leozera",
  description: "Gestão financeira pessoal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">{children}</body>
    </html>
  );
}
