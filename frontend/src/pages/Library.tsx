import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, imageUrl, type RecipeList, type RecipeSummary } from "../api";
import { GridIcon, HeartIcon, ListIcon, SearchIcon } from "../components/icons";
import { useTags } from "../hooks";

const PAGE = 48;

export function Highlight({ text }: { text: string }) {
  // The API marks matches with \x02 ... \x03.
  const parts = text.split(/(\x02[^\x03]*\x03)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("\x02") ? <mark key={i}>{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>,
      )}
    </>
  );
}

export function Thumb({ title, image }: { title: string; image: string | null }) {
  const src = imageUrl(image);
  if (src) return <img src={src} alt="" loading="lazy" />;
  return <div className="placeholder">{title.trim().charAt(0).toUpperCase() || "?"}</div>;
}

type View = "cards" | "list";
const VIEW_KEY = "collander:library-view";

function loadView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "cards";
  } catch {
    return "cards";
  }
}

function saveView(v: View) {
  try {
    localStorage.setItem(VIEW_KEY, v);
  } catch {
    /* storage unavailable; the choice just won't be remembered */
  }
}

function ViewToggle({ view, setView }: { view: View; setView: (v: View) => void }) {
  return (
    <div className="view-toggle" role="group" aria-label="Show recipes as">
      <button aria-pressed={view === "cards"} onClick={() => setView("cards")} title="Cards" aria-label="Cards">
        <GridIcon />
      </button>
      <button aria-pressed={view === "list"} onClick={() => setView("list")} title="List" aria-label="List">
        <ListIcon />
      </button>
    </div>
  );
}

function Row({ r }: { r: RecipeSummary }) {
  return (
    <li>
      <Link to={`/r/${r.id}`} className="list-row">
        <div className="list-thumb">
          <Thumb title={r.title} image={r.image} />
        </div>
        <div className="list-main">
          <div className="list-title">
            {r.favorite && <HeartIcon filled className="list-fav" width={15} height={15} aria-label="Favorite" />}
            <span>{r.title}</span>
          </div>
          {r.snippet ? (
            <div className="snippet">
              <Highlight text={r.snippet.replace(/\n/g, " · ")} />
            </div>
          ) : r.tags.length ? (
            <div className="list-tags">{r.tags.slice(0, 5).join(" · ")}</div>
          ) : null}
        </div>
        <div className="list-meta">
          {r.needs_review && <span className="badge review">Needs review</span>}
          {r.has_modifications && <span className="badge mod">Modified</span>}
          {r.rating ? <span className="list-rating" aria-label={`${r.rating} stars`}>{"★".repeat(r.rating)}</span> : null}
          {r.total_time && <span className="small muted">{r.total_time}</span>}
        </div>
      </Link>
    </li>
  );
}

function Card({ r }: { r: RecipeSummary }) {
  return (
    <Link to={`/r/${r.id}`} className="card">
      <div className="thumb">
        <Thumb title={r.title} image={r.image} />
        {r.favorite && <HeartIcon filled className="fav" width={22} height={22} />}
      </div>
      <h3>{r.title}</h3>
      {r.snippet ? (
        <div className="snippet">
          <Highlight text={r.snippet.replace(/\n/g, " · ")} />
        </div>
      ) : null}
      <div className="meta">
        {r.needs_review && <span className="badge review">Needs review</span>}
        {r.has_modifications && <span className="badge mod">Modified</span>}
        {r.total_time && <span className="small muted">{r.total_time}</span>}
      </div>
    </Link>
  );
}

