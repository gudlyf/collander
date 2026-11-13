import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, imageUrl, toInput, type IngredientIn, type Note, type QueueItem, type Recipe } from "../api";
import { HeartIcon, PencilIcon, PrinterIcon, SunIcon, TrashIcon } from "../components/icons";
import { LineList } from "../components/Lines";
import { useApi } from "../hooks";
import { factorLabel, PRESET_FACTORS, scaleServings } from "../scale";

function Scaler({ factor, setFactor }: { factor: number; setFactor: (f: number) => void }) {
  const custom = !PRESET_FACTORS.includes(factor);
  const [draft, setDraft] = useState(custom ? String(factor) : "");
  return (
    <div className="scaler" role="group" aria-label="Scale recipe">
      {PRESET_FACTORS.map((f) => (
        <button key={f} aria-pressed={factor === f} onClick={() => setFactor(f)}>
          {factorLabel(f)}
        </button>
      ))}
      <input
        type="number"
        inputMode="decimal"
        min={0.1}
        step={0.25}
        placeholder="other"
        aria-label="Custom multiplier"
        value={custom ? String(factor) : draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = parseFloat(e.target.value);
          if (n > 0 && n <= 50) setFactor(n);
        }}
      />
    </div>
  );
}

function Stars({ value, onChange }: { value: number | null; onChange: (v: number) => void }) {
  return (
    <span className="stars" role="group" aria-label="Rating">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          className={value && n <= value ? "on" : ""}
          onClick={() => onChange(value === n ? 0 : n)}
          aria-label={`${n} star${n > 1 ? "s" : ""}`}
        >
          ★
        </button>
      ))}
    </span>
  );
}

function Notes({ recipe, reload }: { recipe: Recipe; reload: () => void }) {
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    await api.post(`/recipes/${recipe.id}/notes`, { text });
    setText("");
    reload();
  };

  return (
    <section className="stack">
      <h2>Notes</h2>
      <form onSubmit={add} className="stack no-print" style={{ gap: 8 }}>
        <textarea
          rows={2}
          placeholder="Add a note: what worked, what to try next time…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="New note"
        />
        <div>
          <button className="btn small" disabled={!text.trim()}>
            Add note
          </button>
        </div>
      </form>
      <div className="notes-list">
        {recipe.notes.map((n: Note) =>
          editing === n.id ? (
            <div key={n.id} className="stack" style={{ gap: 8 }}>
              <textarea rows={3} value={editText} onChange={(e) => setEditText(e.target.value)} />
              <div className="row">
                <button
                  className="btn primary small"
                  onClick={async () => {
                    await api.put(`/recipes/${recipe.id}/notes/${n.id}`, { text: editText });
                    setEditing(null);
                    reload();
                  }}
                >
                  Save note
                </button>
                <button className="btn ghost small" onClick={() => setEditing(null)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div key={n.id} className="note">
              {n.text}
              <footer>
                {new Date(n.created_at + "Z").toLocaleDateString()}
                <button
                  className="btn ghost small no-print"
                  onClick={() => {
                    setEditing(n.id);
                    setEditText(n.text);
                  }}
                >
                  Edit
                </button>
                <button
                  className="btn ghost small danger no-print"
                  onClick={async () => {
                    await api.del(`/recipes/${recipe.id}/notes/${n.id}`);
                    reload();
                  }}
                >
                  Delete
                </button>
              </footer>
            </div>
          ),
        )}
      </div>
    </section>
  );
}

function ReviewBanner({ recipe, onReviewed }: { recipe: Recipe; onReviewed: () => void }) {
  const { data } = useApi<QueueItem[]>(`/queue?recipe_id=${recipe.id}`);
  const [zoom, setZoom] = useState<string | null>(null);
  const item = data?.[0];
  return (
    <div className="review-banner no-print">
      <div className="spread">
        <strong>
          {recipe.source_kind === "photo"
            ? "Read from a photo. Check it against the original before you cook."
            : "Imported automatically. Give it a quick check."}
        </strong>
        <div className="row">
          <Link className="btn small" to={`/r/${recipe.id}/edit`}>
            Edit
          </Link>
          <button className="btn primary small" onClick={onReviewed}>
            Mark as reviewed
          </button>
        </div>
      </div>
      {item?.warnings.map((w) => (
        <div key={w} className="small">
          {w}
        </div>
      ))}
      {item && item.file_count > 0 && (
        <div className="photos">
          {Array.from({ length: item.file_count }, (_, n) => {
            const src = `/api/queue/${item.id}/photos/${n}`;
            return <img key={n} src={src} alt={`Original photo ${n + 1}`} onClick={() => setZoom(src)} />;
          })}
        </div>
      )}
      {zoom && (
        <div className="lightbox" onClick={() => setZoom(null)} role="dialog" aria-label="Photo">
          <img src={zoom} alt="Original photo" />
        </div>
      )}
    </div>
  );
}

