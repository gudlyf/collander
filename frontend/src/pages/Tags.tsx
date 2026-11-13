import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type TagInfo } from "../api";
import { useTags } from "../hooks";

function TagRow({ tag, reload }: { tag: TagInfo; reload: () => void }) {
  const [name, setName] = useState(tag.name);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const changed = name.trim() && name !== tag.name;
  return (
    <tr>
      <td>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label={`Rename ${tag.name}`}
          onKeyDown={async (e) => {
            if (e.key === "Enter" && changed) {
              await api.put(`/tags/${tag.id}`, { name });
              reload();
            }
          }}
        />
        {error && <div className="small" style={{ color: "var(--danger)" }}>{error}</div>}
      </td>
      <td>
        <Link to={`/?tag=${encodeURIComponent(tag.name)}`}>{tag.count}</Link>
      </td>
      <td>
        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          {changed && (
            <button
              className="btn small primary"
              onClick={async () => {
                try {
                  await api.put(`/tags/${tag.id}`, { name });
                  reload();
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Rename
            </button>
          )}
          {confirm ? (
            <button
              className="btn small danger"
              onClick={async () => {
                await api.del(`/tags/${tag.id}`);
                reload();
              }}
            >
              Remove from {tag.count} recipe{tag.count === 1 ? "" : "s"}
            </button>
          ) : (
            <button className="btn small ghost danger" onClick={() => setConfirm(true)}>
              Delete
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function Tags() {
  const { data, reload } = useTags();
  return (
    <div className="stack" style={{ maxWidth: 720 }}>
      <h1>Tags</h1>
      <p className="muted">
        Rename a tag to fix it everywhere. Renaming it to an existing tag merges the two.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Tag</th>
            <th>Recipes</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(data ?? []).map((t) => (
            <TagRow key={`${t.id}-${t.name}`} tag={t} reload={reload} />
          ))}
        </tbody>
      </table>
      {data && data.length === 0 && <p className="muted">No tags yet.</p>}
    </div>
  );
}
