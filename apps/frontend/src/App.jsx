import { useEffect, useState } from "react";
import AuthPage from "./pages/AuthPage";
import FeedPage from "./pages/FeedPage";
import ProfilePage from "./pages/ProfilePage";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function App() {
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("auth");
  const [theme, setTheme] = useState(() => localStorage.getItem("topfeed-theme") || "light");
  const [needsProfileUpdate, setNeedsProfileUpdate] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("topfeed-theme", theme);
  }, [theme]);

  useEffect(() => {
    const storedUserId = localStorage.getItem("topfeed-user-id");
    if (!storedUserId) return;
    async function loadUser() {
      try {
        const response = await fetch(`${API_BASE}/users/${encodeURIComponent(storedUserId)}`);
        if (!response.ok) {
          setPage("auth");
          return;
        }
        const data = await response.json();
        setUser(data);
        setTheme(data.theme_preference || "light");
        if (!data.full_name || !data.email) {
          setNeedsProfileUpdate(true);
          setPage("profile");
        } else {
          setNeedsProfileUpdate(false);
          setPage("feed");
        }
      } catch (error) {
        setPage("auth");
      }
    }
    loadUser();
  }, []);

  function handleAuth(data, options = {}) {
    setUser(data);
    localStorage.setItem("topfeed-user-id", data.user_id);
    setTheme(data.theme_preference || "light");
    if (options.needsProfile) {
      setNeedsProfileUpdate(true);
      setPage("profile");
    } else {
      setNeedsProfileUpdate(false);
      setPage("feed");
    }
  }

  async function handleToggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (!user) return;
    try {
      const response = await fetch(`${API_BASE}/users/${encodeURIComponent(user.user_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme_preference: next })
      });
      if (response.ok) {
        const data = await response.json();
        setUser(data);
      }
    } catch (error) {
      // Ignore theme update failure.
    }
  }

  function handleProfileUpdate(data) {
    setUser(data);
    setTheme(data.theme_preference || theme);
    setNeedsProfileUpdate(false);
  }

  function handleLogout() {
    localStorage.removeItem("topfeed-user-id");
    setUser(null);
    setPage("auth");
  }

  if (page === "auth") {
    return <AuthPage onAuth={handleAuth} />;
  }

  if (page === "profile") {
    return (
      <ProfilePage
        user={user}
        theme={theme}
        onBack={() => setPage("feed")}
        onLogout={handleLogout}
        onUpdate={handleProfileUpdate}
        showCompleteProfileNotice={needsProfileUpdate}
      />
    );
  }

  return (
    <FeedPage
      user={user}
      theme={theme}
      onToggleTheme={handleToggleTheme}
      onProfile={() => setPage("profile")}
      onLogout={handleLogout}
    />
  );
}
