from __future__ import annotations


def name_matches_fuzzy(name: str | None, query: str) -> bool:
    """Match literal, case-insensitive subsequences, independently for each word.

    Used as a SQLite predicate so counts and every page share the same selection.
    This does not implement fzf's extended operators, smart case, or ranking.
    """
    words = query.casefold().split()
    if not words:
        return True
    if name is None:
        return False
    folded = name.casefold()
    for word in words:
        position = 0
        for character in word:
            index = folded.find(character, position)
            if index < 0:
                return False
            position = index + 1
    return True
