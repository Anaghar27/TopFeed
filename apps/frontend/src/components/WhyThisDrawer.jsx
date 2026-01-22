const tagStyles = {
  relevant_to_you: "bg-[color:var(--chip-bg)] text-[color:var(--chip-text)]",
  underexplored_interest: "bg-[color:var(--new-bg)] text-[color:var(--new-text)]",
  adds_topic_variety: "bg-[color:var(--panel-border)] text-[color:var(--text)]",
  reduces_repetition: "bg-[color:var(--heart-bg)] text-[color:var(--heart-border)]",
  popular_fallback: "bg-[color:var(--panel-border)] text-[color:var(--text)]"
};

function ProgressRow({ label, value }) {
  const safeValue = Number.isFinite(value) ? value : 0;
  const width = Math.round(safeValue * 100);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-[color:var(--muted)]">
        <span>{label}</span>
        <span>
          {safeValue.toFixed(4)} ({width}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-[color:var(--panel-border)]">
        <div
          className="h-2 rounded-full bg-[color:var(--accent-strong)]"
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export default function WhyThisDrawer({ item, open, onClose }) {
  if (!open || !item) return null;

  const explanation = item.explanation;
  const evidence = explanation?.evidence || {};
  const breakdown = explanation?.score_breakdown || {};

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative ml-auto h-full w-full max-w-md bg-[color:var(--panel-bg)] p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[color:var(--text)]">Why this?</h2>
          <button
            className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        {!explanation && (
          <p className="mt-4 text-sm text-[color:var(--muted)]">Loading explanation...</p>
        )}
        {explanation && (
          <p className="mt-4 text-sm text-[color:var(--muted)]">{explanation.top_path || "Unknown topic"}</p>
        )}

        {explanation && (
          <div className="mt-3 flex flex-wrap gap-2">
            {(explanation.reason_tags || []).map((tag) => (
              <span
                key={tag}
                className={`rounded-full px-3 py-1 text-xs font-semibold ${tagStyles[tag] || "bg-[color:var(--chip-bg)] text-[color:var(--chip-text)]"}`}
              >
                {tag.replaceAll("_", " ")}
              </span>
            ))}
          </div>
        )}

        {explanation && (
          <div className="mt-6 space-y-4">
            <ProgressRow label="relevance" value={breakdown.rel_score_norm} />
            <ProgressRow label="underexplored bonus" value={breakdown.top_bonus_norm} />
            <ProgressRow label="coverage gain" value={breakdown.coverage_gain_norm} />
            <ProgressRow label="repetition penalty" value={breakdown.redundancy_penalty_norm} />
          </div>
        )}

        {explanation && (
          <>
            <div className="mt-6 rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-4 text-sm text-[color:var(--muted)]">
              <p className="font-semibold text-[color:var(--text)]">Evidence</p>
              {evidence.recent_clicks_used?.length ? (
                <div className="mt-3 space-y-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    You recently clicked
                  </p>
                  {evidence.recent_clicks_used.map((click) => (
                    <p key={click.news_id} className="text-sm text-[color:var(--text)]">
                      {click.title || click.news_id}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-500">No recent clicks available.</p>
              )}

              {evidence.top_node_stats && (
                <div className="mt-4">
                  <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">ToP signals</p>
                  <p className="mt-2 text-sm text-[color:var(--text)]">
                    clicks: {evidence.top_node_stats.clicks}, exposures: {evidence.top_node_stats.exposures}
                  </p>
                  <p className="text-sm text-[color:var(--text)]">
                    underexplored score: {evidence.top_node_stats.underexplored_score?.toFixed?.(3)}
                  </p>
                </div>
              )}
            </div>

            <div className="mt-4 text-xs text-[color:var(--muted)]">
              method: {explanation.method || "unknown"}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
