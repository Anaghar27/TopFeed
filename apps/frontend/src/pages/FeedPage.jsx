import { useEffect, useMemo, useState } from "react";
import FeedCard from "../components/FeedCard";
import WhyThisDrawer from "../components/WhyThisDrawer";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function FeedPage() {
  const [userId, setUserId] = useState("U483745");
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

  const payload = useMemo(
    () => ({
      user_id: userId,
      top_n: 30,
      history_k: 50,
      diversify: true,
      explore_level: exploreLevel,
      include_explanations: true
    }),
    [userId, exploreLevel]
  );

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("topfeed-theme", theme);
  }, [theme]);

  useEffect(() => {
    let alive = true;

    async function fetchFeed() {
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
        }
      } catch (error) {
        if (alive) {
          setStatus("error");
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

  async function handlePrefer(item) {
    const isPreferred = Boolean(item.is_preferred);
    const action = isPreferred ? "unprefer" : "prefer";

    setItems((prev) =>
      prev.map((entry) => {
        if (entry.news_id !== item.news_id) return entry;
        return {
          ...entry,
          is_preferred: action === "prefer"
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
            is_preferred: true
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
      setMessage(action === "prefer" ? "Saved to preferences" : "Removed from preferences");
      setTimeout(() => setMessage(""), 2000);
    } catch (error) {
      setMessage("Could not update preference");
      setTimeout(() => setMessage(""), 2000);
    }
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
            <p className="mt-1 text-sm text-[color:var(--muted)]">
              {activeView === "feed" ? `status: ${status}` : `saved topics for ${userId}`}
            </p>
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
                onChange={(event) => setUserId(event.target.value.trim())}
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

        {activeView === "feed" && loading && (
          <div className="mt-8 rounded-2xl border border-dashed border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-6 text-center text-sm text-[color:var(--muted)]">
            Building your feed...
          </div>
        )}

        {activeView === "feed" && !loading && (
          <div className="mt-8 grid gap-6">
            {items.map((item) => (
              <FeedCard
                key={item.news_id}
                item={item}
                onWhy={setActiveItem}
                onPreview={setPreviewItem}
                onPrefer={handlePrefer}
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
              <div className="grid gap-6 md:grid-cols-2">
                {preferredItems.map((item) => (
                  <FeedCard
                    key={`preferred-${item.news_id}`}
                    item={{ ...item, is_preferred: true }}
                    onWhy={setActiveItem}
                    onPreview={setPreviewItem}
                    onPrefer={handlePrefer}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <WhyThisDrawer item={activeItem} open={Boolean(activeItem)} onClose={() => setActiveItem(null)} />
      {previewItem && (
        <div className="fixed inset-0 z-40 flex">
          <div className="absolute inset-0 bg-black/60" onClick={() => setPreviewItem(null)} />
          <div className="relative ml-auto h-full w-full max-w-lg bg-[color:var(--panel-bg)] p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-[color:var(--text)]">Article preview</h2>
              <button
                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={() => setPreviewItem(null)}
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
