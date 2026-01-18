import { useEffect, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function App() {
  const [status, setStatus] = useState("checking...");

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch(`${API_BASE}/health`, {
          signal: controller.signal
        });
        if (!response.ok) {
          setStatus(`error ${response.status}`);
          return;
        }
        const data = await response.json();
        setStatus(data.status || "ok");
      } catch (error) {
        setStatus("unreachable");
      }
    }

    checkHealth();

    return () => controller.abort();
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-100 via-white to-cyan-100 text-slate-900">
      <div className="mx-auto flex min-h-screen max-w-4xl flex-col items-center justify-center px-6 text-center">
        <div className="rounded-3xl border border-slate-200 bg-white/70 p-10 shadow-lg backdrop-blur">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">ToPFeed</p>
          <h1 className="mt-4 font-display text-4xl font-semibold sm:text-5xl">
            ToPFeed running
          </h1>
          <p className="mt-3 text-base text-slate-600">
            Backend health: <span className="font-semibold text-slate-900">{status}</span>
          </p>
          <div className="mt-6 inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white">
            <span className="inline-flex h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            LLM-guided diversified feed
          </div>
          <p className="mt-6 text-xs text-slate-500">
            API base: {API_BASE}
          </p>
        </div>
      </div>
    </div>
  );
}
