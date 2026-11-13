from conftest import FIXTURES

from app.services import enex
from app.services.heuristic import looks_like_recipe, parse_text

TEXT = """Pancakes
Fluffy weekend pancakes.
Serves: 4
Ingredients
- 1 1/2 cups flour
- 1 tbsp sugar
For the topping:
- maple syrup
Directions
1. Whisk dry ingredients.
2. Add milk and eggs; cook on a griddle.
Notes
Keep warm in a low oven.
"""


def test_parse_text_with_headings():
    r = parse_text(TEXT)
    assert r.title == "Pancakes"
    assert r.servings == "4"
    assert [i.text for i in r.ingredients] == ["1 1/2 cups flour", "1 tbsp sugar", "maple syrup"]
    assert r.ingredients[2].section == "For the topping"
    assert [s.text for s in r.steps][0] == "Whisk dry ingredients."
    assert not r.needs_review
    assert r.notes and "low oven" in r.notes[0].text


def test_parse_text_without_structure_flags_review():
    r = parse_text("Mom's thing\nmix stuff and bake it until done")
    assert r.needs_review
    assert r.original_text


def test_looks_like_recipe():
    assert looks_like_recipe(TEXT + " bake at 350 oven tsp")
    assert not looks_like_recipe("Policy renews in March. Call the agent.")


def test_enex_stream_parse():
    notes = list(enex.iter_notes(FIXTURES / "sample.enex"))
    assert [n.title for n in notes] == [
        "Grandma's Chili",
        "Recipe card scan",
        "Car insurance renewal",
    ]
    chili = notes[0]
    assert chili.tags == ["Dinner", "Family Recipes"]
    assert chili.source_url == "https://example.com/chili"
    assert chili.created.year == 2019
    assert len(chili.images) == 1 and chili.images[0].mime == "image/png"
    text = chili.text
    assert "- 1 lb ground beef" in text
    assert "Directions" in text
    assert "[x]" in notes[2].text
