"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Field, fieldErrorId } from "@/components/ui/Field";
import { StatusMessage } from "@/components/ui/StatusMessage";
import { inputClass, primaryButtonClass, secondaryButtonClass } from "@/components/ui/classes";
import { apiSend, redirectIfUnauthorized } from "@/lib/api";
import { listCategories } from "@/lib/finance";
import type { Category } from "@/lib/types";

export function CategoriesView() {
  const requestId = useRef(0);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<Category | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState<Category | null>(null);
  const [pendingArchive, setPendingArchive] = useState(false);

  const load = useCallback(async (initial: boolean) => {
    const request = ++requestId.current;
    if (initial) {
      setLoading(true);
    }
    const result = await listCategories(true);
    if (request !== requestId.current) {
      return;
    }
    if (!result.ok) {
      if (!result.aborted && !redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      setLoading(false);
      return;
    }
    setCategories(result.data);
    setError("");
    setLoading(false);
  }, []);

  useEffect(() => {
    void load(true);
    return () => {
      requestId.current += 1;
    };
  }, [load]);

  useEffect(() => {
    function onFocus() {
      void load(false);
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  async function archive(category: Category) {
    setPendingArchive(true);
    const result = await apiSend<Category>(`/api/categories/${category.id}/archive`, "POST");
    setPendingArchive(false);
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setConfirmArchive(null);
    setMessage("Categoria arquivada.");
    await load(false);
  }

  async function reactivate(category: Category) {
    const result = await apiSend<Category>(`/api/categories/${category.id}/reactivate`, "POST");
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setError(result.message);
      }
      return;
    }
    setMessage("Categoria reativada.");
    await load(false);
  }

  const custom = categories.filter((category) => !category.is_internal && category.archived_at === null);
  const archived = categories.filter((category) => !category.is_internal && category.archived_at !== null);
  const internal = categories.filter((category) => category.is_internal);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-stone-600">
          Crie as categorias que você usa no dia a dia. A categoria interna de ajuste não entra em receitas ou despesas.
        </p>
        <button
          type="button"
          className={primaryButtonClass}
          onClick={() => {
            setCreating(true);
            setEditing(null);
            setMessage("");
          }}
        >
          Nova categoria
        </button>
      </div>
      <StatusMessage message={message} />
      <ErrorBanner message={error} onRetry={() => void load(false)} />
      {creating || editing ? (
        <CategoryForm
          category={editing}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={async (text) => {
            setCreating(false);
            setEditing(null);
            setMessage(text);
            await load(false);
          }}
        />
      ) : null}
      {loading ? <p className="text-stone-600">Carregando categorias...</p> : null}
      {!loading && custom.length === 0 ? (
        <EmptyState title="Nenhuma categoria sua ainda">
          <p>Cadastre uma categoria, como Mercado ou Salário, para usá-la nos lançamentos.</p>
        </EmptyState>
      ) : null}
      <CategoryList
        title="Suas categorias"
        categories={custom}
        onEdit={setEditing}
        onArchive={setConfirmArchive}
      />
      <CategoryList title="Arquivadas" categories={archived} onReactivate={(category) => void reactivate(category)} />
      <CategoryList title="Uso interno" categories={internal} onEdit={setEditing} internal />
      <ConfirmDialog
        open={confirmArchive !== null}
        title="Arquivar categoria"
        description={
          confirmArchive
            ? `${confirmArchive.name} deixa de aparecer em novos lançamentos e continua identificável no histórico.`
            : ""
        }
        confirmLabel="Arquivar"
        pending={pendingArchive}
        onConfirm={() => {
          if (confirmArchive) {
            void archive(confirmArchive);
          }
        }}
        onCancel={() => {
          if (!pendingArchive) {
            setConfirmArchive(null);
          }
        }}
      />
    </div>
  );
}

function CategoryList({
  title,
  categories,
  onEdit,
  onArchive,
  onReactivate,
  internal = false,
}: {
  title: string;
  categories: Category[];
  onEdit?: (category: Category) => void;
  onArchive?: (category: Category) => void;
  onReactivate?: (category: Category) => void;
  internal?: boolean;
}) {
  if (categories.length === 0) {
    return null;
  }
  return (
    <section>
      <h2 className="text-base font-semibold text-stone-950">{title}</h2>
      <ul className="mt-3 grid gap-3">
        {categories.map((category) => (
          <li key={category.id} className="rounded-2xl border border-stone-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium text-stone-950">{category.name}</p>
                <p className="mt-1 text-sm text-stone-500">
                  {internal ? "Interna · usada somente em ajustes de saldo" : category.archived_at ? "Arquivada" : "Ativa"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {onEdit ? (
                  <button type="button" className={secondaryButtonClass} onClick={() => onEdit(category)}>
                    Renomear
                  </button>
                ) : null}
                {onArchive && !category.is_internal ? (
                  <button type="button" className={secondaryButtonClass} onClick={() => onArchive(category)}>
                    Arquivar
                  </button>
                ) : null}
                {onReactivate ? (
                  <button type="button" className={secondaryButtonClass} onClick={() => onReactivate(category)}>
                    Reativar
                  </button>
                ) : null}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CategoryForm({
  category,
  onCancel,
  onSaved,
}: {
  category: Category | null;
  onCancel: () => void;
  onSaved: (message: string) => void;
}) {
  const [name, setName] = useState(category?.name ?? "");
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) {
      return;
    }
    if (!name.trim()) {
      setError("Informe o nome da categoria.");
      return;
    }
    setError("");
    setPending(true);
    const result = category
      ? await apiSend<Category>(`/api/categories/${category.id}`, "PATCH", { name: name.trim() })
      : await apiSend<Category>("/api/categories", "POST", { name: name.trim() });
    if (!result.ok) {
      if (!redirectIfUnauthorized(result)) {
        setFormError(result.message);
        setPending(false);
      }
      return;
    }
    onSaved(category ? "Categoria atualizada." : "Categoria criada.");
  }

  return (
    <form onSubmit={onSubmit} className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{category ? "Renomear categoria" : "Nova categoria"}</h2>
      {category?.is_internal ? (
        <p className="mt-2 text-sm text-stone-600">O nome pode mudar. O uso interno e o bloqueio em receitas e despesas permanecem.</p>
      ) : null}
      <div className="mt-4 max-w-md">
        <Field id="category-name" label="Nome" error={error}>
          <input
            id="category-name"
            value={name}
            maxLength={80}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? fieldErrorId("category-name") : undefined}
            onChange={(event) => setName(event.target.value)}
            className={inputClass}
          />
        </Field>
      </div>
      {formError ? (
        <p role="alert" className="mt-4 text-sm text-red-700">
          {formError}
        </p>
      ) : null}
      <div className="mt-6 flex gap-3">
        <button type="submit" className={primaryButtonClass} disabled={pending}>
          {pending ? "Salvando..." : "Salvar categoria"}
        </button>
        <button type="button" className={secondaryButtonClass} onClick={onCancel} disabled={pending}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