export default function RecipeView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: recipe, setData, error, reload } = useApi<Recipe>(`/recipes/${id}`);
  const [factor, setFactor] = useState(1);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [awake, setAwake] = useState(false);
  const wakeLock = useRef<WakeLockSentinel | null>(null);

  useEffect(() => {
    return () => {
      wakeLock.current?.release();
    };
  }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!recipe) return null;

  const save = async (patch: Partial<ReturnType<typeof toInput>>) => {
    const body = { ...toInput(recipe), ...patch };
    const updated = await api.put<Recipe>(`/recipes/${recipe.id}`, body);
    setData(updated);
  };
  const patch = async (body: Record<string, unknown>) => {
    setData(await api.patch<Recipe>(`/recipes/${recipe.id}`, body));
  };

  const toggleAwake = async () => {
    if (awake) {
      await wakeLock.current?.release();
      wakeLock.current = null;
      setAwake(false);
    } else if ("wakeLock" in navigator) {
      try {
        wakeLock.current = await navigator.wakeLock.request("screen");
        setAwake(true);
        wakeLock.current.addEventListener("release", () => setAwake(false));
      } catch {
        /* not allowed */
      }
    }
  };

  const hero = imageUrl(recipe.image);
  const servings = scaleServings(recipe.servings, factor);
  const facts = [
    ["Serves", servings],
    ["Prep", recipe.prep_time],
    ["Cook", recipe.cook_time],
    ["Total", recipe.total_time],
  ].filter(([, v]) => v);

  return (
    <article>
      {recipe.needs_review && (
        <ReviewBanner recipe={recipe} onReviewed={() => patch({ needs_review: false })} />
      )}
      <div className="recipe-head" style={hero ? undefined : { gridTemplateColumns: "1fr" }}>
        <div className="recipe-title">
          <h1>{recipe.title}</h1>
          {recipe.description && <p className="desc">{recipe.description}</p>}
          {facts.length > 0 && (
            <dl className="facts">
              {facts.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          )}
          {recipe.source_url && (
            <div className="small">
              From{" "}
              <a href={recipe.source_url} target="_blank" rel="noreferrer noopener">
                {recipe.source_name || new URL(recipe.source_url).hostname}
              </a>
            </div>
          )}
          {recipe.tags.length > 0 && (
            <div className="tagbar">
              {recipe.tags.map((t) => (
                <Link key={t} to={`/?tag=${encodeURIComponent(t)}`} className="chip">
                  {t}
                </Link>
              ))}
            </div>
          )}
          <div className="row no-print">
            <button
              className="btn icon"
              onClick={() => patch({ favorite: !recipe.favorite })}
              aria-pressed={recipe.favorite}
              aria-label={recipe.favorite ? "Remove from favorites" : "Add to favorites"}
              title="Favorite"
              style={recipe.favorite ? { color: "var(--danger)" } : undefined}
            >
              <HeartIcon filled={recipe.favorite} />
            </button>
            <Stars value={recipe.rating} onChange={(v) => patch({ rating: v })} />
            <Link to={`/r/${recipe.id}/edit`} className="btn">
              <PencilIcon /> Edit
            </Link>
            <button className="btn icon" onClick={() => window.print()} aria-label="Print" title="Print">
              <PrinterIcon />
            </button>
            {"wakeLock" in navigator && (
              <button
                className="btn icon"
                onClick={toggleAwake}
                aria-pressed={awake}
                title={awake ? "Screen stays on" : "Keep screen on while cooking"}
                aria-label="Keep screen on"
                style={awake ? { color: "var(--cobalt)", borderColor: "var(--cobalt)" } : undefined}
              >
                <SunIcon />
              </button>
            )}
            {confirmDelete ? (
              <>
                <button
                  className="btn danger"
                  onClick={async () => {
                    await api.del(`/recipes/${recipe.id}`);
                    navigate("/");
                  }}
                >
                  Delete for good
                </button>
                <button className="btn ghost" onClick={() => setConfirmDelete(false)}>
                  Keep
                </button>
              </>
            ) : (
              <button
                className="btn icon ghost"
                onClick={() => setConfirmDelete(true)}
                aria-label="Delete recipe"
                title="Delete"
              >
                <TrashIcon />
              </button>
            )}
          </div>
        </div>
        {hero && (
          <div className="hero">
            <img src={hero} alt="" />
          </div>
        )}
      </div>

      <div className="cook">
        <section className="ingredients">
          <div className="section-head">
            <h2>Ingredients</h2>
            <Scaler factor={factor} setFactor={setFactor} />
          </div>
          {factor !== 1 && (
            <p className="scale-note">
              Showing {factorLabel(factor)} quantities. Amounts mentioned inside the steps are not scaled.
            </p>
          )}
          {recipe.ingredients.length ? (
            <LineList
              lines={recipe.ingredients}
              kind="ingredient"
              factor={factor}
              onChange={(lines: IngredientIn[]) => save({ ingredients: lines })}
            />
          ) : (
            <p className="muted">No ingredients yet.</p>
          )}
        </section>
        <div className="stack" style={{ gap: 40 }}>
          <section>
            <div className="section-head">
              <h2>Steps</h2>
            </div>
            {recipe.steps.length ? (
              <LineList
                lines={recipe.steps}
                kind="step"
                factor={factor}
                onChange={(lines: IngredientIn[]) => save({ steps: lines })}
              />
            ) : (
              <p className="muted">No steps yet.</p>
            )}
          </section>
          <Notes recipe={recipe} reload={reload} />
          {recipe.original_text && (
            <details>
              <summary>Original imported text</summary>
              <div className="original-text">{recipe.original_text}</div>
            </details>
          )}
        </div>
      </div>
    </article>
  );
}
