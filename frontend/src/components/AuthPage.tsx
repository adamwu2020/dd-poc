import { useState } from "react";
import { api } from "../api";
import type { Account } from "../types";

interface Props {
  onSignedIn: (account: Account) => void;
}

export default function AuthPage({ onSignedIn }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const registering = mode === "register";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (registering && password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      onSignedIn(registering ? await api.register(email, password) : await api.login(email, password));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: "login" | "register") {
    setMode(next);
    setError(null);
    setConfirm("");
  }

  return (
    <div className="auth-wrap">
      <section className="card auth-card">
        <h2>{registering ? "Create an account" : "Sign in"}</h2>
        <p className="muted">
          {registering
            ? "New accounts get 1 positive and 1 negative sample free. Additional samples cost $0.50 each."
            : "Sign in to generate synthetic patient records."}
        </p>
        <form onSubmit={submit} className="stack">
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={registering ? "new-password" : "current-password"}
              required
              minLength={registering ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {registering && (
            <label>
              Confirm password
              <input
                type="password"
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
              <span className="hint">At least 8 characters.</span>
            </label>
          )}
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
          </button>
        </form>
        <p className="muted center">
          {registering ? "Already have an account? " : "New here? "}
          <button type="button" className="link" onClick={() => switchMode(registering ? "login" : "register")}>
            {registering ? "Sign in" : "Create an account"}
          </button>
        </p>
      </section>
    </div>
  );
}
