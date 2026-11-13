import { useId, useState } from "react";

interface Props {
  value: string[];
  onChange: (tags: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
}

export function normalizeTag(t: string): string {
  return t
    .trim()
    .toLowerCase()
    .replace(/^#/, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "");
}

export default function TagInput({ value, onChange, suggestions = [], placeholder }: Props) {
  const [draft, setDraft] = useState("");
  const listId = useId();

  const add = (raw: string) => {
    const parts = raw.split(",").map(normalizeTag).filter(Boolean);
    const next = [...value];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    onChange(next);
    setDraft("");
  };

  return (
    <div className="taginput">
      {value.map((t) => (
        <button
          type="button"
          key={t}
          className="chip"
          onClick={() => onChange(value.filter((x) => x !== t))}
          aria-label={`Remove tag ${t}`}
        >
          {t} <span className="x">×</span>
        </button>
      ))}
      <input
        type="text"
        value={draft}
        list={listId}
        placeholder={value.length ? "" : placeholder ?? "Add tags"}
        onChange={(e) => {
          const v = e.target.value;
          if (v.endsWith(",")) add(v);
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (draft.trim()) add(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft.trim() && add(draft)}
        aria-label="Add a tag"
      />
      <datalist id={listId}>
        {suggestions
          .filter((s) => !value.includes(s))
          .map((s) => (
            <option key={s} value={s} />
          ))}
      </datalist>
    </div>
  );
}
