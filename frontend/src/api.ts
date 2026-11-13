// Typed client for the Collander REST API.

export interface BuildInfo {
  status: string;
  version: string;
  commit: string | null;
}

export interface IngredientIn {
  text: string;
  section?: string | null;
  override_text?: string | null;
  override_note?: string | null;
  omitted?: boolean;
  is_addition?: boolean;
}
export type StepIn = IngredientIn;

export interface Ingredient extends IngredientIn {
  id: number;
}
export type Step = Ingredient;

export interface Note {
  id: number;
  text: string;
  created_at: string;
  updated_at: string;
}

export interface RecipeIn {
  title: string;
  description: string;
  source_url: string | null;
  source_name: string | null;
  source_kind: string;
  servings: string | null;
  prep_time: string | null;
  cook_time: string | null;
  total_time: string | null;
  rating: number | null;
  favorite: boolean;
  needs_review: boolean;
  original_text: string | null;
  tags: string[];
  ingredients: IngredientIn[];
  steps: StepIn[];
  notes: { text: string }[];
  image: string | null;
}

export interface Recipe extends Omit<RecipeIn, "ingredients" | "steps" | "notes"> {
  id: number;
  ingredients: Ingredient[];
  steps: Step[];
  notes: Note[];
  created_at: string;
  updated_at: string;
}

export interface RecipeSummary {
  id: number;
  title: string;
  description: string;
  image: string | null;
  favorite: boolean;
  rating: number | null;
  needs_review: boolean;
  total_time: string | null;
  tags: string[];
  has_modifications: boolean;
  updated_at: string;
  snippet: string | null;
}

export interface RecipeList {
  items: RecipeSummary[];
  total: number;
}

export interface TagInfo {
  id: number;
  name: string;
  count: number;
}

export interface QueueItem {
  id: number;
  kind: "photo" | "url" | "text";
  status: "queued" | "processing" | "done" | "failed";
  label: string;
  file_count: number;
  recipe_id: number | null;
  method: string | null;
  warnings: string[];
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ImportJob {
  id: number;
  kind: string;
  status: string;
  filename: string;
  total: number;
  processed: number;
  imported: number;
  failed: number;
  use_ai: boolean;
  log: string;
  created_at: string;
}

export interface EnexNotePreview {
  index: number;
  title: string;
  tags: string[];
  source_url: string | null;
  snippet: string;
  image_count: number;
  likely_recipe: boolean;
}

export interface AISettings {
  provider: string;
  model: string | null;
  ollama_base_url: string;
  openai_base_url: string | null;
  effective_model: string | null;
  keys: Record<string, "env" | "db" | "">;
  auto_tag: boolean;
}

export interface AuthStatus {
  authenticated: boolean;
  setup_required: boolean;
  password_from_env: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`/api${path}`, init);
  if (res.status === 401 && !path.startsWith("/auth")) {
    window.dispatchEvent(new Event("collander:unauthorized"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  del: <T = void>(p: string) => request<T>("DELETE", p),
};

export function imageUrl(name: string | null | undefined): string | null {
  if (!name) return null;
  if (name.startsWith("data:") || name.startsWith("http")) return name;
  return `/api/images/${name}`;
}

export function emptyRecipe(): RecipeIn {
  return {
    title: "",
    description: "",
    source_url: null,
    source_name: null,
    source_kind: "manual",
    servings: null,
    prep_time: null,
    cook_time: null,
    total_time: null,
    rating: null,
    favorite: false,
    needs_review: false,
    original_text: null,
    tags: [],
    ingredients: [],
    steps: [],
    notes: [],
    image: null,
  };
}

/** Convert a saved recipe back into the editable/input shape. */
export function toInput(r: Recipe): RecipeIn {
  const strip = <T extends { id?: number }>(x: T) => {
    const { id: _id, ...rest } = x;
    return rest;
  };
  return {
    title: r.title,
    description: r.description,
    source_url: r.source_url,
    source_name: r.source_name,
    source_kind: r.source_kind,
    servings: r.servings,
    prep_time: r.prep_time,
    cook_time: r.cook_time,
    total_time: r.total_time,
    rating: r.rating,
    favorite: r.favorite,
    needs_review: r.needs_review,
    original_text: r.original_text,
    tags: [...r.tags],
    ingredients: r.ingredients.map(strip),
    steps: r.steps.map(strip),
    notes: [],
    image: r.image,
  };
}
