from outreach_studio.engine import aggregate


def drafts(*ids):
    return {i: {"status": "done", "persona": i.title(), "subject": "s", "body": "b"} for i in ids}


def judgment(scores, ranking, taste=False, tradeoff=""):
    full = {d: {c: v for c in ["purpose", "recipient_fit", "accuracy", "tone", "craft", "overall"]} | {"note": ""} for d, v in scores.items()}
    return {"status": "done", "scores": full, "ranking": ranking, "preference_dependent": taste, "tradeoff": tradeoff}


def test_own_score_is_excluded_and_consensus_reached():
    d = drafts("a", "b", "c")
    j = {
        "a": judgment({"a": 10, "b": 6, "c": 5}, ["a", "b", "c"]),  # self-preference ignored
        "b": judgment({"a": 9, "b": 7, "c": 5}, ["a", "b", "c"]),
        "c": judgment({"a": 8, "b": 6, "c": 9}, ["c", "a", "b"]),
    }
    dec = aggregate(d, j)
    assert dec["table"]["a"]["peer"] == 8.5  # only b and c count
    assert dec["table"]["c"]["peer"] == 5.0
    assert dec["winner"] == "a" and dec["mode"] == "consensus"
    assert dec["picks"]["c"] == "a"  # c's own draft is skipped when reading its pick


def test_close_scores_ask_the_user():
    d = drafts("a", "b", "c")
    j = {
        "a": judgment({"a": 9, "b": 8, "c": 6}, ["a", "b", "c"]),
        "b": judgment({"a": 8, "b": 9, "c": 6}, ["b", "a", "c"]),
        "c": judgment({"a": 8, "b": 8, "c": 7}, ["b", "a", "c"]),
    }
    dec = aggregate(d, j)
    assert dec["mode"] == "review"
    assert set(dec["contenders"]) >= {"a", "b"}


def test_split_first_choices_ask_the_user_even_with_margin():
    d = drafts("a", "b", "c")
    j = {
        "a": judgment({"a": 9, "b": 5, "c": 9}, ["c", "a", "b"]),
        "b": judgment({"a": 9, "b": 9, "c": 6}, ["a", "b", "c"]),
        "c": judgment({"a": 9, "b": 5, "c": 9}, ["b", "a", "c"]),
    }
    dec = aggregate(d, j)
    assert dec["winner"] == "a"
    assert not dec["agree"] and dec["mode"] == "review"


def test_majority_taste_flag_asks_the_user():
    d = drafts("a", "b", "c")
    j = {k: judgment({"a": 9, "b": 7, "c": 5}, ["a", "b", "c"], taste=(k != "c"), tradeoff="warmth vs brevity") for k in "abc"}
    dec = aggregate(d, j)
    assert dec["mode"] == "review" and dec["tradeoff"] == "warmth vs brevity"


def test_failed_judges_are_ignored():
    d = drafts("a", "b")
    j = {"a": judgment({"a": 9, "b": 5}, ["a", "b"]), "b": judgment({"a": 9, "b": 6}, ["a", "b"]), "x": {"status": "failed"}}
    dec = aggregate(d, j)
    assert dec["table"]["a"]["n"] == 1 and dec["mode"] == "consensus"
