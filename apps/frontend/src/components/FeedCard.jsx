export default function FeedCard({ item, onWhy, onPreview, onPrefer, onRead }) {
  const isPreference = Boolean(item.is_preferred);
  const isUnderexplored =
    Boolean(item.is_new_interest) ||
    (isPreference && item.explanation?.reason_tags?.includes("underexplored_interest"));
  const hasPublicLink = Boolean(item.url) && item.content_type === "fresh";

  return (
    <div className="rounded-2xl border border-[color:var(--card-border)] bg-[color:var(--card-bg)] p-5 shadow-[0_12px_40px_rgba(0,0,0,0.15)] transition hover:shadow-[0_18px_60px_rgba(0,0,0,0.25)]">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
            {item.category || "uncategorized"}
            {item.subcategory ? ` • ${item.subcategory}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-[color:var(--text)]">{item.title || "Untitled"}</h3>
            {isUnderexplored && (
              <span className="inline-flex items-center gap-2 rounded-full bg-[color:var(--new-bg)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-[color:var(--new-text)]">
                new interest
                <span className="normal-case tracking-normal text-[10px] text-[color:var(--new-text)]/80">
                  {item.category || "uncategorized"}
                  {item.subcategory ? `/${item.subcategory}` : ""}
                </span>
              </span>
            )}
          </div>
          {item.abstract && (
            <p className="mt-2 text-sm text-[color:var(--muted)] line-clamp-3">{item.abstract}</p>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <button
            className={
              isPreference
                ? "inline-flex h-7 w-7 items-center justify-center rounded-full bg-[color:var(--heart-fill)] text-white shadow-[0_0_0_2px_rgba(224,107,107,0.2)] hover:brightness-110"
                : "inline-flex h-7 w-7 items-center justify-center rounded-full border border-[color:var(--heart-border)] bg-transparent text-[color:var(--heart-border)] hover:bg-[color:var(--heart-bg)]"
            }
            title={isPreference ? "Remove preference" : "Save to preferences"}
            aria-pressed={isPreference}
            onClick={() => onPrefer(item)}
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill={isPreference ? "currentColor" : "none"}
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20.8 4.6c-1.8-1.8-4.8-1.8-6.6 0L12 6.8l-2.2-2.2c-1.8-1.8-4.8-1.8-6.6 0-1.8 1.8-1.8 4.8 0 6.6L12 20l8.8-8.8c1.8-1.8 1.8-4.8 0-6.6Z" />
            </svg>
          </button>
          <button
            className="shrink-0 rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
            onClick={() => onWhy(item)}
          >
            Why this?
          </button>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-[color:var(--muted)]">
        <button
          className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)] hover:brightness-105"
          onClick={() => onPreview(item)}
        >
          preview
        </button>
        {hasPublicLink ? (
          <a
            className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)] hover:brightness-105"
            href={item.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => onRead?.(item)}
          >
            read full article
          </a>
        ) : (
          <span
            className="cursor-not-allowed rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)]"
            title="Full article not available for dataset items."
          >
            Not available
          </span>
        )}
      </div>
    </div>
  );
}
