export function StatusMessage({ message }: { message: string }) {
  if (!message) {
    return null;
  }
  return (
    <p role="status" className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
      {message}
    </p>
  );
}
