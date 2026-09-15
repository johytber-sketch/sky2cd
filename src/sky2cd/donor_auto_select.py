"""Automatic per-piece donor selection.

**Real gap this fixes:** `auto_replace_batch_from_skyrim` previously required
one manually-typed `--piece "mesh_selector=donor_id"` per piece for every
run -- for a real 4-piece outfit (Sherwood Huntress-style boots/dress/
gloves/hood) that means looking up 4 donor ids by hand every single time,
which defeats the point of an "automated" tool. This module guesses each
converted piece's Crimson Desert slot from its filename (the same
substring-matching style `--mesh-selector` already relies on), then looks up
a matching donor in `sky2cd.donor_catalog` automatically.

**Real limitation, by design:** Skyrim's actual body-slot assignment lives
in the plugin's (`.esp`/`.esl`) `ARMA` record biped-model bitfield, not in
the `.nif` mesh file itself -- and `sky2cd` never reads plugins, only loose
mesh archives. So this can only ever be a best-effort filename-keyword
guess, never a guaranteed-correct slot detection. Ambiguous guesses
(multiple catalog donors for the same slot) and unmatched pieces (no
keyword matched, or no catalog donor exists for that slot) are reported
explicitly rather than silently resolved, so the caller can always fall
back to an explicit `--piece` override for just the pieces that need one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sky2cd.donor_catalog import DonorEntry, list_catalog

# Keyword -> Crimson Desert slot name, used to guess a piece's slot from its
# filename. Order matters: entries are checked in order and the first match
# wins, so more specific keywords (e.g. "upperbody") are listed before more
# generic ones (e.g. "body") that could otherwise match unrelated pieces.
_SLOT_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("glove", "hands"),
    ("gauntlet", "hands"),
    ("hand", "hands"),
    ("boot", "feet"),
    ("shoe", "feet"),
    ("foot", "feet"),
    ("hood", "head"),
    ("helm", "head"),
    ("hat", "head"),
    ("head", "head"),
    ("upperbody", "upperbody"),
    ("dress", "upperbody"),
    ("chest", "upperbody"),
    ("cuirass", "upperbody"),
    ("robe", "upperbody"),
    ("torso", "upperbody"),
    ("lowerbody", "lowerbody"),
    ("pant", "lowerbody"),
    ("legging", "lowerbody"),
    ("skirt", "lowerbody"),
    ("body", "upperbody"),
)


@dataclass(frozen=True)
class PieceDonorGuess:
    """Auto-detection result for one converted outfit piece.

    `candidates` is every catalog donor whose `slot` matches `guessed_slot`
    (empty if the slot couldn't be guessed at all, or no catalog donor
    exists for that slot).
    """

    relative_path: str
    guessed_slot: str | None
    candidates: list[DonorEntry] = field(default_factory=list)

    @property
    def resolved(self) -> DonorEntry | None:
        """The single unambiguous donor to auto-select, or `None`.

        `None` covers both "no candidates" (`unmatched`) and "more than one
        candidate" (`ambiguous`) -- check those properties to tell them
        apart when reporting back to the user.
        """
        return self.candidates[0] if len(self.candidates) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1

    @property
    def unmatched(self) -> bool:
        return len(self.candidates) == 0


def guess_slot_from_path(relative_path: str) -> str | None:
    """Best-effort Crimson Desert slot guess from a piece's filename.

    Uses simple case-insensitive substring matching against `_SLOT_KEYWORDS`
    (the same style of matching `--mesh-selector` already uses to pick a
    piece). Returns `None` if no keyword matches.
    """
    lowered = relative_path.lower()
    for keyword, slot in _SLOT_KEYWORDS:
        if keyword in lowered:
            return slot
    return None


def auto_select_donors(
    relative_paths: list[str],
    catalog: list[DonorEntry] | None = None,
) -> list[PieceDonorGuess]:
    """Guess a slot + candidate donor(s) for every piece in `relative_paths`.

    `catalog` defaults to `sky2cd.donor_catalog.list_catalog()`; pass an
    explicit list (e.g. in tests) to avoid depending on the built-in
    catalog's current contents.
    """
    entries = catalog if catalog is not None else list_catalog()
    guesses: list[PieceDonorGuess] = []
    for relative_path in relative_paths:
        slot = guess_slot_from_path(relative_path)
        candidates = [entry for entry in entries if entry.slot == slot] if slot else []
        guesses.append(PieceDonorGuess(relative_path=relative_path, guessed_slot=slot, candidates=candidates))
    return guesses
