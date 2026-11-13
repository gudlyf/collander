import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AISettings, type AuthStatus } from "../api";
import { useApi } from "../hooks";

const PROVIDERS: [string, string][] = [
  ["none", "Off"],
  ["anthropic", "Anthropic Claude"],
  ["openai", "OpenAI (or compatible)"],
  ["google", "Google Gemini"],
  ["ollama", "Ollama (local)"],
];
const KEY_FIELD: Record<string, string> = {
  anthropic: "anthropic_api_key",
  openai: "openai_api_key",
  google: "google_api_key",
};

function AIForm() {
  const { data, setData } = useApi<AISettings>("/settings/ai");
  const defaults = useApi<{ default_models: Record<string, string> }>("/settings/ai/defaults");
  const [provider, setProvider] = useState("none");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [ollama, setOllama] = useState("");
  const [openaiBase, setOpenaiBase] = useState("");
  const [autoTag, setAutoTag] = useState(true);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setProvider(data.provider);
    setModel(data.model ?? "");
    setOllama(data.ollama_base_url);
    setOpenaiBase(data.openai_base_url ?? "");
    setAutoTag(data.auto_tag);
  }, [data]);

  if (!data) return null;
  const keySource = data.keys[provider];
  const defaultModel = defaults.data?.default_models[provider];

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    const body: Record<string, unknown> = { provider, model, auto_tag: autoTag };
    if (provider === "ollama") body.ollama_base_url = ollama;
    if (provider === "openai") body.openai_base_url = openaiBase;
    if (KEY_FIELD[provider] && key) body[KEY_FIELD[provider]] = key;
    try {
      setData(await api.put<AISettings>("/settings/ai", body));
      setKey("");
      setStatus({ kind: "ok", text: "Settings saved." });
    } catch (err) {
      setStatus({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setStatus(null);
    try {
      const r = await api.post<{ model: string }>("/settings/ai/test");
      setStatus({ kind: "ok", text: `Connected to ${r.model}.` });
    } catch (err) {
      setStatus({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="panel stack" onSubmit={save}>
      <h2>AI model</h2>
      <p className="muted small">
        Used to read recipes from web pages, pasted text, photos and Evernote notes, and to suggest tags. Everything
        else works without it.
      </p>
      <label className="field">
        Provider
        <select value={provider} onChange={(e) => setProvider(e.target.value)}>
          {PROVIDERS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      {provider !== "none" && (
        <>
          <label className="field">
            <span>
              Model <span className="hint">(leave empty for {defaultModel ?? "the default"})</span>
            </span>
            <input type="text" value={model} onChange={(e) => setModel(e.target.value)} placeholder={defaultModel} />
          </label>
          {provider === "ollama" && (
            <>
              <label className="field">
                Ollama address
                <input type="url" value={ollama} onChange={(e) => setOllama(e.target.value)} />
              </label>
              <p className="small muted">
                For photo import, use a vision model such as <code>llama3.2-vision</code> or <code>qwen2.5vl</code>.
              </p>
            </>
          )}
          {provider === "openai" && (
            <label className="field">
              <span>
                Base URL <span className="hint">(optional, for OpenAI-compatible servers)</span>
              </span>
              <input type="url" value={openaiBase} onChange={(e) => setOpenaiBase(e.target.value)} placeholder="https://api.openai.com/v1" />
            </label>
          )}
          {KEY_FIELD[provider] && (
            <label className="field">
              <span>
                API key{" "}
                <span className="hint">
                  {keySource === "env"
                    ? "(set by an environment variable)"
                    : keySource === "db"
                      ? "(saved; enter a new one to replace it)"
                      : ""}
                </span>
              </span>
              <input
                type="password"
                autoComplete="off"
                value={key}
                disabled={keySource === "env"}
                onChange={(e) => setKey(e.target.value)}
                placeholder={keySource ? "••••••••" : ""}
              />
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={autoTag} onChange={(e) => setAutoTag(e.target.checked)} />
            Let the AI choose tags when importing from a link
          </label>
        </>
      )}
      {status && <div className={`alert ${status.kind === "error" ? "error" : ""}`}>{status.text}</div>}
      <div className="row">
        <button className="btn primary" disabled={busy}>
          Save
        </button>
        {data.provider !== "none" && (
          <button type="button" className="btn" onClick={test} disabled={busy}>
            Test connection
          </button>
        )}
      </div>
    </form>
  );
}

function PasswordForm({ fromEnv }: { fromEnv: boolean }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  if (fromEnv)
    return (
      <div className="panel stack">
        <h2>Password</h2>
        <p className="muted">The password is set with COLLANDER_PASSWORD. Change it there and restart.</p>
      </div>
    );
  return (
    <form
      className="panel stack"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.post("/auth/password", { current_password: current, new_password: next });
          setMsg({ kind: "", text: "Password changed. Other devices will need to sign in again." });
          setCurrent("");
          setNext("");
        } catch (err) {
          setMsg({ kind: "error", text: (err as Error).message });
        }
      }}
    >
      <h2>Password</h2>
      <label className="field">
        Current password
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label className="field">
        New password
        <input type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      {msg && <div className={`alert ${msg.kind}`}>{msg.text}</div>}
      <div>
        <button className="btn">Change password</button>
      </div>
    </form>
  );
}

export default function Settings({ auth }: { auth: AuthStatus }) {
  return (
    <div className="stack" style={{ maxWidth: 720, gap: 24 }}>
      <h1>Settings</h1>
      <AIForm />
      <div className="panel stack">
        <h2>Backup</h2>
        <p className="muted small">
          Download every recipe, note and modification as one file. Restore it from{" "}
          <Link to="/import">Import → Backup file</Link>.
        </p>
        <div className="row">
          <a className="btn" href="/api/recipes/export" download>
            Download backup
          </a>
          <a className="btn ghost" href="/api/recipes/export?images=false" download>
            Without photos
          </a>
        </div>
      </div>
      <div className="panel stack">
        <h2>Tags</h2>
        <p className="muted small">Rename, merge, or delete tags.</p>
        <div>
          <Link to="/tags" className="btn">
            Manage tags
          </Link>
        </div>
      </div>
      <PasswordForm fromEnv={auth.password_from_env} />
      <div>
        <button
          className="btn ghost"
          onClick={async () => {
            await api.post("/auth/logout");
            window.location.href = "/";
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
