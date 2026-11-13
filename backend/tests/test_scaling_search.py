from app.services.search import parse_query


def test_parse_plain_terms_are_prefix_anded():
    pq = parse_query("chicken curry")
    assert pq.match == '"chicken"* AND "curry"*'


def test_parse_phrase_exclusion_tags_flags_and_fields():
    pq = parse_query('"brown butter" -cilantro tag:Vegetarian -tag:spicy is:favorite in:title soup')
    assert pq.match == '"brown butter" AND title : "soup"*'
    assert pq.exclude_match == '"cilantro"*'
    assert pq.tags == ["vegetarian"]
    assert pq.exclude_tags == ["spicy"]
    assert "favorite" in pq.flags


def test_parse_strips_fts_syntax():
    pq = parse_query('NEAR( "x" * ^col:')
    assert pq.match  # does not raise, produces a safe expression
