import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, emptyRecipe, imageUrl, toInput, type IngredientIn, type Recipe, type RecipeIn } from "../api";
import { DownIcon, TrashIcon, UpIcon } from "../components/icons";
import TagInput from "../components/TagInput";
import { useTags } from "../hooks";

type Line = IngredientIn;

function linesFromText(text: string, prevSection: string | null): Line[] {
  const out: Line[] = [];
  let section = prevSection;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim();
    if (!line) continue;
    if (line.endsWith(":") && line.length < 60) {
      section = line.slice(0, -1).trim();
      continue;
    }
    out.push({ text: line, section });
  }
  return out;
}

function LinesEditor({
  label,
  lines,
  onChange,
  multiline,
}: {
  label: string;
  lines: Line[];
  onChange: (l: Line[]) => void;
  multiline?: boolean;
}) {
  const [bulk, setBulk] = useState("");
  const [showBulk, setShowBulk] = useState(lines.length === 0);
  const [openMods, setOpenMods] = useState<Set<number>>(new Set());
  const useSections = lines.some((l) => l.section);
  const [sections, setSections] = useState(useSections);

  const set = (i: number, patch: Partial<Line>) =>
    onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= lines.length) return;
    const next = [...lines];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  const Field = multiline ? "textarea" : "input";

  return (
    <section className="stack" style={{ gap: 10 }}>
      <div className="spread">
        <h2>{label}</h2>
        <div className="row">
          <label className="check small">
            <input type="checkbox" checked={sections} onChange={(e) => setSections(e.target.checked)} />
            Groups
          </label>
          <button type="button" className="btn small" onClick={() => setShowBulk((s) => !s)}>
            {showBulk ? "Hide paste box" : "Paste several"}
          </button>
        </div>
      </div>
      {showBulk && (
        <div className="stack" style={{ gap: 8 }}>
          <textarea
            rows={6}
            value={bulk}
            onChange={(e) => setBulk(e.target.value)}
            placeholder={
              multiline
                ? "One step per line.\nA line ending in ':' starts a group."
                : "One ingredient per line, e.g.\n2 cups flour\n1 tsp salt\nFor the glaze:\n1 cup powdered sugar"
            }
            aria-label={`Paste ${label.toLowerCase()}`}
          />
          <div>
            <button
              type="button"
              className="btn small"
              disabled={!bulk.trim()}
              onClick={() => {
                const added = linesFromText(bulk, lines.at(-1)?.section ?? null);
                if (added.some((l) => l.section)) setSections(true);
                onChange([...lines, ...added]);
                setBulk("");
                setShowBulk(false);
              }}
            >
              Add these lines
            </button>
          </div>
        </div>
      )}
      <div className="edit-rows">
        {lines.map((l, i) => {
          const modded = !!(l.override_text || l.omitted || l.override_note);
          const open = openMods.has(i) || modded;
          return (
            <div key={i} className={`edit-row ${modded || l.is_addition ? "has-mod" : ""}`}>
              <div className="main">
                <div className="line-inputs">
                  {sections && (
                    <input
                      type="text"
                      className="section-input"
                      placeholder="Group"
                      value={l.section ?? ""}
                      onChange={(e) => set(i, { section: e.target.value || null })}
                      aria-label="Group"
                      title="Group, e.g. For the sauce"
                    />
                  )}
                  <Field
                    type="text"
                    rows={2}
                    value={l.text}
                    onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
                      set(i, { text: e.target.value })
                    }
                    aria-label={`${label} ${i + 1}`}
                  />
                </div>
                {open && (
                  <div className="mod-fields">
                    <label htmlFor={`ov-${label}-${i}`}>Your change (original stays visible)</label>
                    <Field
                      id={`ov-${label}-${i}`}
                      type="text"
                      rows={2}
                      value={l.override_text ?? ""}
                      placeholder="e.g. 2 cups almond milk"
                      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
                        set(i, { override_text: e.target.value || null })
                      }
                    />
                    <input
                      type="text"
                      value={l.override_note ?? ""}
                      placeholder="Why (optional)"
                      onChange={(e) => set(i, { override_note: e.target.value || null })}
                      aria-label="Reason for the change"
                    />
                    <div className="row">
                      <label className="check small">
                        <input
                          type="checkbox"
                          checked={!!l.omitted}
                          onChange={(e) => set(i, { omitted: e.target.checked })}
                        />
                        Leave this out
                      </label>
                      <label className="check small">
                        <input
                          type="checkbox"
                          checked={!!l.is_addition}
                          onChange={(e) => set(i, { is_addition: e.target.checked })}
                        />
                        This is my addition
                      </label>
                    </div>
                  </div>
                )}
              </div>
              <div className="tools">
                {!open && (
                  <button
                    type="button"
                    className="btn ghost small"
                    style={{ color: "var(--mod)" }}
                    onClick={() => setOpenMods((s) => new Set(s).add(i))}
                    title="Record a change while keeping the original"
                  >
                    Modify
                  </button>
                )}
                <button type="button" className="btn ghost icon" onClick={() => move(i, -1)} aria-label="Move up">
                  <UpIcon />
                </button>
                <button type="button" className="btn ghost icon" onClick={() => move(i, 1)} aria-label="Move down">
                  <DownIcon />
                </button>
                <button
                  type="button"
                  className="btn ghost icon danger"
                  onClick={() => onChange(lines.filter((_, j) => j !== i))}
                  aria-label="Remove line"
                >
                  <TrashIcon />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <div>
        <button
          type="button"
          className="btn small"
          onClick={() => onChange([...lines, { text: "", section: lines.at(-1)?.section ?? null }])}
        >
          + Add line
        </button>
      </div>
    </section>
  );
}

function readAsDataUri(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

export default function RecipeEdit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const tags = useTags();
  const [form, setForm] = useState<RecipeIn | null>(id ? null : (location.state?.draft ?? emptyRecipe()));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [imageInput, setImageInput] = useState("");

  useEffect(() => {
    if (!id) return;
    api
      .get<Recipe>(`/recipes/${id}`)
      .then((r) => setForm(toInput(r)))
      .catch((e) => setError(e.message));
  }, [id]);

  if (!form) return error ? <div className="alert error">{error}</div> : null;

  const set = <K extends keyof RecipeIn>(k: K, v: RecipeIn[K]) => setForm({ ...form, [k]: v });
  const text = (k: keyof RecipeIn) => ({
    value: (form[k] as string | null) ?? "",
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      set(k, (e.target.value || null) as never),
  });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: RecipeIn = {
      ...form,
      title: form.title.trim(),
      ingredients: form.ingredients.filter((l) => l.text.trim()),
      steps: form.steps.filter((l) => l.text.trim()),
    };
    try {
      const saved = id
        ? await api.put<Recipe>(`/recipes/${id}`, body)
        : await api.post<Recipe>("/recipes", body);
      navigate(`/r/${saved.id}`, { replace: !!id });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const suggest = async () => {
    setSuggesting(true);
    setError(null);
    try {
      const sug = await api.post<string[]>("/recipes/suggest-tags", { ...form, title: form.title || "Untitled" });
      set("tags", Array.from(new Set([...form.tags, ...sug])));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSuggesting(false);
    }
  };

  const img = imageUrl(form.image);

  return (
    <form className="editor" onSubmit={save}>
      <h1>{id ? "Edit recipe" : "New recipe"}</h1>
      <label className="field">
        Title
        <input type="text" required value={form.title} onChange={(e) => set("title", e.target.value)} autoFocus={!id} />
      </label>
      <label className="field">
        Description
        <textarea rows={3} value={form.description} onChange={(e) => set("description", e.target.value)} />
      </label>
      <div className="editor-grid">
        <label className="field">
          Serves / makes
          <input type="text" {...text("servings")} placeholder="4 servings" />
        </label>
        <label className="field">
          Prep time
          <input type="text" {...text("prep_time")} placeholder="15 min" />
        </label>
        <label className="field">
          Cook time
          <input type="text" {...text("cook_time")} />
        </label>
        <label className="field">
          Total time
          <input type="text" {...text("total_time")} />
        </label>
      </div>
      <div className="editor-grid">
        <label className="field">
          Source link
          <input type="url" {...text("source_url")} placeholder="https://" />
        </label>
        <label className="field">
          Source name
          <input type="text" {...text("source_name")} placeholder="Grandma, a cookbook…" />
        </label>
      </div>

      <section className="stack" style={{ gap: 10 }}>
        <h2>Photo</h2>
        <div className="row" style={{ alignItems: "flex-start" }}>
          {img && <img src={img} alt="" style={{ width: 160, borderRadius: 10 }} />}
          <div className="stack" style={{ gap: 8, flex: 1, minWidth: 240 }}>
            <input
              type="file"
              accept="image/*"
              aria-label="Upload a photo"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) set("image", await readAsDataUri(f));
              }}
            />
            <div className="row">
              <input
                type="url"
                placeholder="…or paste an image link"
                value={imageInput}
                onChange={(e) => setImageInput(e.target.value)}
                style={{ flex: 1 }}
              />
              <button type="button" className="btn small" disabled={!imageInput} onClick={() => set("image", imageInput)}>
                Use link
              </button>
            </div>
            {img && (
              <div>
                <button type="button" className="btn ghost small danger" onClick={() => set("image", null)}>
                  Remove photo
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="stack" style={{ gap: 10 }}>
        <div className="spread">
          <h2>Tags</h2>
          <button type="button" className="btn small" onClick={suggest} disabled={suggesting}>
            {suggesting ? "Thinking…" : "Suggest tags"}
          </button>
        </div>
        <TagInput value={form.tags} onChange={(t) => set("tags", t)} suggestions={(tags.data ?? []).map((t) => t.name)} />
      </section>

      <LinesEditor label="Ingredients" lines={form.ingredients} onChange={(l) => set("ingredients", l)} />
      <LinesEditor label="Steps" lines={form.steps} onChange={(l) => set("steps", l)} multiline />

      {form.original_text && (
        <details>
          <summary>Original imported text</summary>
          <div className="original-text">{form.original_text}</div>
        </details>
      )}

      <label className="check">
        <input type="checkbox" checked={form.needs_review} onChange={(e) => set("needs_review", e.target.checked)} />
        Needs review
      </label>

      {error && <div className="alert error">{error}</div>}
      <div className="sticky-actions">
        <Link to={id ? `/r/${id}` : "/"} className="btn ghost">
          Cancel
        </Link>
        <button className="btn primary" disabled={busy || !form.title.trim()}>
          {busy ? "Saving…" : "Save recipe"}
        </button>
      </div>
    </form>
  );
}
