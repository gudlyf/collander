from app.schemas import RecipeIn
from app.services.ai_check import NOTE_PREFIX, check_recipe
from app.services.settings_store import AIConfig

CFG = AIConfig(
    provider="ollama",
    model="x",
    anthropic_api_key=None,
    openai_api_key=None,
    openai_base_url=None,
    google_api_key=None,
    ollama_base_url="http://x",
    auto_tag=True,
)

RAW = RecipeIn(
    title="Soup",
    ingredients=[
        {"text": "▢ 2 cups broth"},
        {"text": "1 tsp salt USE SOY SAUCE INSTEAD", "override_text": "1 tsp soy sauce"},
    ],
    steps=[{"text": "1. Heat it."}],
)


def test_tidy_applied_and_original_kept(fake_ai):
    fake_ai.review = lambda u: {
        "ingredients": [
            {"section": "", "text": "2 cups broth"},
            {"section": "", "text": "1 tsp salt"},
        ],
        "steps": [{"section": "", "text": "Heat it."}],
        "issues": [],
        "tags": ["Soup"],
    }
    res = check_recipe(CFG, RAW, [])
    r = res.recipe
    assert res.changed_lines
    assert [i.text for i in r.ingredients] == ["2 cups broth", "1 tsp salt USE SOY SAUCE INSTEAD"]
    assert r.ingredients[1].override_text == "1 tsp soy sauce"  # modified line untouched
    assert r.steps[0].text == "Heat it."
    assert "▢ 2 cups broth" in r.original_text
    assert "soup" in r.tags and not r.needs_review


def test_quantity_change_rejected(fake_ai):
    fake_ai.review = lambda u: {
        "ingredients": [
            {"section": "", "text": "4 cups broth"},
            {"section": "", "text": "1 tsp salt USE SOY SAUCE INSTEAD"},
        ],
        "steps": [{"section": "", "text": "Heat it."}],
        "issues": ["Step 1 heats an empty pot."],
        "tags": [],
    }
    res = check_recipe(CFG, RAW, [])
    assert not res.changed_lines
    assert res.recipe.ingredients[0].text == "▢ 2 cups broth"
    assert res.recipe.needs_review
    note = res.recipe.notes[-1].text
    assert note.startswith(NOTE_PREFIX) and "changed quantities" in note and "empty pot" in note


def test_dropping_text_rejected(fake_ai):
    fake_ai.review = lambda u: {
        "ingredients": [
            {"section": "", "text": "2 cups"},
            {"section": "", "text": "1 tsp salt USE SOY SAUCE INSTEAD"},
        ],
        "steps": [{"section": "", "text": "1."}],
        "issues": [],
        "tags": [],
    }
    res = check_recipe(CFG, RAW, [])
    assert not res.changed_lines
    assert "not applied" in res.recipe.notes[-1].text
