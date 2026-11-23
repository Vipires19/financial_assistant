export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  if (!message) {
    return null;
  }
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <p>{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="font-medium underline underline-offset-2">
          Tentar de novo
        </button>
      ) : null}
    </div>
  );
}
