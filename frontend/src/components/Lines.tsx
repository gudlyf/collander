// Ingredient and step lists for the recipe view, with scaling and inline modifications.
import { Fragment, useState } from "react";
import type { IngredientIn } from "../api";
import { scaleLine } from "../scale";
import { PencilIcon } from "./icons";

type Line = IngredientIn;

function Qty({ text, factor, enabled }: { text: string; factor: number; enabled: boolean }) {
  if (!enabled) return <>{text}</>;
  const s = scaleLine(text, factor);
  if (!s.scaled) return <>{text}</>;
  return (
    <>
      <span className="scaled">{s.text.slice(0, s.qtyEnd)}</span>
      {s.text.slice(s.qtyEnd)}
    </>
  );
}

function LineText({ line, factor, scale }: { line: Line; factor: number; scale: boolean }) {
  const replaced = !!line.override_text;
  return (
    <span className="text">
      <span className={`orig ${replaced ? "replaced" : ""}`}>
        <Qty text={line.text} factor={factor} enabled={scale} />
      </span>
      {line.is_addition && <span className="tag-added">added</span>}
      {line.omitted && <span className="tag-omitted">left out</span>}
      {replaced && (
        <span className="yours">
          <Qty text={line.override_text!} factor={factor} enabled={scale} />
        </span>
      )}
      {line.override_note && <span className="why">{line.override_note}</span>}
    </span>
  );
}

function ModifyBox({
  line,
  isStep,
  onSave,
  onCancel,
  onDelete,
}: {
  line: Line;
  isStep: boolean;
  onSave: (l: Line) => void;
  onCancel: () => void;
  onDelete?: () => void;
}) {
  // Start from the current wording so a small change is a small edit.
  const [override, setOverride] = useState(line.override_text ?? line.text);
  const [note, setNote] = useState(line.override_note ?? "");
  const [omitted, setOmitted] = useState(!!line.omitted);
  const Input = isStep ? "textarea" : "input";

  const save = () => {
    if (line.is_addition) {
      onSave({ ...line, text: override.trim() || line.text, override_note: note.trim() || null });
    } else {
      const changed = override.trim() && override.trim() !== line.text.trim();
      onSave({
        ...line,
        override_text: changed ? override.trim() : null,
        override_note: note.trim() || null,
        omitted,
      });
    }
  };

  return (
    <div className="modify-box">
      {!line.is_addition && (
        <div className="orig-ref">
          Original: <em>{line.text}</em>
        </div>
      )}
      <label className="field">
        {line.is_addition ? "Your addition" : "Change to"}
        <Input
          type="text"
          value={override}
          autoFocus
          rows={3}
          placeholder={line.is_addition ? "" : "Leave empty to use the original"}
          onFocus={(e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) =>
            e.currentTarget.setSelectionRange(e.currentTarget.value.length, e.currentTarget.value.length)
          }
          onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
            setOverride(e.target.value)
          }
          onKeyDown={(e: React.KeyboardEvent) => {
            if (e.key === "Enter" && !isStep) save();
            if (e.key === "Escape") onCancel();
          }}
        />
      </label>
      <label className="field">
        <span>
          Why <span className="hint">(optional)</span>
        </span>
        <input
          type="text"
          value={note}
          placeholder="e.g. dairy-free, less sweet"
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      {!line.is_addition && (
        <label className="check">
          <input type="checkbox" checked={omitted} onChange={(e) => setOmitted(e.target.checked)} />
          Leave this out
        </label>
      )}
      <div className="row">
        <button className="btn primary small" onClick={save}>
          Save change
        </button>
        {!line.is_addition && (line.override_text || line.omitted || line.override_note) && (
          <button
            className="btn small"
            onClick={() => onSave({ ...line, override_text: null, override_note: null, omitted: false })}
          >
            Restore original
          </button>
        )}
        {line.is_addition && onDelete && (
          <button className="btn small danger" onClick={onDelete}>
            Remove
          </button>
        )}
        <button className="btn ghost small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

interface ListProps {
  lines: Line[];
  kind: "ingredient" | "step";
  factor: number;
  onChange: (lines: Line[]) => Promise<void>;
}

export function LineList({ lines, kind, factor, onChange }: ListProps) {
  const [editing, setEditing] = useState<number | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);
  const isStep = kind === "step";
  let stepNo = 0;

  const update = async (i: number, l: Line) => {
    const next = lines.map((x, j) => (j === i ? l : x));
    await onChange(next);
    setEditing(null);
  };

  const toggleDone = (i: number) =>
    setDone((prev) => {
      const n = new Set(prev);
      n.has(i) ? n.delete(i) : n.add(i);
      return n;
    });

  return (
    <>
      <ul className={`lines ${isStep ? "steps" : ""}`}>
        {lines.map((l, i) => {
          const showSection = l.section && l.section !== lines[i - 1]?.section;
          if (!l.omitted) stepNo += 1;
          return (
            <Fragment key={i}>
              {showSection && <li className="group">{l.section}</li>}
              <li
                className={`line ${done.has(i) ? "done" : ""} ${l.omitted ? "omitted" : ""} ${
                  l.is_addition ? "added" : ""
                }`}
                onClick={
                  isStep
                    ? (e) => {
                        // A tap anywhere on a step ticks it, except on its own controls.
                        const t = e.target as HTMLElement;
                        if (t.closest("input, button, textarea, a, .modify-box")) return;
                        if (window.getSelection()?.toString()) return; // selecting text to copy
                        toggleDone(i);
                      }
                    : undefined
                }
              >
                <input
                  type="checkbox"
                  className="tick check"
                  checked={done.has(i)}
                  onChange={() => toggleDone(i)}
                  aria-label={isStep ? `Done with step ${l.omitted ? "" : stepNo}`.trim() : `Got ${l.text}`}
                />
                {isStep && <span className="num">{l.omitted ? "–" : stepNo}</span>}
                <LineText line={l} factor={factor} scale={!isStep} />
                <button
                  className="btn ghost icon edit-btn"
                  onClick={() => setEditing(editing === i ? null : i)}
                  aria-label={`Modify: ${l.text}`}
                  title="Modify"
                >
                  <PencilIcon />
                </button>
                {editing === i && (
                  <ModifyBox
                    line={l}
                    isStep={isStep}
                    onSave={(nl) => update(i, nl)}
                    onCancel={() => setEditing(null)}
                    onDelete={async () => {
                      await onChange(lines.filter((_, j) => j !== i));
                      setEditing(null);
                    }}
                  />
                )}
              </li>
            </Fragment>
          );
        })}
      </ul>
      {adding ? (
        <ModifyBox
          line={{ text: "", is_addition: true, section: lines.at(-1)?.section ?? null }}
          isStep={isStep}
          onSave={async (l) => {
            if (l.text.trim()) await onChange([...lines, l]);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : (
        <button className="btn ghost small no-print" style={{ marginTop: 8 }} onClick={() => setAdding(true)}>
          + Add {isStep ? "a step" : "an ingredient"}
        </button>
      )}
    </>
  );
}
