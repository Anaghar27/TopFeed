import { useMemo, useState } from "react";
import { City, Country, State } from "country-state-city";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const CATEGORY_OPTIONS = [
  "news",
  "sports",
  "finance",
  "entertainment",
  "health",
  "travel",
  "foodanddrink",
  "music",
  "tv"
];

const SUBCATEGORY_OPTIONS = [
  "newsworld",
  "newsus",
  "newspolitics",
  "tech",
  "science",
  "sportsnews",
  "football_nfl",
  "basketball_nba",
  "financeeconomy",
  "entertainment-celebrity"
];

export default function AuthPage({ onAuth, onAdmin }) {
  const [mode, setMode] = useState("login");
  const [loginMode, setLoginMode] = useState("email");
  const [resetStep, setResetStep] = useState("request");
  const [userId, setUserId] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [country, setCountry] = useState("");
  const [manualCountry, setManualCountry] = useState("");
  const [stateRegion, setStateRegion] = useState("");
  const [manualState, setManualState] = useState("");
  const [city, setCity] = useState("");
  const [manualCity, setManualCity] = useState("");
  const [theme] = useState("dark");
  const [categories, setCategories] = useState([]);
  const [subcategories, setSubcategories] = useState([]);
  const [status, setStatus] = useState(null);
  const [showPasswordRules, setShowPasswordRules] = useState(false);
  const [resetEmail, setResetEmail] = useState("");
  const [resetOtp, setResetOtp] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [resetMessage, setResetMessage] = useState("");
  const [otpVerified, setOtpVerified] = useState(false);
  const [otpVerifying, setOtpVerifying] = useState(false);
  const [otpFailed, setOtpFailed] = useState(false);
  const [resetCompleted, setResetCompleted] = useState(false);
  const [showResetPassword, setShowResetPassword] = useState(false);
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
  const passwordChecks = useMemo(() => {
    const checks = {};
    for (const rule of passwordRules) {
      checks[rule.id] = rule.test(password);
    }
    return checks;
  }, [password, passwordRules]);
  const resetPasswordChecks = useMemo(() => {
    const checks = {};
    for (const rule of passwordRules) {
      checks[rule.id] = rule.test(resetPassword);
    }
    return checks;
  }, [resetPassword, passwordRules]);
  const isPasswordValid = useMemo(
    () => passwordRules.every((rule) => passwordChecks[rule.id]),
    [passwordChecks, passwordRules]
  );
  const isResetPasswordValid = useMemo(
    () => passwordRules.every((rule) => resetPasswordChecks[rule.id]),
    [resetPasswordChecks, passwordRules]
  );
  const countries = useMemo(() => {
    try {
      return Country.getAllCountries().sort((a, b) => a.name.localeCompare(b.name));
    } catch (error) {
      return [];
    }
  }, []);
  const selectedCountry = countries.find((entry) => entry.isoCode === country) || null;
  const states = useMemo(() => {
    if (!country) return [];
    try {
      return State.getStatesOfCountry(country).sort((a, b) => a.name.localeCompare(b.name));
    } catch (error) {
      return [];
    }
  }, [country]);
  const selectedState = states.find((entry) => entry.isoCode === stateRegion) || null;
  const cities = useMemo(() => {
    if (!country || !stateRegion) return [];
    try {
      return City.getCitiesOfState(country, stateRegion).sort((a, b) => a.name.localeCompare(b.name));
    } catch (error) {
      return [];
    }
  }, [country, stateRegion]);
  const hasGeoData = countries.length > 0;

  const locationParts = hasGeoData
    ? [city || "", selectedState?.name || "", selectedCountry?.name || ""]
    : [manualCity.trim(), manualState.trim(), manualCountry.trim()];
  const resolvedLocationParts = locationParts.filter(Boolean);
  const locationValue = resolvedLocationParts.length ? resolvedLocationParts.join(", ") : null;

  const canSubmit = useMemo(() => {
    if (mode === "login") {
      return loginMode === "user_id" ? userId.trim().length > 0 : email.trim().length > 0 && password.length > 0;
    }
    return fullName.trim().length > 0 && email.trim().length > 0 && password.length > 0 && isPasswordValid;
  }, [mode, loginMode, userId, fullName, email, password, isPasswordValid]);

  async function handleLogin(event) {
    event.preventDefault();
    setStatus("loading");
    try {
      if (loginMode === "user_id") {
        const response = await fetch(`${API_BASE}/users/${encodeURIComponent(userId.trim())}`);
        if (response.status === 404) {
          setMode("signup");
          setStatus("no-user");
          return;
        }
        if (!response.ok) {
          if (response.status === 401) {
            setStatus("login-invalid");
            return;
          }
          if (response.status === 404) {
            setStatus("login-no-email");
            return;
          }
          setStatus("login-error");
          return;
        }
        const data = await response.json();
        const needsProfile = !data.full_name || !data.email;
        onAuth(data, { needsProfile });
      } else {
        const response = await fetch(`${API_BASE}/users/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), password })
        });
        if (!response.ok) {
          throw new Error("login failed");
        }
        const data = await response.json();
        const needsProfile = !data.full_name || !data.email;
        onAuth(data, { needsProfile });
      }
    } catch (error) {
      setStatus("login-error");
    }
  }

  async function handleSignup(event) {
    event.preventDefault();
    setStatus("loading");
    try {
      const response = await fetch(`${API_BASE}/users/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim(),
          email: email.trim() || null,
          location: locationValue,
          theme_preference: theme,
          preferences: { categories, subcategories },
          password
        })
      });
      if (!response.ok) {
        if (response.status === 409) {
          const payload = await response.json().catch(() => ({}));
          if (payload.detail === "user_id already exists") {
            setStatus("duplicate-user");
          } else {
            setStatus("duplicate-email");
          }
          return;
        }
        throw new Error("signup failed");
      }
      const data = await response.json();
      onAuth(data);
    } catch (error) {
      setStatus("signup-error");
    }
  }

  async function handleResetRequest(event) {
    event.preventDefault();
    setStatus("loading");
    setResetMessage("");
    setOtpVerified(false);
    try {
      const response = await fetch(`${API_BASE}/users/password/reset/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: resetEmail.trim() })
      });
      if (response.status === 404) {
        setStatus("reset-no-user");
        return;
      }
      if (!response.ok) {
        throw new Error("reset failed");
      }
      setResetStep("verify");
      setStatus("reset-sent");
      setResetMessage("OTP sent. Please check your email.");
    } catch (error) {
      setStatus("reset-error");
      setResetMessage("Could not send OTP. Please try again.");
    }
  }

  async function handleOtpVerify() {
    setOtpVerifying(true);
    setResetMessage("");
    try {
      const response = await fetch(`${API_BASE}/users/password/reset/otp/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: resetEmail.trim(),
          otp: resetOtp.trim()
        })
      });
      if (!response.ok) {
        throw new Error("otp verify failed");
      }
      setOtpVerified(true);
      setOtpFailed(false);
      setResetMessage("OTP verified. You can set a new password.");
    } catch (error) {
      setOtpVerified(false);
      setOtpFailed(true);
      setResetMessage("OTP verification failed. Check the code and try again.");
    } finally {
      setOtpVerifying(false);
    }
  }

  async function handleResetVerify(event) {
    event.preventDefault();
    setStatus("loading");
    setResetMessage("");
    try {
      const response = await fetch(`${API_BASE}/users/password/reset/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: resetEmail.trim(),
          otp: resetOtp.trim(),
          new_password: resetPassword
        })
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = payload.detail || "Password reset failed.";
        setStatus("reset-verify-error");
        setResetMessage(detail);
        return;
      }
      setStatus("reset-success");
      setPassword("");
      setResetOtp("");
      setResetPassword("");
      setOtpVerified(false);
      setResetCompleted(true);
      setResetMessage("Password updated.");
    } catch (error) {
      setStatus("reset-verify-error");
      setResetMessage("Password reset failed. Please try again.");
    }
  }

  function toggleSelection(value, current, setter) {
    if (current.includes(value)) {
      setter(current.filter((item) => item !== value));
    } else {
      setter([...current, value]);
    }
  }

  return (
    <div className="min-h-screen bg-[color:var(--bg)]">
      <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center px-6 py-12">
        <div className="rounded-3xl border border-[color:var(--panel-border)] bg-[color:var(--panel-bg)] p-8 shadow-[0_25px_60px_rgba(0,0,0,0.2)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-[color:var(--accent)]">ToPFeed</p>
              <h1 className="mt-3 text-3xl font-semibold text-[color:var(--text)]">
                {mode === "login"
                  ? "Sign in"
                  : mode === "signup"
                  ? "Create your portal"
                  : resetCompleted
                  ? "Password reset successful"
                  : "Reset your password"}
              </h1>
            </div>
            {mode !== "reset" && (
              <button
                type="button"
                className="h-fit rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={onAdmin}
              >
                Admin login
              </button>
            )}
          </div>
          {!resetCompleted && (
            <p className="mt-2 text-sm text-[color:var(--muted)]">
              {mode === "login"
                ? "Sign in to continue."
                : mode === "signup"
                ? "Share your preferences to personalize your feed."
                : "Verify your email and set a new password."}
            </p>
          )}

          {mode !== "reset" && (
            <div className="mt-6 flex gap-2 text-xs font-semibold">
              <button
                className={
                  mode === "login"
                    ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                    : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)]"
                }
                onClick={() => {
                  setMode("login");
                  setStatus(null);
                }}
              >
                Login
              </button>
              <button
                className={
                  mode === "signup"
                    ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                    : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)]"
                }
                onClick={() => {
                  setMode("signup");
                  setStatus(null);
                }}
              >
                Sign up
              </button>
            </div>
          )}

          {mode === "login" && (
            <form className="mt-6 space-y-4" onSubmit={handleLogin}>
              <div className="flex gap-2 text-xs font-semibold">
                <button
                  type="button"
                  className={
                    loginMode === "email"
                      ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                      : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)]"
                  }
                  onClick={() => setLoginMode("email")}
                >
                  Email
                </button>
                <button
                  type="button"
                  className={
                    loginMode === "user_id"
                      ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-[color:var(--text)]"
                      : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[color:var(--muted)]"
                  }
                  onClick={() => setLoginMode("user_id")}
                >
                  One-time Access code
                </button>
              </div>
              {loginMode === "user_id" ? (
              <label className="block text-xs font-semibold text-[color:var(--muted)]">
                User ID
                <input
                  className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)] focus:border-[color:var(--accent-strong)] focus:outline-none"
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                  placeholder="U483745"
                />
              </label>
              ) : (
                <>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    Email
                    <input
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)] focus:border-[color:var(--accent-strong)] focus:outline-none"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      placeholder="jane@example.com"
                    />
                  </label>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    Password
                    <input
                      type="password"
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)] focus:border-[color:var(--accent-strong)] focus:outline-none"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Enter password"
                    />
                  </label>
                </>
              )}
              <button
                className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)] disabled:opacity-60"
                disabled={!canSubmit}
              >
                Continue
              </button>
              {loginMode === "email" && (
                <button
                  type="button"
                  className="text-xs font-semibold text-[color:var(--muted)] hover:text-[color:var(--accent)]"
                  onClick={() => {
                    setMode("reset");
                    setResetStep("request");
                    setResetEmail(email.trim());
                    setStatus(null);
                  }}
                >
                  Forgot password?
                </button>
              )}
              {status === "no-user" && (
                <p className="text-xs text-[color:var(--muted)]">
                  User not found. Please sign up or update your profile details.
                </p>
              )}
      {(status === "login-invalid" || (status === "login-error" && loginMode === "email")) && (
        <p className="text-xs text-[color:var(--muted)]">Password incorrect.</p>
      )}
      {status === "login-no-email" && (
        <p className="text-xs text-[color:var(--muted)]">Email not found. Please sign up.</p>
      )}
      {status === "login-error" && loginMode === "user_id" && (
        <p className="text-xs text-[color:var(--muted)]">Could not load user.</p>
      )}
            </form>
          )}

          {mode === "reset" && (
            <form
              className="mt-6 space-y-4"
              onSubmit={resetStep === "request" ? handleResetRequest : handleResetVerify}
            >
              {resetCompleted ? (
                <>
                  <div className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] px-4 py-3 text-xs text-[color:var(--muted)]">
                    Password reset successful.
                  </div>
                  <button
                    type="button"
                    className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)]"
                    onClick={() => {
                      setMode("login");
                      setLoginMode("email");
                      setResetStep("request");
                      setResetCompleted(false);
                      setResetMessage("");
                    }}
                  >
                    Login to continue
                  </button>
                </>
              ) : (
                <>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    Email
                    <input
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                      value={resetEmail}
                      onChange={(event) => setResetEmail(event.target.value)}
                      placeholder="jane@example.com"
                    />
                  </label>
              {resetStep === "verify" && (
                <>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    OTP
                        <div className="mt-2 flex items-center gap-2">
                          <input
                            className="w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                            value={resetOtp}
                            onChange={(event) => {
                              setResetOtp(event.target.value);
                              setOtpVerified(false);
                              setOtpFailed(false);
                            }}
                            placeholder="6-digit code"
                            type="password"
                          />
                          <button
                            type="button"
                            className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)] disabled:opacity-60"
                            onClick={handleOtpVerify}
                            disabled={!resetOtp.trim() || otpVerifying}
                          >
                            {otpVerifying ? "Checking..." : "Verify OTP"}
                          </button>
                          {otpVerified && <span className="text-xs text-green-400">✓</span>}
                          {otpFailed && !otpVerifying && (
                            <span className="text-xs text-red-400">✕</span>
                          )}
                        </div>
                      </label>
                      <label className="block text-xs font-semibold text-[color:var(--muted)]">
                        New password
                        <input
                          type={showResetPassword ? "text" : "password"}
                          className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)] disabled:opacity-60"
                          value={resetPassword}
                          onChange={(event) => setResetPassword(event.target.value)}
                          placeholder="Set a new password"
                          disabled={!otpVerified}
                        />
                        <label className="mt-2 flex items-center gap-2 text-xs text-[color:var(--muted)]">
                          <input
                            type="checkbox"
                            checked={showResetPassword}
                            onChange={(event) => setShowResetPassword(event.target.checked)}
                          />
                          Show password
                        </label>
                        <div className="mt-3 space-y-1 text-xs">
                          {passwordRules.map((rule) => (
                            <div
                              key={`reset-${rule.id}`}
                              className={`flex items-center justify-between ${
                                resetPasswordChecks[rule.id]
                                  ? "text-green-400"
                                  : "text-[color:var(--muted)]"
                              }`}
                            >
                              <span>{rule.label}</span>
                              {resetPasswordChecks[rule.id] ? <span>✓</span> : null}
                            </div>
                          ))}
                        </div>
                      </label>
                    </>
                  )}
                  <button
                    className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)]"
                    disabled={
                      resetStep === "verify" && (!otpVerified || !resetPassword.trim() || !isResetPasswordValid)
                    }
                  >
                    {resetStep === "request" ? "Send OTP" : "Reset password"}
                  </button>
                  <button
                    type="button"
                    className="text-xs font-semibold text-[color:var(--muted)] hover:text-[color:var(--accent)]"
                    onClick={() => {
                      setMode("login");
                      setStatus(null);
                      setResetCompleted(false);
                    }}
                  >
                    Back to login
                  </button>
                  {status === "reset-no-user" && (
                    <p className="text-xs text-[color:var(--muted)]">
                      No account found for this email. Please sign up instead.
                    </p>
                  )}
                  {resetMessage && <p className="text-xs text-[color:var(--muted)]">{resetMessage}</p>}
                </>
              )}
            </form>
          )}

          {mode === "signup" && (
            <form className="mt-6 space-y-4" onSubmit={handleSignup}>
              <label className="block text-xs font-semibold text-[color:var(--muted)]">
                Full name
                <input
                  className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Jane Doe"
                  required
                />
              </label>
              <label className="block text-xs font-semibold text-[color:var(--muted)]">
                Email
                <input
                  className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="jane@example.com"
                  required
                />
              </label>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    Password
                    <input
                      type="password"
                      className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      onFocus={() => setShowPasswordRules(true)}
                      onBlur={() => setShowPasswordRules(false)}
                      placeholder="Create a password"
                      required
                    />
                    {showPasswordRules && (
                      <div className="mt-3 space-y-1 text-xs">
                        {passwordRules.map((rule) => (
                          <div
                            key={`signup-${rule.id}`}
                            className={`flex items-center justify-between ${
                              passwordChecks[rule.id]
                                ? "text-green-400"
                                : "text-[color:var(--muted)]"
                            }`}
                          >
                            <span>{rule.label}</span>
                            {passwordChecks[rule.id] ? <span>✓</span> : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </label>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2 grid gap-4 md:grid-cols-3">
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    Country
                    {hasGeoData ? (
                      <select
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={country}
                        onChange={(event) => {
                          setCountry(event.target.value);
                          setStateRegion("");
                          setCity("");
                        }}
                      >
                        <option value="">Select country</option>
                        {countries.map((option) => (
                          <option key={`country-${option.isoCode}`} value={option.isoCode}>
                            {option.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={manualCountry}
                        onChange={(event) => setManualCountry(event.target.value)}
                        placeholder="Enter country"
                      />
                    )}
                  </label>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    State
                    {hasGeoData ? (
                      <select
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={stateRegion}
                        onChange={(event) => {
                          setStateRegion(event.target.value);
                          setCity("");
                        }}
                        disabled={!country}
                      >
                        <option value="">{country ? "Select state" : "Select country first"}</option>
                        {states.map((option) => (
                          <option key={`state-${option.isoCode}`} value={option.isoCode}>
                            {option.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={manualState}
                        onChange={(event) => setManualState(event.target.value)}
                        placeholder="Enter state"
                      />
                    )}
                  </label>
                  <label className="block text-xs font-semibold text-[color:var(--muted)]">
                    City
                    {hasGeoData ? (
                      <select
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={city}
                        onChange={(event) => setCity(event.target.value)}
                        disabled={!stateRegion}
                      >
                        <option value="">{stateRegion ? "Select city" : "Select state first"}</option>
                        {cities.map((option) => (
                          <option key={`city-${option.name}`} value={option.name}>
                            {option.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={manualCity}
                        onChange={(event) => setManualCity(event.target.value)}
                        placeholder="Enter city"
                      />
                    )}
                  </label>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs font-semibold text-[color:var(--muted)]">News categories</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {CATEGORY_OPTIONS.map((option) => (
                      <button
                        type="button"
                        key={option}
                        className={
                          categories.includes(option)
                            ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-xs text-[color:var(--text)]"
                            : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs text-[color:var(--muted)]"
                        }
                        onClick={() => toggleSelection(option, categories, setCategories)}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold text-[color:var(--muted)]">Subcategories</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {SUBCATEGORY_OPTIONS.map((option) => (
                      <button
                        type="button"
                        key={option}
                        className={
                          subcategories.includes(option)
                            ? "rounded-full bg-[color:var(--accent-strong)] px-3 py-1 text-xs text-[color:var(--text)]"
                            : "rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs text-[color:var(--muted)]"
                        }
                        onClick={() => toggleSelection(option, subcategories, setSubcategories)}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <button
                className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)] disabled:opacity-60"
                disabled={!canSubmit}
              >
                Create account
              </button>
              {status === "duplicate-email" && (
                <p className="text-xs text-[color:var(--muted)]">
                  Email already exists. Try logging in instead.
                </p>
              )}
              {status === "duplicate-user" && (
                <p className="text-xs text-[color:var(--muted)]">
                  User ID already exists. Choose a different one or leave it blank.
                </p>
              )}
              {status === "signup-error" && (
                <p className="text-xs text-[color:var(--muted)]">Could not create account.</p>
              )}
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