export default function Library() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const selected = params.getAll("tag");
  const sort = params.get("sort") ?? "relevance";
  const flags = { favorite: params.has("favorite"), modified: params.has("modified"), review: params.has("review") };

  const [input, setInput] = useState(q);
  const [items, setItems] = useState<RecipeSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showAllTags, setShowAllTags] = useState(false);
  const [view, setViewState] = useState<View>(loadView);
  const setView = (v: View) => {
    setViewState(v);
    saveView(v);
  };
  const tags = useTags();

  useEffect(() => setInput(q), [q]);

  // Debounce typing into the URL.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (input === q) return;
      const next = new URLSearchParams(params);
      if (input.trim()) next.set("q", input);
      else next.delete("q");
      setParams(next, { replace: true });
    }, 250);
    return () => window.clearTimeout(t);
  }, [input]); // eslint-disable-line react-hooks/exhaustive-deps

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    selected.forEach((t) => p.append("tag", t));
    if (flags.favorite) p.set("favorite", "true");
    if (flags.modified) p.set("modified", "true");
    if (flags.review) p.set("review", "true");
    p.set("sort", q ? sort : sort === "relevance" ? "updated" : sort);
    return p;
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const p = new URLSearchParams(query);
    p.set("limit", String(PAGE));
    api
      .get<RecipeList>(`/recipes?${p}`)
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query]);

  const loadMore = async () => {
    const p = new URLSearchParams(query);
    p.set("limit", String(PAGE));
    p.set("offset", String(items.length));
    const res = await api.get<RecipeList>(`/recipes?${p}`);
    setItems((prev) => [...prev, ...res.items]);
  };

  const toggle = (key: string, value?: string) => {
    const next = new URLSearchParams(params);
    if (value !== undefined) {
      const all = next.getAll(key);
      next.delete(key);
      (all.includes(value) ? all.filter((v) => v !== value) : [...all, value]).forEach((v) =>
        next.append(key, v),
      );
    } else if (next.has(key)) next.delete(key);
    else next.set(key, "1");
    setParams(next, { replace: true });
  };

  const tagList = (tags.data ?? []).filter((t) => t.count > 0).sort((a, b) => b.count - a.count);
  const visibleTags = showAllTags ? tagList : tagList.slice(0, 14);
  const filtering = q || selected.length || flags.favorite || flags.modified || flags.review;

  return (
    <div>
      <div className="library-head">
        <div className="searchbox">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search recipes, ingredients, notes…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Search recipes"
            enterKeyHint="search"
          />
        </div>
        <div className="tagbar" role="group" aria-label="Filter by tag">
          <button className={`chip ${flags.favorite ? "on" : ""}`} onClick={() => toggle("favorite")}>
            ♥ Favorites
          </button>
          <button className={`chip ${flags.modified ? "on" : ""}`} onClick={() => toggle("modified")}>
            Modified
          </button>
          <button className={`chip ${flags.review ? "on" : ""}`} onClick={() => toggle("review")}>
            Needs review
          </button>
          {visibleTags.map((t) => (
            <button
              key={t.id}
              className={`chip ${selected.includes(t.name) ? "on" : ""}`}
              onClick={() => toggle("tag", t.name)}
            >
              {t.name}
            </button>
          ))}
          {tagList.length > 14 && (
            <button className="chip" onClick={() => setShowAllTags((s) => !s)}>
              {showAllTags ? "Fewer tags" : `All ${tagList.length} tags`}
            </button>
          )}
        </div>
        <div className="spread">
          <span className="muted small">
            {loading ? "Searching…" : `${total} recipe${total === 1 ? "" : "s"}`}
            {filtering ? (
              <>
                {" · "}
                <button className="btn ghost small" onClick={() => setParams(new URLSearchParams())}>
                  Clear filters
                </button>
              </>
            ) : null}
          </span>
          <div className="row">
          <ViewToggle view={view} setView={setView} />
          <label className="row small">
            Sort
            <select
              value={q ? sort : sort === "relevance" ? "updated" : sort}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("sort", e.target.value);
                setParams(next, { replace: true });
              }}
              style={{ width: "auto" }}
            >
              {q && <option value="relevance">Best match</option>}
              <option value="updated">Recently changed</option>
              <option value="created">Recently added</option>
              <option value="title">A–Z</option>
              <option value="rating">Rating</option>
            </select>
          </label>
          </div>
        </div>
      </div>

      {!loading && items.length === 0 ? (
        filtering ? (
          <div className="empty">
            <h2>No recipes match</h2>
            <p className="muted">
              Try fewer words, or search a single ingredient. <code>tag:soup</code>,{" "}
              <code>-cilantro</code> and <code>"exact phrase"</code> also work.
            </p>
          </div>
        ) : (
          <div className="empty">
            <h2>Your recipe box is empty</h2>
            <p className="muted">Add a recipe by hand, or import one from a link, a photo, or Evernote.</p>
            <div className="row">
              <Link to="/new" className="btn primary">
                Write a recipe
              </Link>
              <Link to="/import" className="btn">
                Import recipes
              </Link>
            </div>
          </div>
        )
      ) : (
        view === "list" ? (
          <ul className="recipe-list">
            {items.map((r) => (
              <Row key={r.id} r={r} />
            ))}
          </ul>
        ) : (
          <div className="grid">
            {items.map((r) => (
              <Card key={r.id} r={r} />
            ))}
          </div>
        )
      )}
      {items.length < total && (
        <div className="row" style={{ justifyContent: "center", marginTop: 30 }}>
          <button className="btn" onClick={loadMore}>
            Show more
          </button>
        </div>
      )}
    </div>
  );
}
