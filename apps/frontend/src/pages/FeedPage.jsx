import { useEffect, useMemo, useRef, useState } from "react";
import FeedCard from "../components/FeedCard";
import WhyThisDrawer from "../components/WhyThisDrawer";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function FeedPage() {
  const [userId, setUserId] = useState(
    () => localStorage.getItem("topfeed-user-id") || "U483745"
  );
  const [exploreLevel, setExploreLevel] = useState(0.6);
  const [theme, setTheme] = useState(() => localStorage.getItem("topfeed-theme") || "light");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("idle");
  const [activeView, setActiveView] = useState("feed");
  const [preferredItems, setPreferredItems] = useState([]);
  const [preferredLoading, setPreferredLoading] = useState(false);
  const [activeItem, setActiveItem] = useState(null);
  const [previewItem, setPreviewItem] = useState(null);
  const [message, setMessage] = useState("");
  const [loadMs, setLoadMs] = useState(null);
  const [requestId, setRequestId] = useState(null);
  const [modelVersion, setModelVersion] = useState(null);
  const [feedMethod, setFeedMethod] = useState(null);
  const [userMetrics, setUserMetrics] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const lastLoggedRequest = useRef(null);
  const previewStart = useRef(null);
  const preferredByCategory = useMemo(() => {
    const grouped = {};
    for (const item of preferredItems) {
      const key = item.category || "uncategorized";
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    }
    return Object.entries(grouped).sort((a, b) => b[1].length - a[1].length);
  }, [preferredItems]);

  const preferredCountsByPath = useMemo(() => {
    const counts = {};
    for (const item of preferredItems) {
      const category = item.category || "uncategorized";
      const subcategory = item.subcategory || "";
      const path = subcategory ? `${category}/${subcategory}` : category;
      counts[path] = (counts[path] || 0) + 1;
    }
    return counts;
  }, [preferredItems]);

  const resolvedUserId = userId.trim() || "U483745";

  const payload = useMemo(
    () => ({
      user_id: resolvedUserId,
      top_n: 50,
      history_k: 50,
      diversify: true,
      explore_level: exploreLevel,
      include_explanations: false
    }),
    [resolvedUserId, exploreLevel]
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("topfeed-theme", theme);
  }, [theme]);

  useEffect(() => {
    const trimmed = userId.trim();
    if (trimmed) {
      localStorage.setItem("topfeed-user-id", trimmed);
    }
  }, [userId]);

  useEffect(() => {
    let alive = true;

    async function fetchFeed() {
      const startedAt = performance.now();
      setLoading(true);
      setStatus("loading");
      try {
        const response = await fetch(`${API_BASE}/feed`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const data = await response.json();
        if (alive) {
          setItems(data.items || []);
          setStatus(data.method || "ok");
          setFeedMethod(data.method || null);
          setRequestId(data.request_id || null);
          setModelVersion(data.model_version || null);
          setPage(1);
          setLoadMs(Math.round(performance.now() - startedAt));
        }
      } catch (error) {
        if (alive) {
          setStatus("error");
          setLoadMs(null);
        }
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    }

    fetchFeed();
    return () => {
      alive = false;
    };
  }, [payload]);

  useEffect(() => {
    let alive = true;

    async function fetchMetrics() {
      setMetricsLoading(true);
      try {
        const response = await fetch(
          `${API_BASE}/metrics/summary?days=14&user_id=${encodeURIComponent(resolvedUserId)}`
        );
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const data = await response.json();
        if (alive) {
          setUserMetrics(data);
        }
      } catch (error) {
        if (alive) {
          setUserMetrics(null);
        }
      } finally {
        if (alive) {
          setMetricsLoading(false);
        }
      }
    }

    if (activeView === "feed") {
      fetchMetrics();
    }
    return () => {
      alive = false;
    };
  }, [resolvedUserId, activeView]);

  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const pagedItems = items.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    let alive = true;

    async function fetchPreferred() {
      setPreferredLoading(true);
      try {
        const response = await fetch(`${API_BASE}/users/${userId}/preferred?limit=100`);
        if (!response.ok) {
          throw new Error(`status ${response.status}`);
        }
        const data = await response.json();
        if (alive) {
          setPreferredItems(data.items || []);
        }
      } catch (error) {
        if (alive) {
          setPreferredItems([]);
        }
      } finally {
        if (alive) {
          setPreferredLoading(false);
        }
      }
    }

    if (activeView === "preferred") {
      fetchPreferred();
    }
    return () => {
      alive = false;
    };
  }, [userId, activeView]);

  async function postEvents(events) {
    if (!events.length) return;
    try {
      await fetch(`${API_BASE}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(events)
      });
    } catch (error) {
      // Best-effort logging; no UI impact.
    }
  }

  useEffect(() => {
    if (activeView !== "feed") return;
    if (!requestId || !items.length) return;
    if (lastLoggedRequest.current === requestId) return;
    lastLoggedRequest.current = requestId;
    const events = items.map((item, index) => ({
      user_id: userId,
      event_type: "impression",
      news_id: item.news_id,
      request_id: requestId,
      model_version: modelVersion,
      method: feedMethod,
      position: index + 1,
      explore_level: exploreLevel,
      diversify: true
    }));
    postEvents(events);
  }, [activeView, items, requestId, modelVersion, feedMethod, exploreLevel, userId]);

  async function handleWhy(item) {
    if (item.explanation) {
      setActiveItem(item);
      return;
    }
    setActiveItem({ ...item, explanation: null });
    const scoreContext = (() => {
      if (!items.length) return null;
      const relVals = [];
      const topVals = [];
      const repVals = [];
      const covVals = [];
      for (const entry of items) {
        const rel = Number.isFinite(entry.rel_score) ? entry.rel_score : entry.score || 0;
        relVals.push(rel);
        topVals.push(Number.isFinite(entry.top_bonus) ? entry.top_bonus : 0);
        repVals.push(Number.isFinite(entry.redundancy_penalty) ? entry.redundancy_penalty : 0);
        covVals.push(Number.isFinite(entry.coverage_gain) ? entry.coverage_gain : 0);
      }
      const minMax = (values) => {
        let min = Infinity;
        let max = -Infinity;
        for (const value of values) {
          if (value < min) min = value;
          if (value > max) max = value;
        }
        if (min === Infinity || max === -Infinity) {
          return { min: 0, max: 1 };
        }
        return { min, max };
      };
      const rel = minMax(relVals);
      const top = minMax(topVals);
      const rep = minMax(repVals);
      const cov = minMax(covVals);
      return {
        rel_min: rel.min,
        rel_max: rel.max,
        top_min: top.min,
        top_max: top.max,
        rep_min: rep.min,
        rep_max: rep.max,
        cov_min: cov.min,
        cov_max: cov.max
      };
    })();
    try {
      const response = await fetch(`${API_BASE}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          item,
          method: status === "personalized_top_diversified" ? status : status === "popular_fallback" ? status : "rerank_only",
          score_context: scoreContext
        })
      });
      if (!response.ok) {
        throw new Error("explain failed");
      }
      const data = await response.json();
      const explainedItem = { ...(data.item || item), is_preferred: item.is_preferred };
      setItems((prev) =>
        prev.map((entry) => (entry.news_id === explainedItem.news_id ? explainedItem : entry))
      );
      setActiveItem(explainedItem);
    } catch (error) {
      setMessage("Could not load explanation");
      setTimeout(() => setMessage(""), 2000);
    }
  }

  async function handlePrefer(item) {
    const isPreferred = Boolean(item.is_preferred);
    const action = isPreferred ? "unprefer" : "prefer";
    const category = item.category || "uncategorized";
    const subcategory = item.subcategory || "";
    const path = subcategory ? `${category}/${subcategory}` : category;
    const currentCount = preferredCountsByPath[path] || 0;
    const nextCount = action === "prefer" ? currentCount + 1 : Math.max(currentCount - 1, 0);
    const isNewInterest = action === "prefer" && nextCount < 5;

    setItems((prev) =>
      prev.map((entry) => {
        if (entry.news_id !== item.news_id) return entry;
        return {
          ...entry,
          is_preferred: action === "prefer",
          is_new_interest: isNewInterest
        };
      })
    );

    setPreferredItems((prev) => {
      if (action === "prefer") {
        if (prev.some((entry) => entry.news_id === item.news_id)) {
          return prev.map((entry) =>
            entry.news_id === item.news_id ? { ...entry, is_preferred: true } : entry
          );
        }
        return [
          {
            news_id: item.news_id,
            title: item.title,
            abstract: item.abstract,
            category: item.category,
            subcategory: item.subcategory,
            url: item.url,
            is_preferred: true,
            is_new_interest: isNewInterest
          },
          ...prev
        ];
      }
      return prev.filter((entry) => entry.news_id !== item.news_id);
    });

    try {
      const response = await fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          news_id: item.news_id,
          action,
          split: "live"
        })
      });
      if (!response.ok) {
        throw new Error("feedback failed");
      }
      if (requestId) {
        postEvents([
          {
            user_id: userId,
            event_type: action === "prefer" ? "save" : "hide",
            news_id: item.news_id,
            request_id: requestId,
            model_version: modelVersion,
            method: feedMethod,
            position: items.findIndex((entry) => entry.news_id === item.news_id) + 1 || null,
            explore_level: exploreLevel,
            diversify: true
          }
        ]);
      }
      setMessage(action === "prefer" ? "Saved to preferences" : "Removed from preferences");
      setTimeout(() => setMessage(""), 2000);
    } catch (error) {
      setMessage("Could not update preference");
      setTimeout(() => setMessage(""), 2000);
    }
  }

  function handleRead(item) {
    if (!requestId) return;
    postEvents([
      {
        user_id: userId,
        event_type: "click",
        news_id: item.news_id,
        request_id: requestId,
        model_version: modelVersion,
        method: feedMethod,
        position: items.findIndex((entry) => entry.news_id === item.news_id) + 1 || null,
        explore_level: exploreLevel,
        diversify: true,
        metadata: { source: "article" }
      }
    ]);
  }

  function handlePreviewOpen(item) {
    previewStart.current = Date.now();
    setPreviewItem(item);
    if (requestId) {
      postEvents([
        {
          user_id: userId,
          event_type: "click",
          news_id: item.news_id,
          request_id: requestId,
          model_version: modelVersion,
          method: feedMethod,
          position: items.findIndex((entry) => entry.news_id === item.news_id) + 1 || null,
          explore_level: exploreLevel,
          diversify: true,
          metadata: { source: "preview" }
        }
      ]);
    }
  }

  function handlePreviewClose() {
    if (previewItem && previewStart.current && requestId) {
      const dwellMs = Math.max(Date.now() - previewStart.current, 0);
      postEvents([
        {
          user_id: userId,
          event_type: "dwell",
          news_id: previewItem.news_id,
          request_id: requestId,
          model_version: modelVersion,
          method: feedMethod,
          position: items.findIndex((entry) => entry.news_id === previewItem.news_id) + 1 || null,
          explore_level: exploreLevel,
          diversify: true,
          dwell_ms: dwellMs,
          metadata: { source: "preview" }
        }
      ]);
    }
    previewStart.current = null;
    setPreviewItem(null);
  }

  return (
    <div
      className="min-h-screen"
      style={{
        background: "radial-gradient(circle at top, var(--bg-accent), var(--bg) 45%, var(--bg) 100%)"
      }}
    >
      <div className="mx-auto w-full max-w-5xl px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border border-[color:var(--panel-border)] bg-[color:var(--panel-bg)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.15)]">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">ToPFeed</p>
            <h1 className="mt-2 text-3xl font-semibold text-[color:var(--text)]">
              {activeView === "feed" ? "Personalized feed" : "Preferred list"}
            </h1>
            {activeView === "feed" && loadMs !== null && (
              <p className="mt-2 text-xs font-semibold text-[color:var(--muted)]">
                load time: {loadMs} ms
              </p>
            )}
            <div className="mt-3 flex gap-2 text-xs font-semibold">
              <button
                className={
                  activeView === "feed"
                    ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                    : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                }
                onClick={() => setActiveView("feed")}
              >
                Feed
              </button>
              <button
                className={
                  activeView === "preferred"
                    ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                    : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                }
                onClick={() => setActiveView("preferred")}
              >
                Preferences
              </button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-3 shadow-sm">
            <label className="text-xs font-semibold text-[color:var(--muted)]">
              User
              <input
                className="mt-1 w-40 rounded-lg border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-2 py-1 text-sm text-[color:var(--text)] focus:border-[color:var(--accent-strong)] focus:outline-none"
                value={userId}
                onChange={(event) => setUserId(event.target.value)}
              />
            </label>
            {activeView === "feed" && (
              <div className="text-xs font-semibold text-[color:var(--muted)]">
                <div className="flex items-center justify-between">
                  <span>Explore vs relevance</span>
                  <span className="text-[color:var(--accent)]">{exploreLevel.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={exploreLevel}
                  onChange={(event) => setExploreLevel(Number(event.target.value))}
                  className="mt-2 w-40 accent-[color:var(--accent-strong)]"
                />
                <div className="mt-1 flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  <span>Focus</span>
                  <span>Explore</span>
                </div>
              </div>
            )}
            {activeView === "feed" && (
              <span className="text-xs font-semibold text-[color:var(--muted)]">
                {exploreLevel < 0.4 ? "relevance-first" : exploreLevel < 0.7 ? "balanced" : "exploration-heavy"}
              </span>
            )}
            <button
              className="relative flex h-7 w-16 items-center rounded-full border border-[color:var(--panel-border)] bg-[color:var(--chip-bg)] px-1 text-xs font-semibold text-[color:var(--muted)]"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label="Toggle theme"
            >
              <span className="absolute left-2 text-[11px]">☀</span>
              <span className="absolute right-2 text-[11px]">☾</span>
              <span
                className={`h-5 w-5 rounded-full bg-[color:var(--accent-strong)] shadow transition-transform ${
                  theme === "dark" ? "translate-x-9" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        </div>

        {activeView === "feed" && (
          <div className="mt-6 rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] px-5 py-4 text-xs text-[color:var(--muted)]">
            {metricsLoading && <span>Loading your metrics...</span>}
            {!metricsLoading && userMetrics?.totals && (
              <div className="flex flex-wrap items-center gap-4">
                <span className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)]">
                  impressions {userMetrics.totals.impressions}
                </span>
                <span className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)]">
                  clicks {userMetrics.totals.clicks}
                </span>
                <span className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)]">
                  ctr {(userMetrics.totals.ctr || 0).toFixed(3)}
                </span>
                {userMetrics.series?.length ? (
                  <span className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-[color:var(--chip-text)]">
                    avg dwell {(userMetrics.series[userMetrics.series.length - 1].avg_dwell_ms || 0).toFixed(0)} ms
                  </span>
                ) : null}
                <span className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                  last 14 days
                </span>
              </div>
            )}
            {!metricsLoading && !userMetrics?.totals && (
              <span>No user metrics yet. Interact with the feed to generate events.</span>
            )}
          </div>
        )}

        {activeView === "feed" && loading && (
          <div className="mt-8 rounded-2xl border border-dashed border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-6 text-center text-sm text-[color:var(--muted)]">
            Building your feed...
          </div>
        )}

        {activeView === "feed" && !loading && (
          <div className="mt-8 grid gap-6">
            {pagedItems.map((item) => (
              <FeedCard
                key={item.news_id}
                item={item}
                onWhy={handleWhy}
                onPreview={handlePreviewOpen}
                onPrefer={handlePrefer}
                onRead={handleRead}
              />
            ))}
          </div>
        )}

        {activeView === "preferred" && (
          <div className="mt-8">
            {preferredLoading && (
              <div className="rounded-2xl border border-dashed border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-6 text-center text-sm text-[color:var(--muted)]">
                Loading preferred items...
              </div>
            )}
            {!preferredLoading && preferredItems.length === 0 && (
              <div className="rounded-2xl border border-dashed border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-6 text-center text-sm text-[color:var(--muted)]">
                No preferred items yet. Tap the heart to save a topic.
              </div>
            )}
            {!preferredLoading && preferredItems.length > 0 && (
              <div className="grid gap-8">
                {preferredByCategory.map(([category, group]) => (
                  <div key={category} className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-[color:var(--accent)]">
                          {String(category).toUpperCase()}
                        </p>
                      </div>
                      <span className="rounded-full bg-[color:var(--chip-bg)] px-3 py-1 text-xs font-semibold text-[color:var(--chip-text)]">
                        {group.length} items
                      </span>
                    </div>
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      {group.map((item) => (
                        <FeedCard
                          key={`preferred-${item.news_id}`}
                          item={{ ...item, is_preferred: true }}
                          onWhy={handleWhy}
                          onPreview={handlePreviewOpen}
                          onPrefer={handlePrefer}
                          onRead={handleRead}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeView === "feed" && totalPages > 1 && !loading && (
          <div className="mt-10 flex flex-wrap items-center justify-center gap-2">
            {Array.from({ length: totalPages }, (_, idx) => idx + 1).map((num) => (
              <button
                key={`page-${num}`}
                className={
                  num === page
                    ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-xs font-semibold text-[color:var(--text)]"
                    : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                }
                onClick={() => setPage(num)}
              >
                {num}
              </button>
            ))}
          </div>
        )}
      </div>

      <WhyThisDrawer item={activeItem} open={Boolean(activeItem)} onClose={() => setActiveItem(null)} />
      {previewItem && (
        <div className="fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/60" onClick={handlePreviewClose} />
          <div className="relative ml-auto h-full w-full max-w-lg bg-[color:var(--panel-bg)] p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-[color:var(--text)]">Article preview</h2>
              <button
                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={handlePreviewClose}
              >
                Close
              </button>
            </div>
            <p className="mt-4 text-xs uppercase tracking-[0.2em] text-[color:var(--muted)]">
              {previewItem.category || "uncategorized"}
              {previewItem.subcategory ? ` • ${previewItem.subcategory}` : ""}
            </p>
            <h3 className="mt-3 text-xl font-semibold text-[color:var(--text)]">
              {previewItem.title || "Untitled"}
            </h3>
            <p className="mt-4 text-sm text-[color:var(--muted)] whitespace-pre-line">
              {previewItem.abstract || "No abstract available for this item."}
            </p>
            <div className="mt-6 flex flex-wrap gap-2 text-xs text-[color:var(--muted)]">
              {previewItem.url ? (
                <a
                  className="rounded-full bg-[color:var(--accent-strong)] px-4 py-2 text-xs font-semibold text-[color:var(--text)] hover:brightness-110"
                  href={previewItem.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  read full article
                </a>
              ) : (
                <span className="rounded-full bg-[color:var(--chip-bg)] px-4 py-2 text-[color:var(--chip-text)]">
                  no article link available
                </span>
              )}
            </div>
          </div>
        </div>
      )}
      {message && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-[color:var(--accent-strong)] px-4 py-2 text-xs font-semibold text-[color:var(--text)] shadow-lg">
          {message}
        </div>
      )}
    </div>
  );
}
