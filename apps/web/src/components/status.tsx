import { API_BASE_URL, isNotFound } from "@/lib/api";

const BOX =
  "rounded-lg border border-dashed border-zinc-200 px-4 py-10 text-center text-sm dark:border-zinc-800";

export function LoadingState({ label = "Loading…", className = "" }: { label?: string; className?: string }) {
  return (
    <div role="status" className={`${BOX} text-zinc-500 dark:text-zinc-400 ${className}`}>
      <span className="inline-block animate-pulse">{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  className = "",
}: {
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div className={`${BOX} ${className}`}>
      <p className="font-medium text-zinc-700 dark:text-zinc-300">{title}</p>
      {description ? <p className="mt-1 text-zinc-500 dark:text-zinc-400">{description}</p> : null}
    </div>
  );
}

export function ErrorState({
  title = "Couldn't load data",
  error,
  className = "",
}: {
  title?: string;
  error: unknown;
  className?: string;
}) {
  const detail = isNotFound(error)
    ? "The API returned 404 for this request."
    : error instanceof TypeError
      ? `Couldn't reach the API at ${API_BASE_URL}.`
      : error instanceof Error
        ? error.message
        : "Unknown error";
  return (
    <div
      role="alert"
      className={`rounded-lg border border-red-200 bg-red-50 px-4 py-6 text-center text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300 ${className}`}
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-red-600/80 dark:text-red-300/70">{detail}</p>
    </div>
  );
}
