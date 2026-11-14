import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AISettings, type AuthStatus, type BuildInfo, type ImageSettings } from "../api";
import { useApi } from "../hooks";
import { JobProgress } from "./Import";

function CheckRecipes() {
  const ai = useApi<AISettings>("/settings/ai");
  const [scope, setScope] = useState<"review" | "all">("review");
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!ai.data || ai.data.provider === "none") return null;
  return (
    <div className="panel stack">
      <h2>Check recipes with AI</h2>
      <p className="muted small">
        Tidies leftover formatting from imports, suggests tags, and flags problems such as an ingredient used in a
        step but missing from the list. Quantities and wording are never changed; anything it finds is added as a
        note and the recipe is marked Needs review. Runs in the background.
      </p>
      {jobId ? (
        <JobProgress jobId={jobId} />
      ) : (
        <div className="row">
          <select value={scope} onChange={(e) => setScope(e.target.value as "review" | "all")} style={{ width: "auto" }}>
            <option value="review">Recipes that need review</option>
            <option value="all">All recipes</option>
          </select>
          <button
            className="btn"
            onClick={async () => {
              setError(null);
              try {
                const job = await api.post<{ id: number }>("/import/ai-check", { scope });
                setJobId(job.id);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Start check
          </button>
        </div>
      )}
      {error && <div className="alert error">{error}</div>}
    </div>
  );
}

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

const ICON_ENGINES: [ImageSettings["provider"], string][] = [
  ["none", "Off"],
  ["svg", "Drawn by the AI model above"],
  ["a1111", "Stable Diffusion server (AUTOMATIC1111 API)"],
  ["openai", "OpenAI image model"],
  ["google", "Google image model"],
];

function IconsForm() {
  const { data, setData, reload } = useApi<ImageSettings>("/settings/images");
  const ai = useApi<AISettings>("/settings/ai");
  const defaults = useApi<{ default_models: Record<string, string> }>("/settings/images/defaults");
  const [provider, setProvider] = useState<ImageSettings["provider"]>("none");
  const [model, setModel] = useState("");
  const [auto, setAuto] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [steps, setSteps] = useState("8");
  const [cfgScale, setCfgScale] = useState("1");
  const [key, setKey] = useState("");
  const [redo, setRedo] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data) return;
    setProvider(data.provider);
    setModel(data.model ?? "");
    setAuto(data.auto);
    setBaseUrl(data.base_url ?? "");
    setSteps(String(data.steps));
    setCfgScale(String(data.cfg_scale));
  }, [data]);

  if (!data || !ai.data) return null;
  const keyField = provider === "openai" || provider === "google" ? `${provider}_api_key` : null;
  const hasKey = keyField ? !!ai.data.keys[provider] : true;
  const placeholder =
    provider === "svg"
      ? (ai.data.effective_model ?? "the AI model above")
      : provider === "a1111"
        ? "the server's current model"
        : defaults.data?.default_models[provider];
  const count = data.missing + (redo ? data.generated : 0);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      if (keyField && key.trim()) {
        ai.setData(await api.put<AISettings>("/settings/ai", { [keyField]: key.trim() }));
        setKey("");
      }
      const body: Record<string, unknown> = { provider, model, auto };
      if (provider === "a1111") {
        body.base_url = baseUrl;
        if (steps.trim()) body.steps = Number(steps);
        if (cfgScale.trim()) body.cfg_scale = Number(cfgScale);
      }
      const next = await api.put<ImageSettings>("/settings/images", body);
      setData(next);
      setStatus(
        next.provider === "none" || next.ready
          ? { kind: "ok", text: "Saved." }
          : { kind: "error", text: `Saved, but icons can't be made yet: ${next.problem}` },
      );
    } catch (err) {
      setStatus({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setStatus(null);
    try {
      const res = await api.post<{ models: string[] }>("/settings/images/test");
      setStatus({ kind: "ok", text: `Connected. Models: ${res.models.join(", ") || "none listed"}.` });
    } catch (err) {
      setStatus({ kind: "error", text: (err as Error).message });
    }
  };

  const start = async () => {
    setStatus(null);
    try {
      const job = await api.post<{ id: number }>("/import/icons", { scope: redo ? "all" : "missing" });
      setJobId(job.id);
    } catch (err) {
      setStatus({ kind: "error", text: (err as Error).message });
    }
  };

  return (
    <form className="panel stack" onSubmit={save}>
      <h2>Recipe icons</h2>
      <p className="muted small">
        Recipes without a photo can get a simple icon in the style of the Collander logo. A photo you add later always
        replaces the icon.
      </p>
      <label className="field">
        Made by
        <select value={provider} onChange={(e) => setProvider(e.target.value as ImageSettings["provider"])}>
          {ICON_ENGINES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </label>
      {provider !== "none" && (
        <>
          {provider === "svg" && (
            <p className="small muted">
              The AI model draws each icon as simple shapes. Works with every provider, including local models, and
              costs about as much as a tag suggestion.
            </p>
          )}
          {provider === "a1111" && (
            <>
              <label className="field">
                Server address
                <input
                  type="url"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="http://host.docker.internal:7860"
                />
              </label>
              <p className="small muted">
                Any server with the AUTOMATIC1111 API: A1111, Forge, or stable-diffusion.cpp's{" "}
                <code>sd-server</code>. Turbo models such as Z-Image Turbo want about 8 steps and CFG 1.
              </p>
              <div className="row">
                <label className="field" style={{ flex: 1 }}>
                  Steps
                  <input type="number" min={1} max={150} value={steps} onChange={(e) => setSteps(e.target.value)} />
                </label>
                <label className="field" style={{ flex: 1 }}>
                  CFG scale
                  <input
                    type="number"
                    min={0}
                    max={30}
                    step={0.5}
                    value={cfgScale}
                    onChange={(e) => setCfgScale(e.target.value)}
                  />
                </label>
              </div>
            </>
          )}
          <label className="field">
            <span>
              Model <span className="hint">(leave empty for {placeholder ?? "the default"})</span>
            </span>
            <input type="text" value={model} onChange={(e) => setModel(e.target.value)} placeholder={placeholder} />
          </label>
          {keyField && !hasKey && (
            <label className="field">
              <span>
                {provider === "openai" ? "OpenAI" : "Google"} API key{" "}
                <span className="hint">(also used by the AI model setting)</span>
              </span>
              <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
            </label>
          )}
          <label className="check">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            Make an icon when I add a recipe without a photo
          </label>
          <p className="small muted">Bulk imports (backups, Evernote) don't make icons; use the button below.</p>
        </>
      )}
      {status && <div className={`alert ${status.kind === "error" ? "error" : ""}`}>{status.text}</div>}
      <div className="row">
        <button className="btn primary" disabled={busy}>
          Save
        </button>
        {data.provider === "a1111" && provider === "a1111" && (
          <button type="button" className="btn" onClick={test} disabled={busy}>
            Test connection
          </button>
        )}
      </div>
      {data.ready && data.provider === provider && (
        <div className="stack" style={{ gap: 8, borderTop: "1px solid var(--line)", paddingTop: 16 }}>
          {jobId ? (
            <JobProgress
              jobId={jobId}
              onDone={() => {
                reload();
              }}
            />
          ) : (
            <>
              <p className="small">
                {data.missing === 1 ? "1 recipe has" : `${data.missing} recipes have`} no photo or icon
                {data.generated > 0 && `; ${data.generated} already ${data.generated === 1 ? "has an icon" : "have icons"}`}.
              </p>
              {data.generated > 0 && (
                <label className="check">
                  <input type="checkbox" checked={redo} onChange={(e) => setRedo(e.target.checked)} />
                  Also replace existing icons
                </label>
              )}
              <div className="row">
                <button type="button" className="btn" disabled={count === 0} onClick={start}>
                  Make {count} {count === 1 ? "icon" : "icons"}
                </button>
              </div>
              <p className="small muted">Runs in the background, one recipe at a time. Photos are never replaced.</p>
            </>
          )}
        </div>
      )}
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

const REPO = "https://github.com/gudlyf/collander";

function About() {
  const { data } = useApi<BuildInfo>("/health");
  if (!data) return null;
  const sha = data.commit;
  return (
    <div className="panel stack">
      <h2>About</h2>
      <dl className="about">
        <dt>Version</dt>
        <dd>{data.version}</dd>
        <dt>Commit</dt>
        <dd>
          {sha ? (
            <a href={`${REPO}/commit/${sha}`} target="_blank" rel="noreferrer" title={sha}>
              <code>{sha.slice(0, 7)}</code>
            </a>
          ) : (
            <span className="muted">Not recorded in this build</span>
          )}
        </dd>
      </dl>
      <p className="muted small">
        <a href={REPO} target="_blank" rel="noreferrer">
          Source code and release notes
        </a>
      </p>
    </div>
  );
}

export default function Settings({ auth }: { auth: AuthStatus }) {
  return (
    <div className="stack" style={{ maxWidth: 720, gap: 24 }}>
      <h1>Settings</h1>
      <AIForm />
      <CheckRecipes />
      <IconsForm />
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
      <About />
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
