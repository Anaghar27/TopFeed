import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const EVENT_TYPES = ["impression", "click", "hide", "save", "dwell"];

export default function AdminPage({ onBack }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState("request");
  const [status, setStatus] = useState(null);
  const [token, setToken] = useState(null);
  const [expiresAt, setExpiresAt] = useState(null);
  const [users, setUsers] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventUserId, setEventUserId] = useState("");
  const [eventType, setEventType] = useState("");
  const [updateUserId, setUpdateUserId] = useState("");
  const [updateEmail, setUpdateEmail] = useState("");
  const [updatePassword, setUpdatePassword] = useState("");
  const [showUpdatePassword, setShowUpdatePassword] = useState(false);
  const [updateFullName, setUpdateFullName] = useState("");
  const [updateStatus, setUpdateStatus] = useState(null);

  const passwordRules = useMemo(
    () => [
      { id: "len", label: "At least 8 characters", test: (value) => value.length >= 8 },
      { id: "upper", label: "One uppercase letter (A-Z)", test: (value) => /[A-Z]/.test(value) },
      { id: "lower", label: "One lowercase letter (a-z)", test: (value) => /[a-z]/.test(value) },
      { id: "digit", label: "One number (0-9)", test: (value) => /\d/.test(value) },
      { id: "symbol", label: "One symbol (!@#$...)", test: (value) => /[^A-Za-z0-9]/.test(value) }
    ],
    []
  );
  const updatePasswordChecks = useMemo(() => {
    const checks = {};
    for (const rule of passwordRules) {
      checks[rule.id] = rule.test(updatePassword);
    }
    return checks;
  }, [passwordRules, updatePassword]);

  useEffect(() => {
    const storedToken = localStorage.getItem("topfeed-admin-token");
    const storedExpires = localStorage.getItem("topfeed-admin-expires");
    if (!storedToken || !storedExpires) return;
    const parsed = new Date(storedExpires);
    if (Number.isNaN(parsed.getTime())) return;
    if (parsed.getTime() <= Date.now()) {
      localStorage.removeItem("topfeed-admin-token");
      localStorage.removeItem("topfeed-admin-expires");
      return;
    }
    setToken(storedToken);
    setExpiresAt(parsed.toISOString());
  }, []);

  const canRequestOtp = useMemo(() => email.trim().length > 0 && password.length > 0, [email, password]);
  const canVerifyOtp = useMemo(
    () => email.trim().length > 0 && password.length > 0 && otp.trim().length > 0,
    [email, password, otp]
  );

  async function handleRequestOtp(event) {
    event.preventDefault();
    setStatus("loading");
    try {
      const response = await fetch(`${API_BASE}/admin/login/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password })
      });
      if (!response.ok) {
        throw new Error("otp request failed");
      }
      setStep("verify");
      setStatus("otp-sent");
    } catch (error) {
      setStatus("otp-error");
    }
  }

  async function handleVerifyOtp(event) {
    event.preventDefault();
    setStatus("loading");
    try {
      const response = await fetch(`${API_BASE}/admin/login/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password, otp: otp.trim() })
      });
      if (!response.ok) {
        throw new Error("otp verify failed");
      }
      const data = await response.json();
      localStorage.setItem("topfeed-admin-token", data.access_token);
      localStorage.setItem("topfeed-admin-expires", data.expires_at);
      setToken(data.access_token);
      setExpiresAt(data.expires_at);
      setStatus("otp-verified");
    } catch (error) {
      setStatus("otp-verify-error");
    }
  }

  function handleLogout() {
    localStorage.removeItem("topfeed-admin-token");
    localStorage.removeItem("topfeed-admin-expires");
    setToken(null);
    setExpiresAt(null);
    setUsers([]);
    setEvents([]);
    setStatus(null);
    setStep("request");
    setOtp("");
  }

  async function loadUsers() {
    if (!token) return;
    setStatus("loading-users");
    try {
      const response = await fetch(`${API_BASE}/admin/users?limit=50`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) {
        throw new Error("users fetch failed");
      }
      const data = await response.json();
      setUsers(data);
      setStatus("users-loaded");
    } catch (error) {
      setStatus("users-error");
    }
  }

  async function loadEvents() {
    if (!token) return;
    setStatus("loading-events");
    const params = new URLSearchParams();
    if (eventUserId.trim()) params.append("user_id", eventUserId.trim());
    if (eventType) params.append("event_type", eventType);
    params.append("limit", "50");
    try {
      const response = await fetch(`${API_BASE}/admin/events?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) {
        throw new Error("events fetch failed");
      }
      const data = await response.json();
      setEvents(data);
      setStatus("events-loaded");
    } catch (error) {
      setStatus("events-error");
    }
  }

  async function handleUserUpdate(event) {
    event.preventDefault();
    if (!updateUserId.trim() || !token) return;
    setUpdateStatus("loading");
    const payload = {};
    if (updateEmail.trim()) payload.email = updateEmail.trim();
    if (updatePassword.trim()) payload.password = updatePassword;
    if (updateFullName.trim()) payload.full_name = updateFullName.trim();
    try {
      const response = await fetch(
        `${API_BASE}/admin/users/${encodeURIComponent(updateUserId.trim())}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        }
      );
      if (!response.ok) {
        throw new Error("update failed");
      }
      setUpdateStatus("updated");
      setUpdateEmail("");
      setUpdatePassword("");
      setUpdateFullName("");
      loadUsers();
    } catch (error) {
      setUpdateStatus("error");
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen bg-[color:var(--bg)]">
        <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center px-6 py-12">
          <div className="rounded-3xl border border-[color:var(--panel-border)] bg-[color:var(--panel-bg)] p-8 shadow-[0_25px_60px_rgba(0,0,0,0.2)]">
            <p className="text-xs uppercase tracking-[0.4em] text-[color:var(--accent)]">Admin</p>
            <h1 className="mt-3 text-3xl font-semibold text-[color:var(--text)]">
              {step === "request" ? "Request login code" : "Verify OTP"}
            </h1>
            <p className="mt-2 text-sm text-[color:var(--muted)]">
              {step === "request"
                ? "Enter your admin email and password to receive an OTP."
                : "Enter the OTP sent to your email to finish login."}
            </p>
            <form
              className="mt-6 space-y-4"
              onSubmit={step === "request" ? handleRequestOtp : handleVerifyOtp}
            >
              <label className="block text-xs font-semibold text-[color:var(--muted)]">
                Email
                <input
                  className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="admin@example.com"
                />
              </label>
              <label className="block text-xs font-semibold text-[color:var(--muted)]">
                Password
                <input
                  type="password"
                  className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter password"
                />
              </label>
              {step === "verify" && (
                <label className="block text-xs font-semibold text-[color:var(--muted)]">
                  OTP
                  <input
                    type="password"
                    className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                    value={otp}
                    onChange={(event) => setOtp(event.target.value)}
                    placeholder="6-digit code"
                  />
                </label>
              )}
              <button
                className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)] disabled:opacity-60"
                disabled={step === "request" ? !canRequestOtp : !canVerifyOtp}
              >
                {step === "request" ? "Send OTP" : "Verify and login"}
              </button>
              <div className="flex flex-col gap-2">
                {step === "verify" && (
                  <button
                    type="button"
                    className="text-xs font-semibold text-[color:var(--muted)] hover:text-[color:var(--accent)]"
                    onClick={() => {
                      setStep("request");
                      setOtp("");
                      setStatus(null);
                    }}
                  >
                    Resend OTP
                  </button>
                )}
                <button
                  type="button"
                  className="text-xs font-semibold text-[color:var(--muted)] hover:text-[color:var(--accent)]"
                  onClick={onBack}
                >
                  Back to user login
                </button>
              </div>
              {status === "otp-sent" && (
                <p className="text-xs text-[color:var(--muted)]">OTP sent. Check your email.</p>
              )}
              {status === "otp-error" && (
                <p className="text-xs text-[color:var(--muted)]">Could not send OTP.</p>
              )}
              {status === "otp-verify-error" && (
                <p className="text-xs text-[color:var(--muted)]">OTP verification failed.</p>
              )}
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[color:var(--bg)]">
      <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <div className="rounded-3xl border border-[color:var(--panel-border)] bg-[color:var(--panel-bg)] p-8 shadow-[0_25px_60px_rgba(0,0,0,0.2)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-[color:var(--accent)]">Admin</p>
              <h1 className="mt-2 text-3xl font-semibold text-[color:var(--text)]">Control room</h1>
              {expiresAt && (
                <p className="mt-1 text-xs text-[color:var(--muted)]">Token expires: {expiresAt}</p>
              )}
            </div>
            <button
              className="rounded-full border border-[color:var(--panel-border)] px-4 py-2 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
              onClick={handleLogout}
            >
              Log out
            </button>
          </div>

          <div className="mt-8 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
            <div className="space-y-6">
              <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-[color:var(--text)]">Recent users</h2>
                  <button
                    className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                    onClick={loadUsers}
                  >
                    Load
                  </button>
                </div>
                <div className="mt-4 space-y-3">
                  {users.length === 0 ? (
                    <p className="text-xs text-[color:var(--muted)]">No users loaded yet.</p>
                  ) : (
                    users.map((user) => (
                      <div
                        key={user.user_id}
                        className="rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-xs text-[color:var(--muted)]"
                      >
                        <p className="text-sm font-semibold text-[color:var(--text)]">{user.full_name || "Unnamed"}</p>
                        <p>{user.email || "No email"}</p>
                        <p>{user.user_id}</p>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-[color:var(--text)]">Activity log</h2>
                  <button
                    className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                    onClick={loadEvents}
                  >
                    Load
                  </button>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <label className="text-xs font-semibold text-[color:var(--muted)]">
                    User ID
                    <input
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                      value={eventUserId}
                      onChange={(event) => setEventUserId(event.target.value)}
                      placeholder="Optional"
                    />
                  </label>
                  <label className="text-xs font-semibold text-[color:var(--muted)]">
                    Event type
                    <select
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                      value={eventType}
                      onChange={(event) => setEventType(event.target.value)}
                    >
                      <option value="">All</option>
                      {EVENT_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="mt-4 space-y-3">
                  {events.length === 0 ? (
                    <p className="text-xs text-[color:var(--muted)]">No events loaded yet.</p>
                  ) : (
                    events.map((eventItem) => (
                      <div
                        key={eventItem.event_id}
                        className="rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-xs text-[color:var(--muted)]"
                      >
                        <p className="text-sm font-semibold text-[color:var(--text)]">{eventItem.event_type}</p>
                        <p>{eventItem.user_id}</p>
                        <p>{eventItem.ts}</p>
                        <p>{eventItem.news_id}</p>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>

            <section className="h-fit rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
              <h2 className="text-sm font-semibold text-[color:var(--text)]">Update user</h2>
              <form className="mt-4 space-y-3" onSubmit={handleUserUpdate}>
                <label className="block text-xs font-semibold text-[color:var(--muted)]">
                  User ID
                  <input
                    className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                    value={updateUserId}
                    onChange={(event) => setUpdateUserId(event.target.value)}
                    placeholder="U123456"
                    required
                  />
                </label>
                <label className="block text-xs font-semibold text-[color:var(--muted)]">
                  Full name
                  <input
                    className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                    value={updateFullName}
                    onChange={(event) => setUpdateFullName(event.target.value)}
                    placeholder="Optional"
                  />
                </label>
                <label className="block text-xs font-semibold text-[color:var(--muted)]">
                  Email
                  <input
                    className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                    value={updateEmail}
                    onChange={(event) => setUpdateEmail(event.target.value)}
                    placeholder="Optional"
                  />
                </label>
                <label className="block text-xs font-semibold text-[color:var(--muted)]">
                  Password
                  <input
                    type={showUpdatePassword ? "text" : "password"}
                    className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                    value={updatePassword}
                    onChange={(event) => setUpdatePassword(event.target.value)}
                    placeholder="Optional"
                  />
                  <label className="mt-2 flex items-center gap-2 text-xs text-[color:var(--muted)]">
                    <input
                      type="checkbox"
                      checked={showUpdatePassword}
                      onChange={(event) => setShowUpdatePassword(event.target.checked)}
                    />
                    Show password
                  </label>
                  <div className="mt-3 space-y-1 text-xs">
                    {passwordRules.map((rule) => (
                      <div
                        key={`admin-update-${rule.id}`}
                        className={`flex items-center justify-between ${
                          updatePasswordChecks[rule.id]
                            ? "text-green-400"
                            : "text-[color:var(--muted)]"
                        }`}
                      >
                        <span>{rule.label}</span>
                        {updatePasswordChecks[rule.id] ? <span>✓</span> : null}
                      </div>
                    ))}
                  </div>
                </label>
                <button
                  className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)] disabled:opacity-60"
                  disabled={!updateUserId.trim()}
                >
                  Update user
                </button>
                {updateStatus === "updated" && (
                  <p className="text-xs text-[color:var(--muted)]">User updated.</p>
                )}
                {updateStatus === "error" && (
                  <p className="text-xs text-[color:var(--muted)]">Update failed.</p>
                )}
              </form>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
