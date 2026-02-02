import { useEffect, useMemo, useRef, useState } from "react";

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

const CITY_OPTIONS = [
  "Austin",
  "Bengaluru",
  "London",
  "New York",
  "San Francisco",
  "Seattle",
  "Sydney",
  "Toronto",
  "Other"
];

const STATE_OPTIONS = [
  "California",
  "Karnataka",
  "Massachusetts",
  "New South Wales",
  "New York",
  "Ontario",
  "Texas",
  "Washington",
  "Other"
];

const COUNTRY_OPTIONS = [
  "Australia",
  "Canada",
  "India",
  "United Kingdom",
  "United States",
  "Other"
];

export default function ProfilePage({ user, theme, onBack, onLogout, onUpdate, showCompleteProfileNotice }) {
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [email, setEmail] = useState(user?.email || "");
  const locationParts = (user?.location || "").split(",").map((part) => part.trim()).filter(Boolean);
  const [city, setCity] = useState(locationParts[0] || "");
  const [customCity, setCustomCity] = useState(
    locationParts[0] && !CITY_OPTIONS.includes(locationParts[0]) ? locationParts[0] : ""
  );
  const [stateRegion, setStateRegion] = useState(locationParts[1] || "");
  const [customStateRegion, setCustomStateRegion] = useState(
    locationParts[1] && !STATE_OPTIONS.includes(locationParts[1]) ? locationParts[1] : ""
  );
  const [country, setCountry] = useState(locationParts[2] || "");
  const [customCountry, setCustomCountry] = useState(
    locationParts[2] && !COUNTRY_OPTIONS.includes(locationParts[2]) ? locationParts[2] : ""
  );
  const [themePref, setThemePref] = useState(user?.theme_preference || theme || "light");
  const [categories, setCategories] = useState(user?.preferences?.categories || []);
  const [subcategories, setSubcategories] = useState(user?.preferences?.subcategories || []);
  const [status, setStatus] = useState(null);
  const [activeSection, setActiveSection] = useState("details");
  const [userMetrics, setUserMetrics] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [profileImageUrl, setProfileImageUrl] = useState(user?.profile_image_url || "");
  const [imageError, setImageError] = useState("");
  const [showImagePreview, setShowImagePreview] = useState(false);
  const [rawImageUrl, setRawImageUrl] = useState("");
  const [cropZoom, setCropZoom] = useState(1);
  const [cropX, setCropX] = useState(0);
  const [cropY, setCropY] = useState(0);
  const dragRef = useRef({
    active: false,
    startX: 0,
    startY: 0,
    startCropX: 0,
    startCropY: 0
  });
  const fileInputRef = useRef(null);
  const resolvedCity = city === "Other" ? customCity.trim() : city;
  const resolvedState = stateRegion === "Other" ? customStateRegion.trim() : stateRegion;
  const resolvedCountry = country === "Other" ? customCountry.trim() : country;
  const locationPartsResolved = [resolvedCity, resolvedState, resolvedCountry].filter(Boolean);
  const locationValue = locationPartsResolved.length ? locationPartsResolved.join(", ") : null;

  const appVersion = "v0.11.0";

  const canSave = useMemo(() => fullName.trim().length > 0, [fullName]);

  useEffect(() => {
    let alive = true;

    async function fetchMetrics() {
      if (!user?.user_id) return;
      setMetricsLoading(true);
      try {
        const response = await fetch(
          `${API_BASE}/metrics/summary?days=14&user_id=${encodeURIComponent(user.user_id)}`
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

    fetchMetrics();
    return () => {
      alive = false;
    };
  }, [user?.user_id]);

  useEffect(() => {
    setProfileImageUrl(user?.profile_image_url || "");
    setRawImageUrl("");
    setCropZoom(1);
    setCropX(0);
    setCropY(0);
  }, [user?.profile_image_url]);

  function toggleSelection(value, current, setter) {
    if (current.includes(value)) {
      setter(current.filter((item) => item !== value));
    } else {
      setter([...current, value]);
    }
  }

  async function handleSave(event) {
    event.preventDefault();
    setStatus("saving");
    try {
      const response = await fetch(`${API_BASE}/users/${encodeURIComponent(user.user_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName.trim(),
          email: email.trim() || null,
          location: locationValue,
          profile_image_url: profileImageUrl || null,
          theme_preference: themePref,
          preferences: { categories, subcategories }
        })
      });
      if (!response.ok) {
        throw new Error("update failed");
      }
      const data = await response.json();
      onUpdate(data);
      setStatus("saved");
      setTimeout(() => setStatus(null), 2000);
    } catch (error) {
      setStatus("error");
    }
  }

  function handleImageChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setImageError("Please upload an image under 2 MB.");
      return;
    }
    if (!file.type.startsWith("image/")) {
      setImageError("Please upload a valid image file.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      setRawImageUrl(result);
      setCropZoom(1);
      setCropX(0);
      setCropY(0);
      setShowImagePreview(true);
      setImageError("");
    };
    reader.readAsDataURL(file);
  }

  async function applyCrop() {
    if (!rawImageUrl) return;
    const image = new Image();
    image.src = rawImageUrl;
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
    });
    const canvas = document.createElement("canvas");
    const size = 512;
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const baseScale = Math.max(size / image.width, size / image.height);
    const scale = baseScale * cropZoom;
    const scaledW = image.width * scale;
    const scaledH = image.height * scale;
    const extraW = Math.max(0, scaledW - size);
    const extraH = Math.max(0, scaledH - size);
    const offsetX = (extraW / 2) * cropX;
    const offsetY = (extraH / 2) * cropY;
    const drawX = (size - scaledW) / 2 - offsetX;
    const drawY = (size - scaledH) / 2 - offsetY;
    ctx.drawImage(image, drawX, drawY, scaledW, scaledH);
    setProfileImageUrl(canvas.toDataURL("image/jpeg", 0.92));
    setRawImageUrl("");
  }

  function handleCropPointerDown(event) {
    if (!rawImageUrl) return;
    dragRef.current.active = true;
    dragRef.current.startX = event.clientX;
    dragRef.current.startY = event.clientY;
    dragRef.current.startCropX = cropX;
    dragRef.current.startCropY = cropY;
  }

  function handleCropPointerMove(event) {
    if (!dragRef.current.active || !rawImageUrl) return;
    const target = event.currentTarget;
    const rect = target.getBoundingClientRect();
    const dx = event.clientX - dragRef.current.startX;
    const dy = event.clientY - dragRef.current.startY;
    const nextX = dragRef.current.startCropX + dx / (rect.width / 2);
    const nextY = dragRef.current.startCropY + dy / (rect.height / 2);
    setCropX(Math.max(-1, Math.min(1, nextX)));
    setCropY(Math.max(-1, Math.min(1, nextY)));
  }

  function handleCropPointerUp() {
    dragRef.current.active = false;
  }

  function handleCropWheel(event) {
    if (!rawImageUrl) return;
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.1 : 0.1;
    setCropZoom((current) => Math.max(1, Math.min(3, Number((current + delta).toFixed(2)))));
  }

  return (
    <div className="min-h-screen bg-[color:var(--bg)]">
      <div className="mx-auto w-full max-w-5xl px-6 py-12">
        <div>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.4em] text-[color:var(--accent)]">Profile</p>
              <h1 className="mt-3 text-3xl font-semibold text-[color:var(--text)]">{fullName || "Your profile"}</h1>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={onBack}
              >
                Back to feed
              </button>
              <button
                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={onLogout}
              >
                Logout
              </button>
            </div>
          </div>

          <form className="mt-6 space-y-6" onSubmit={handleSave}>
            {showCompleteProfileNotice && (
              <div className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] px-5 py-3 text-xs text-[color:var(--muted)]">
                Please complete your profile details so we can personalize your feed.
              </div>
            )}
            <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
              <aside className="space-y-2">
                {[
                  { key: "details", label: "Profile details" },
                  { key: "preferences", label: "Preferences" },
                  { key: "theme", label: "Theme" },
                  { key: "engagement", label: "Engagement" },
                  { key: "version", label: "App version" }
                ].map((section) => (
                  <button
                    key={section.key}
                    type="button"
                    className={
                      activeSection === section.key
                        ? "w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-left text-xs font-semibold text-[color:var(--text)]"
                        : "w-full rounded-xl border border-[color:var(--panel-border)] px-4 py-2 text-left text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                    }
                    onClick={() => setActiveSection(section.key)}
                  >
                    {section.label}
                  </button>
                ))}
              </aside>
              <div className="space-y-6">
                {activeSection === "details" && (
                  <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">Profile details</p>
                    <div className="mt-4 space-y-4">
                      <div className="flex flex-wrap items-center gap-6">
                        <div className="h-32 w-32 overflow-hidden rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--bg)]">
                          {profileImageUrl ? (
                            <img
                              src={profileImageUrl}
                              alt="Profile"
                              className="h-full w-full object-cover"
                            />
                          ) : rawImageUrl ? (
                            <div
                              className="h-full w-full bg-[color:var(--bg)]"
                              style={{
                                backgroundImage: `url(${rawImageUrl})`,
                                backgroundPosition: `${50 + cropX * 25}% ${50 + cropY * 25}%`,
                                backgroundSize: `${100 * cropZoom}% ${100 * cropZoom}%`,
                                backgroundRepeat: "no-repeat"
                              }}
                            />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-sm font-semibold text-[color:var(--muted)]">
                              {fullName.trim().slice(0, 2).toUpperCase() || "U"}
                            </div>
                          )}
                        </div>
                        <div>
                          <div className="text-xs font-semibold text-[color:var(--muted)]">Profile photo</div>
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept="image/*"
                            className="hidden"
                            onChange={handleImageChange}
                          />
                          <button
                            type="button"
                            className="mt-2 rounded-full bg-[color:var(--accent-strong)] px-4 py-1 text-xs font-semibold text-[color:var(--text)]"
                            onClick={() => fileInputRef.current?.click()}
                          >
                            Choose photo
                          </button>
                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            {profileImageUrl && (
                              <button
                                type="button"
                                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                                onClick={() => setShowImagePreview(true)}
                              >
                                View photo
                              </button>
                            )}
                            <span className="text-[10px] text-[color:var(--muted)]">
                              Replace by selecting a new file.
                            </span>
                          </div>
                          {imageError && (
                            <p className="mt-2 text-xs text-[color:var(--muted)]">{imageError}</p>
                          )}
                        </div>
                      </div>
                      <label className="block text-xs font-semibold text-[color:var(--muted)]">
                        Full name
                        <input
                          className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                          value={fullName}
                          onChange={(event) => setFullName(event.target.value)}
                          required
                        />
                      </label>
                      <div className="grid gap-4 md:grid-cols-2">
                        <label className="block text-xs font-semibold text-[color:var(--muted)]">
                          Email
                          <input
                            className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                          />
                        </label>
                        <div className="md:col-span-2 grid gap-4 md:grid-cols-3">
                          <label className="block text-xs font-semibold text-[color:var(--muted)]">
                            City
                            <select
                              className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                              value={city}
                              onChange={(event) => setCity(event.target.value)}
                            >
                              <option value="">Select city</option>
                              {CITY_OPTIONS.map((option) => (
                                <option key={`city-${option}`} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                            {city === "Other" && (
                              <input
                                className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                                value={customCity}
                                onChange={(event) => setCustomCity(event.target.value)}
                                placeholder="Enter city"
                              />
                            )}
                          </label>
                          <label className="block text-xs font-semibold text-[color:var(--muted)]">
                            State
                            <select
                              className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                              value={stateRegion}
                              onChange={(event) => setStateRegion(event.target.value)}
                            >
                              <option value="">Select state</option>
                              {STATE_OPTIONS.map((option) => (
                                <option key={`state-${option}`} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                            {stateRegion === "Other" && (
                              <input
                                className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                                value={customStateRegion}
                                onChange={(event) => setCustomStateRegion(event.target.value)}
                                placeholder="Enter state"
                              />
                            )}
                          </label>
                          <label className="block text-xs font-semibold text-[color:var(--muted)]">
                            Country
                            <select
                              className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                              value={country}
                              onChange={(event) => setCountry(event.target.value)}
                            >
                              <option value="">Select country</option>
                              {COUNTRY_OPTIONS.map((option) => (
                                <option key={`country-${option}`} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                            {country === "Other" && (
                              <input
                                className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                                value={customCountry}
                                onChange={(event) => setCustomCountry(event.target.value)}
                                placeholder="Enter country"
                              />
                            )}
                          </label>
                        </div>
                      </div>
                    </div>
                  </section>
                )}

                {activeSection === "preferences" && (
                  <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">Preferences</p>
                    <div className="mt-4 grid gap-4 md:grid-cols-2">
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
                  </section>
                )}

                {activeSection === "theme" && (
                  <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">Theme</p>
                    <label className="mt-4 block text-xs font-semibold text-[color:var(--muted)]">
                      Theme preference
                      <select
                        className="mt-2 w-full rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)] px-3 py-2 text-sm text-[color:var(--text)]"
                        value={themePref}
                        onChange={(event) => setThemePref(event.target.value)}
                      >
                        <option value="light">Light</option>
                        <option value="dark">Dark</option>
                      </select>
                    </label>
                  </section>
                )}

                {activeSection === "engagement" && (
                  <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">Engagement</p>
                    <div className="mt-4 text-xs text-[color:var(--muted)]">
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
                  </section>
                )}

                {activeSection === "version" && (
                  <section className="rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--card-bg)] p-5">
                    <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">App version</p>
                    <div className="mt-4 text-xs text-[color:var(--muted)]">
                      Current version: {appVersion}
                    </div>
                  </section>
                )}

                <div className="flex flex-wrap items-center justify-between gap-4 text-xs text-[color:var(--muted)]">
                  {status === "saved" && <span className="text-[color:var(--accent)]">Saved</span>}
                  {status === "error" && <span className="text-[color:var(--muted)]">Save failed</span>}
                </div>

                <button
                  className="w-full rounded-xl bg-[color:var(--accent-strong)] px-4 py-2 text-sm font-semibold text-[color:var(--text)] disabled:opacity-60"
                  disabled={!canSave}
                >
                  Save profile
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>
      {showImagePreview && (rawImageUrl || profileImageUrl) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => {
              setShowImagePreview(false);
              if (rawImageUrl) {
                setRawImageUrl("");
                setCropZoom(1);
                setCropX(0);
                setCropY(0);
              }
            }}
          />
          <div className="relative w-full max-w-3xl rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--panel-bg)] p-4 shadow-[0_25px_60px_rgba(0,0,0,0.25)]">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-[0.3em] text-[color:var(--accent)]">
                {rawImageUrl ? "Adjust photo" : "Profile photo"}
              </p>
              <button
                className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-xs font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                onClick={() => {
                  setShowImagePreview(false);
                  if (rawImageUrl) {
                    setRawImageUrl("");
                    setCropZoom(1);
                    setCropX(0);
                    setCropY(0);
                  }
                }}
              >
                Close
              </button>
            </div>
            <div className="mt-4 space-y-4">
              {rawImageUrl ? (
                <>
                  <div className="flex items-center justify-center">
                    <div
                      className="h-[60vh] w-[60vh] rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--bg)]"
                      onMouseDown={handleCropPointerDown}
                      onMouseMove={handleCropPointerMove}
                      onMouseUp={handleCropPointerUp}
                      onMouseLeave={handleCropPointerUp}
                      onWheel={handleCropWheel}
                      role="presentation"
                      style={{
                        backgroundImage: `url(${rawImageUrl})`,
                        backgroundPosition: `${50 + cropX * 25}% ${50 + cropY * 25}%`,
                        backgroundSize: `${100 * cropZoom}% ${100 * cropZoom}%`,
                        backgroundRepeat: "no-repeat",
                        cursor: "grab"
                      }}
                    />
                  </div>
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[color:var(--muted)]">
                    Drag to reposition • Scroll to zoom
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                      onClick={() => {
                        applyCrop();
                        setShowImagePreview(false);
                      }}
                    >
                      Apply crop
                    </button>
                    <button
                      type="button"
                      className="rounded-full border border-[color:var(--panel-border)] px-3 py-1 text-[10px] font-semibold text-[color:var(--muted)] hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
                      onClick={() => {
                        setRawImageUrl("");
                        setCropZoom(1);
                        setCropX(0);
                        setCropY(0);
                        setShowImagePreview(false);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <div className="max-h-[70vh] overflow-hidden rounded-xl border border-[color:var(--panel-border)] bg-[color:var(--bg)]">
                  <img
                    src={profileImageUrl}
                    alt="Profile preview"
                    className="h-full w-full object-contain"
                  />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
