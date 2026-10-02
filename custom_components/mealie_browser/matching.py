"""Match a spoken phrase to a Mealie recipe.

Recipe *extras* (the free key/value pairs of a Mealie recipe) are checked
first: they are meant to be filled by hand with the phrases people actually
say ("dahl", "dahl de lentilles"...), including speech-recognition mistakes.
The recipe name is the fallback.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class RecipeCandidate:
    """The fields of a recipe that matter for matching."""

    slug: str
    name: str
    extras: Mapping[str, object]


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    text = unicodedata.normalize("NFKD", (text or "").strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_recipe(spoken: str, recipes: Iterable[RecipeCandidate]) -> RecipeCandidate | None:
    """Best recipe for ``spoken``, or None.

    Priority: exact extra, exact name, partial extra, partial name. "Partial"
    means one string contains the other.
    """
    target = normalize(spoken)
    if not target:
        return None

    buckets: list[list[RecipeCandidate]] = [[], [], [], []]
    for recipe in recipes:
        name = normalize(recipe.name)
        # Extras are usually typed as keys with an empty value, but accept
        # values too.
        phrases = {normalize(str(v)) for v in recipe.extras.values() if v}
        phrases |= {normalize(str(k)) for k in recipe.extras if k}
        phrases.discard("")

        if target in phrases:
            buckets[0].append(recipe)
        elif name == target:
            buckets[1].append(recipe)
        elif any(target in p or p in target for p in phrases):
            buckets[2].append(recipe)
        elif name and (target in name or name in target):
            buckets[3].append(recipe)

    for bucket in buckets:
        if bucket:
            return bucket[0]
    return None
