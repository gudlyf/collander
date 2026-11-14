import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type AISettings, type EnexNotePreview, type ImportJob, type QueueItem } from "../api";
import { CameraIcon, TrashIcon } from "../components/icons";
import TagInput from "../components/TagInput";
import { pokeQueue, useApi, useTags } from "../hooks";

type Tab = "link" | "photo" | "text" | "evernote" | "bundle";

/** Upload with progress (fetch can't report upload progress). */
function upload<T>(path: string, form: FormData, onProgress: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* empty */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(new Error((data as { detail?: string })?.detail ?? `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload failed. Check your connection."));
    xhr.send(form);
  });
}

function QueuePanel({ items }: { items: QueueItem[] }) {
  if (!items.length) return null;
  const finished = items.some((i) => i.status === "done" || i.status === "failed");
  const label: Record<QueueItem["status"], string> = {
    queued: "Waiting",
    processing: "Reading…",
    done: "Added",
    failed: "Failed",
  };
  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="spread">
        <h2>Import queue</h2>
        {finished && (
          <button
            className="btn ghost small"
            onClick={async () => {
              await api.post("/queue/clear");
              pokeQueue();
            }}
          >
            Clear finished
          </button>
        )}
      </div>
      <div className="queue" aria-live="polite">
        {items.map((i) => (
          <div key={i.id} className="queue-item">
            <span className={`status ${i.status}`} aria-hidden="true" />
            <div style={{ minWidth: 0 }}>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {i.status === "done" && i.recipe_id ? <Link to={`/r/${i.recipe_id}`}>{i.label}</Link> : i.label}
              </div>
              <div className="small muted">
                {label[i.status]} · {i.kind}
                {i.error && <span style={{ color: "var(--danger)" }}> · {i.error}</span>}
                {i.warnings.length > 0 && <span> · {i.warnings[0]}</span>}
              </div>
            </div>
            <div className="row" style={{ gap: 4 }}>
              {i.status === "done" && i.recipe_id && (
                <Link className="btn small" to={`/r/${i.recipe_id}`}>
                  Review
                </Link>
              )}
              {i.status === "failed" && (
                <button
                  className="btn small"
                  onClick={async () => {
                    await api.post(`/queue/${i.id}/retry`);
                    pokeQueue();
                  }}
                >
                  Retry
                </button>
              )}
              {i.status !== "processing" && (
                <button
                  className="btn ghost icon"
                  aria-label="Remove from queue"
                  onClick={async () => {
                    await api.del(`/queue/${i.id}`);
                    pokeQueue();
                  }}
                >
                  <TrashIcon />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function LinkTab({ aiOn }: { aiOn: boolean }) {
  const [params] = useSearchParams();
  const shared = params.get("url") || (params.get("text") ?? "").match(/https?:\/\/\S+/)?.[0] || "";
  const [url, setUrl] = useState(shared);
  const [tags, setTags] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allTags = useTags();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/queue/url", { url, tags });
      setMsg(`Queued ${url}. Paste another link anytime.`);
      setUrl("");
      pokeQueue();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form onSubmit={submit} className="stack">
      <p className="muted">
        Paste a link to a recipe page. Collander reads the page's recipe data, or has{" "}
        {aiOn ? "your AI model" : "a basic parser (turn on AI in Settings for better results)"} pick out the recipe.
      </p>
      <label className="field">
        Recipe link
        <input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" autoFocus />
      </label>
      <label className="field">
        <span>
          Extra tags <span className="hint">(optional)</span>
        </span>
        <TagInput value={tags} onChange={setTags} suggestions={(allTags.data ?? []).map((t) => t.name)} />
      </label>
      {error && <div className="alert error">{error}</div>}
      {msg && <div className="alert">{msg}</div>}
      <div>
        <button className="btn primary" disabled={!url.trim()}>
          Import link
        </button>
      </div>
    </form>
  );
}

function PhotoTab({ aiOn }: { aiOn: boolean }) {
  const [files, setFiles] = useState<File[]>([]);
  const [hint, setHint] = useState("");
  const [keep, setKeep] = useState(false);
  const [tags, setTags] = useState<string[]>([]);
  const [progress, setProgress] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const pickRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);
  const allTags = useTags();
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  if (!aiOn)
    return (
      <div className="alert warn">
        Reading recipes from photos needs an AI model. <Link to="/settings">Choose one in Settings</Link>.
      </div>
    );

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const imgs = Array.from(list).filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));
    setFiles((prev) => [...prev, ...imgs].slice(0, 8));
    setMsg(null);
  };

  const submit = async () => {
    setError(null);
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("hint", hint);
    form.append("keep_photo", String(keep));
    form.append("tags", tags.join(","));
    try {
      setProgress(0);
      await upload("/queue/photo", form, setProgress);
      setMsg(`Sent ${files.length} photo${files.length > 1 ? "s" : ""}. You can add the next recipe now.`);
      setFiles([]);
      setHint("");
      pokeQueue();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
    }
  };

  return (
    <div className="stack">
      <p className="muted">
        Snap a recipe card, cookbook page, or screenshot. Several photos of one recipe are read together, in order.
        Each upload is queued, so you can keep adding recipes while earlier ones are read.
      </p>
      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          addFiles(e.dataTransfer.files);
        }}
      >
        <CameraIcon width={36} height={36} />
        <div className="row" style={{ justifyContent: "center" }}>
          <button type="button" className="btn primary" onClick={() => camRef.current?.click()}>
            Take a photo
          </button>
          <button type="button" className="btn" onClick={() => pickRef.current?.click()}>
            Choose photos
          </button>
        </div>
        <span className="small muted">or drop images here</span>
        <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => addFiles(e.target.files)} />
        <input ref={pickRef} type="file" accept="image/*,.heic,.heif" multiple hidden onChange={(e) => addFiles(e.target.files)} />
      </div>
      {files.length > 0 && (
        <>
          <div className="photo-strip">
            {previews.map((src, i) => (
              <figure key={src}>
                <img src={src} alt={`Page ${i + 1}`} />
                <button
                  type="button"
                  className="btn icon small"
                  aria-label={`Remove page ${i + 1}`}
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                >
                  ×
                </button>
              </figure>
            ))}
          </div>
          <label className="field">
            <span>
              Note for the reader <span className="hint">(optional)</span>
            </span>
            <input type="text" value={hint} onChange={(e) => setHint(e.target.value)} placeholder="e.g. Grandma's handwriting; it's the pie on the left page" />
          </label>
          <label className="field">
            <span>
              Extra tags <span className="hint">(optional)</span>
            </span>
            <TagInput value={tags} onChange={setTags} suggestions={(allTags.data ?? []).map((t) => t.name)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} />
            Use the first photo as the recipe's picture
          </label>
          {progress !== null && (
            <div className="progress" aria-label="Upload progress">
              <div style={{ width: `${progress}%` }} />
            </div>
          )}
          <div>
            <button className="btn primary" onClick={submit} disabled={progress !== null}>
              Read {files.length > 1 ? `${files.length} photos as one recipe` : "this photo"}
            </button>
          </div>
        </>
      )}
      {error && <div className="alert error">{error}</div>}
      {msg && <div className="alert">{msg}</div>}
    </div>
  );
}

function TextTab({ aiOn }: { aiOn: boolean }) {
  const [params] = useSearchParams();
  const [text, setText] = useState(params.get("text") && !params.get("url") ? params.get("text")! : "");
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/queue/text", { text, source_url: url || null });
      setMsg("Queued. It will appear in your recipes when it's ready.");
      setText("");
      setUrl("");
      pokeQueue();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form onSubmit={submit} className="stack">
      <p className="muted">
        Paste a recipe from an email, a document, or a site that blocks importing.{" "}
        {aiOn ? "Your AI model will structure it." : "Without AI, headings like “Ingredients” and “Directions” are used to split it."}
      </p>
      <label className="field">
        Recipe text
        <textarea rows={14} required value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <label className="field">
        <span>
          Where it's from <span className="hint">(optional link)</span>
        </span>
        <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
      </label>
      {error && <div className="alert error">{error}</div>}
      {msg && <div className="alert">{msg}</div>}
      <div>
        <button className="btn primary" disabled={!text.trim()}>
          Import text
        </button>
      </div>
    </form>
  );
}

export function JobProgress({ jobId, onDone }: { jobId: number; onDone?: () => void }) {
  const [job, setJob] = useState<ImportJob | null>(null);
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      const j = await api.get<ImportJob>(`/import/jobs/${jobId}`);
      if (stop) return;
      setJob(j);
      if (j.status === "running") window.setTimeout(tick, 1500);
      else onDone?.();
    };
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!job) return null;
  const pct = job.total ? Math.round((job.processed / job.total) * 100) : 0;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="spread">
        <strong>
          {job.kind === "ai-check"
            ? job.status === "running"
              ? "Checking…"
              : job.status === "done"
                ? "Check finished"
                : `Check ${job.status}`
            : job.kind === "icons"
              ? job.status === "running"
                ? "Making icons…"
                : job.status === "done"
                  ? "Icons finished"
                  : `Icons ${job.status}`
              : job.status === "running"
                ? "Importing…"
                : job.status === "done"
                  ? "Import finished"
                  : `Import ${job.status}`}
        </strong>
        <span className="small muted">
          {job.processed}/{job.total} processed · {job.imported} {job.kind === "ai-check" ? "checked" : job.kind === "icons" ? "made" : "added"} ·{" "}
          {job.failed} failed
        </span>
      </div>
      <div className="progress">
        <div style={{ width: `${pct}%` }} />
      </div>
      {job.log && <pre className="log">{job.log}</pre>}
      {job.status === "done" &&
        (job.kind === "icons" ? (
          <Link to="/" className="btn small" style={{ justifySelf: "start" }}>
            See recipes
          </Link>
        ) : (
          <Link to="/?review=1" className="btn small" style={{ justifySelf: "start" }}>
            See imported recipes
          </Link>
        ))}
    </div>
  );
}

function EvernoteTab({ aiOn }: { aiOn: boolean }) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [notes, setNotes] = useState<EnexNotePreview[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const [useAi, setUseAi] = useState(aiOn);
  const [tags, setTags] = useState<string[]>(["evernote"]);
  const [running, setRunning] = useState(false);

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setError(null);
    const form = new FormData();
    form.append("file", f);
    try {
      setProgress(0);
      const res = await upload<{ job: ImportJob; notes: EnexNotePreview[] }>("/import/enex", form, setProgress);
      setJobId(res.job.id);
      setNotes(res.notes);
      setSelected(new Set(res.notes.filter((n) => n.likely_recipe).map((n) => n.index)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProgress(null);
    }
  };

  const visible = notes.filter(
    (n) => !filter || `${n.title} ${n.tags.join(" ")} ${n.snippet}`.toLowerCase().includes(filter.toLowerCase()),
  );

  if (running && jobId) return <JobProgress jobId={jobId} />;

  return (
    <div className="stack">
      <p className="muted">
        In Evernote, select the notes or notebook and choose <em>Export</em> → <em>ENEX</em>. Upload the .enex file
        here, then pick which notes are recipes.
      </p>
      {!notes.length && (
        <label className="field">
          Evernote export (.enex)
          <input type="file" accept=".enex,application/xml,text/xml" onChange={(e) => onFile(e.target.files?.[0])} />
        </label>
      )}
      {progress !== null && (
        <div className="progress">
          <div style={{ width: `${progress}%` }} />
        </div>
      )}
      {notes.length > 0 && (
        <>
          <div className="spread">
            <strong>
              {selected.size} of {notes.length} notes selected
            </strong>
            <div className="row">
              <button className="btn small" onClick={() => setSelected(new Set(notes.filter((n) => n.likely_recipe).map((n) => n.index)))}>
                Likely recipes
              </button>
              <button className="btn small" onClick={() => setSelected(new Set(notes.map((n) => n.index)))}>
                All
              </button>
              <button className="btn small" onClick={() => setSelected(new Set())}>
                None
              </button>
            </div>
          </div>
          <input type="search" placeholder="Filter notes" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className="enex-list">
            {visible.map((n) => (
              <label key={n.index}>
                <input
                  type="checkbox"
                  className="check"
                  checked={selected.has(n.index)}
                  onChange={(e) => {
                    const s = new Set(selected);
                    e.target.checked ? s.add(n.index) : s.delete(n.index);
                    setSelected(s);
                  }}
                />
                <div>
                  <div>
                    <strong>{n.title}</strong>{" "}
                    {n.image_count > 0 && <span className="small muted">· {n.image_count} image{n.image_count > 1 ? "s" : ""}</span>}
                    {n.tags.length > 0 && <span className="small muted"> · {n.tags.join(", ")}</span>}
                  </div>
                  <div className="snip">{n.snippet || "(no text)"}</div>
                </div>
              </label>
            ))}
          </div>
          <label className="check">
            <input type="checkbox" checked={useAi} disabled={!aiOn} onChange={(e) => setUseAi(e.target.checked)} />
            Use AI to structure each note{aiOn ? "" : " (set up AI in Settings first)"}. Notes that are mostly a photo
            are read from the photo.
          </label>
          <label className="field">
            Add these tags to every imported recipe
            <TagInput value={tags} onChange={setTags} />
          </label>
          {error && <div className="alert error">{error}</div>}
          <div>
            <button
              className="btn primary"
              disabled={!selected.size}
              onClick={async () => {
                setError(null);
                try {
                  await api.post(`/import/enex/${jobId}/run`, {
                    indexes: [...selected],
                    use_ai: useAi,
                    extra_tags: tags,
                  });
                  setRunning(true);
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              Import {selected.size} note{selected.size === 1 ? "" : "s"}
            </button>
          </div>
        </>
      )}
      {error && !notes.length && <div className="alert error">{error}</div>}
    </div>
  );
}

function BundleTab({ aiOn }: { aiOn: boolean }) {
  const [skip, setSkip] = useState(true);
  const [aiCheck, setAiCheck] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (jobId) return <JobProgress jobId={jobId} />;
  return (
    <div className="stack">
      <p className="muted">
        Restore a Collander backup, or load a bundle prepared elsewhere (for example, recipes gathered from Google
        Docs). Download a backup from Settings.
      </p>
      <label className="check">
        <input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} />
        Skip recipes I already have (same title, link and ingredients)
      </label>
      <label className="check">
        <input type="checkbox" checked={aiCheck} disabled={!aiOn} onChange={(e) => setAiCheck(e.target.checked)} />
        Tidy and check each recipe with AI{aiOn ? "" : " (set up AI in Settings first)"}
      </label>
      {aiCheck && (
        <p className="small muted" style={{ margin: 0 }}>
          The AI cleans up formatting and suggests tags, but never changes quantities or wording. Problems it
          finds are added as a note and the recipe is marked Needs review. This takes a while for large files.
        </p>
      )}
      <label className="field">
        Collander bundle (.json)
        <input
          type="file"
          accept=".json,application/json"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            setError(null);
            const form = new FormData();
            form.append("file", f);
            form.append("skip_duplicates", String(skip));
            form.append("ai_check", String(aiCheck));
            try {
              setProgress(0);
              const job = await upload<ImportJob>("/import/bundle", form, setProgress);
              setJobId(job.id);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setProgress(null);
            }
          }}
        />
      </label>
      {progress !== null && (
        <div className="progress">
          <div style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && <div className="alert error">{error}</div>}
    </div>
  );
}

export default function Import({ queueItems }: { queueItems: QueueItem[] }) {
  const [params] = useSearchParams();
  const sharedText = params.get("text") && !params.get("url") && !/https?:\/\//.test(params.get("text")!);
  const [tab, setTab] = useState<Tab>(sharedText ? "text" : "link");
  const ai = useApi<AISettings>("/settings/ai");
  const aiOn = !!ai.data && ai.data.provider !== "none";

  const tabs: [Tab, string][] = [
    ["link", "Link"],
    ["photo", "Photo"],
    ["text", "Paste text"],
    ["evernote", "Evernote"],
    ["bundle", "Backup file"],
  ];

  return (
    <div className="stack" style={{ gap: 28, maxWidth: 860 }}>
      <h1>Import recipes</h1>
      <div>
        <div className="tabs" role="tablist">
          {tabs.map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </div>
        {ai.data && (
          <>
            {tab === "link" && <LinkTab aiOn={aiOn} />}
            {tab === "photo" && <PhotoTab aiOn={aiOn} />}
            {tab === "text" && <TextTab aiOn={aiOn} />}
            {tab === "evernote" && <EvernoteTab aiOn={aiOn} />}
            {tab === "bundle" && <BundleTab aiOn={aiOn} />}
          </>
        )}
      </div>
      <QueuePanel items={queueItems} />
    </div>
  );
}
