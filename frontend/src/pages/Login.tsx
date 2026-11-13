import { useState } from "react";
import { api } from "../api";
import { Logo } from "../components/icons";

export default function Login({ setup, onDone }: { setup: boolean; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (setup && pw !== pw2) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await api.post(setup ? "/auth/setup" : "/auth/login", { password: pw });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <form onSubmit={submit}>
        <Logo />
        <h1 style={{ fontSize: "2.2rem" }}>Collander</h1>
        {setup ? (
          <p className="muted">Choose a password to protect your recipes. You'll use it to sign in.</p>
        ) : (
          <p className="muted">Sign in to your recipes.</p>
        )}
        <label className="field" style={{ textAlign: "left" }}>
          Password
          <input
            type="password"
            autoComplete={setup ? "new-password" : "current-password"}
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            autoFocus
            required
            minLength={setup ? 8 : 1}
          />
        </label>
        {setup && (
          <label className="field" style={{ textAlign: "left" }}>
            Confirm password
            <input
              type="password"
              autoComplete="new-password"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
              required
            />
          </label>
        )}
        {error && <div className="alert error">{error}</div>}
        <button className="btn primary" disabled={busy}>
          {setup ? "Set password" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
