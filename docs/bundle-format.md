# Collander bundle format

A bundle is a JSON file holding one or more recipes. Collander backups use it, and it is the easiest way to migrate recipes from somewhere else: write a script (or ask an AI assistant) that turns your recipes into this shape, then load it with **Import → Backup file** or `python -m app.cli import-bundle`.

```json
{
  "format": "collander-bundle",
  "version": 1,
  "recipes": [
    {
      "title": "Weeknight Tomato Soup",
      "description": "A cozy, fast soup.",
      "source_url": "https://example.com/soup",
      "source_name": "Example Kitchen",
      "source_kind": "gdrive",
      "servings": "4 servings",
      "prep_time": "10 min",
      "cook_time": "25 min",
      "total_time": "35 min",
      "rating": 4,
      "favorite": false,
      "needs_review": true,
      "tags": ["soup", "vegetarian"],
      "ingredients": [
        { "text": "2 tbsp butter" },
        { "text": "1 1/2 cups skim milk", "override_text": "1 1/2 cups almond milk", "override_note": "dairy-free" },
        { "text": "basil, torn", "section": "For serving" }
      ],
      "steps": [
        { "text": "Melt the butter and soften the onion." },
        { "text": "Simmer 20 minutes, then blend." }
      ],
      "notes": [{ "text": "Roast the tomatoes first next time." }],
      "original_text": "Optional: the full source text, kept for reference.",
      "image": "https://example.com/soup.jpg",
      "created_at": "2021-05-01T12:00:00"
    }
  ]
}
```

Only `title` is required. A bare JSON array of recipes is accepted too.

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `title` | string | Required, at most 300 characters |
| `description` | string | |
| `source_url`, `source_name` | string | Where the recipe came from |
| `source_kind` | string | Free label, e.g. `manual`, `url`, `photo`, `evernote`, `gdrive`, `bundle` |
| `servings`, `prep_time`, `cook_time`, `total_time` | string | Free text ("4 servings", "1 hr 10 min") |
| `rating` | 0–5 | |
| `favorite`, `needs_review` | boolean | `needs_review` shows a badge until someone checks the recipe |
| `tags` | string[] | Lowercased and hyphenated on import |
| `ingredients`, `steps` | line[] | See below |
| `notes` | `{text, created_at?}[]` | |
| `original_text` | string | Shown under "Original imported text" |
| `image` | string | An `http(s)` URL to download, or a `data:image/...;base64,` URI |
| `image_generated` | bool | `true` when `image` is an AI-made recipe icon rather than a photo. Only honored for `data:` URIs; such icons are kept as PNG and replaced by any later photo. Default `false`. |
| `created_at` | ISO datetime | Keeps the original date |

A **line** (ingredient or step) is:

| Field | Type | Notes |
| --- | --- | --- |
| `text` | string | The original wording. Write ingredients quantity-first ("2 cups flour") so they scale. |
| `section` | string | Group heading, e.g. "For the sauce" |
| `override_text` | string | Your replacement; the original stays visible |
| `override_note` | string | Why it was changed |
| `omitted` | boolean | Shown crossed out as "left out" |
| `is_addition` | boolean | A line you added that wasn't in the original |

When importing, recipes whose title (and link, if any) match an existing recipe are skipped unless you turn that off.
