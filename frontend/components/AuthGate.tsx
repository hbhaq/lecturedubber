"use client";
import { useEffect, useState } from "react";
import { api, setCsrf } from "../lib/api";
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"loading" | "login" | "ready">("loading"),
    [required, setRequired] = useState(false),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function check() {
    try {
      const s = await api("/auth/session");
      setRequired(s.required);
      setCsrf(s.csrf);
      setState(s.authenticated ? "ready" : "login");
      setError("");
    } catch {
      setError(
        "Cannot reach the application server. Check that the backend is running.",
      );
    }
  }
  useEffect(() => {
    void check();
    const expired = () => {
      setCsrf("");
      setPassword("");
      setRequired(true);
      setState("login");
      setError("Your session expired. Please sign in again.");
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  if (state === "ready")
    return (
      <>
        {required && (
          <div className="auth-bar">
            <span>Private workspace</span>
            <button
              className="text-button"
              onClick={async () => {
                setBusy(true);
                try {
                  await api("/auth/logout", "POST");
                  setCsrf("");
                  setState("login");
                  setPassword("");
                } catch (e) {
                  setError(e instanceof Error ? e.message : "Sign out failed");
                } finally {
                  setBusy(false);
                }
              }}
              disabled={busy}
            >
              Sign out
            </button>
            {error && <span role="alert">{error}</span>}
          </div>
        )}
        {children}
      </>
    );
  return (
    <main className="login-page">
      <section className="panel login-card">
        <div className="eyebrow">LECTURE STUDIO · PRIVATE WORKSPACE</div>
        <h1>{state === "loading" ? "Connecting…" : "Welcome back."}</h1>
        <p className="muted">
          Sign in to access your lectures, recordings and student materials.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {state === "loading" ? (
          <button onClick={check}>Retry connection</button>
        ) : (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                const s = await api("/auth/login", "POST", {
                  username,
                  password,
                });
                setCsrf(s.csrf);
                setPassword("");
                setState("ready");
              } catch (e) {
                setError(e instanceof Error ? e.message : "Sign in failed");
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="field">
              Username
              <input
                autoComplete="username"
                required
                maxLength={100}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="field">
              Password
              <input
                type="password"
                autoComplete="current-password"
                required
                maxLength={256}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <button disabled={busy}>
              {busy ? "Signing in…" : "Sign in →"}
            </button>
            <p className="tiny">
              Your password is separate from your GitHub account. Contact the
              workspace owner if you need access.
            </p>
          </form>
        )}
      </section>
    </main>
  );
}
