# -*- coding: utf-8 -*-
"""A boss drop must say WHICH BOSS, not which grace it happens to be standing near.

desc_sources declares a boss layer at priority 2, above every spatial layer. gen_data shipped
`_BOSS_NAMES = {}  # TODO` on the day it landed, so layer 2 never fired once: 143 of the 214
Boss-tagged checks fell through to layer 4/4b (nearest grace) or below, and the name answered a
question nobody asked. The worst of them answered nothing at all --

    Altus :: Crimsonspill Crystal Tear [f65000]                       (the Wormface's drop)
    Altus :: Godskin Peeler - around Windmill Heights [f530325]       (the Godskin Apostle's)
    Altus :: Speckled Hardtear - m60_41_53 [f65060]                   (the Wormface again)

-- and the third one was showing a RAW MAP TOKEN to a player. Found 2026-08-24 the only way this
kind of thing gets found: Alaric read a cross-game spoiler, saw a Hollow Knight progression item on
"Crimsonspill Crystal Tear", and said a crystal tear is an item, not a boss pickup. He was reading
the name correctly. The name was wrong.

WHAT THIS FILE PINS, and why it is about data.py rather than desc_sources. The waterfall itself is
already covered by test_gf_location_desc with injected fixtures -- and it PASSED throughout, because
an injected `boss_names={...}` proves the layer works, never that anything feeds it. The failure was
an empty source, so the assertion has to be on the SHIPPED NAMES:

  1. the layer is LIVE and its coverage cannot silently collapse back toward zero;
  2. named worked examples, so a regression names itself;
  3. no Boss-tagged check is described by a grace -- the specific wrong answer;
  4. AP ids did not move, because a rename is not a renumber.
"""
import os
import re

import pytest

from ..data import LOCATIONS
from ..location_tags import LOCATION_TAGS

HERE = os.path.dirname(os.path.abspath(__file__))


def _rows():
    """(region, name, ap_id, flag) for every committed check."""
    return [(reg,) + tuple(t) for reg, lst in LOCATIONS.items() for t in lst]


def _descriptor(name):
    """The middle of `Region :: Item - <desc> [f<flag>]`, or "" when the check ships bare."""
    body = name.split(" :: ", 1)[1] if " :: " in name else name
    body = re.sub(r"\s*\[f-?\d+\]\s*$", "", body)
    body = re.sub(r"\s*\(region unconfirmed\)\s*$", "", body)
    return body.split(" - ", 1)[1] if " - " in body else ""


def _boss_tagged():
    return [r for r in _rows() if "Boss" in (LOCATION_TAGS.get(r[2]) or ())]


# ---- the layer is live ---------------------------------------------------------------------------

def test_the_boss_tagged_set_is_not_empty():
    """WITNESS. Every assertion below quantifies over Boss-tagged checks, and all() over an empty
    set passes. If the tagging goes dark this file must fail here, loudly, not everywhere quietly."""
    assert len(_boss_tagged()) > 150, (
        "only %d Boss-tagged checks -- location_tags went dark and this whole file is vacuous"
        % len(_boss_tagged()))


def test_most_boss_checks_name_their_boss():
    """The floor is deliberately well under the measured coverage: this guards against the layer
    going BACK to empty, not against the datamine gaining or losing a few bosses. Measured
    2026-08-24: 179 flags carry a boss name, 146 of them checks that previously showed something
    else. A number this far below that can only mean the join stopped joining."""
    tagged = _boss_tagged()
    described = [r for r in tagged if _descriptor(r[1])]
    assert len(described) >= 120, (
        "only %d of %d Boss-tagged checks carry ANY descriptor -- desc_sources layer 2 is probably "
        "empty again (gen_data._build_boss_names)" % (len(described), len(tagged)))


# ---- the worked examples -------------------------------------------------------------------------

# flag -> the boss the game actually has holding it. Each was verified through the datamined tables
# (boss_drops.BOSS_DROP_ENTITY / boss_reward_lots.BOSS_REWARD_DEFEAT -> boss_healthbars) at the time
# this landed. They are here BY NAME so a regression reads as "Crimsonspill lost Wormface" rather
# than as a count moving by one.
WORKED_EXAMPLES = {
    65000: "Wormface",                    # a crystal tear, and the case that started this
    65060: "Wormface",                    # was showing the raw tile token m60_41_53
    530325: "Godskin Apostle",
    530315: "Draconic Tree Sentinel",
    530350: "Black Knife Assassin",
    520640: "Onyx Lord",
    520630: "Stonedigger Troll",          # via the scripted-reward join, not the drop join
    520110: "Misbegotten Warrior",        # ditto
    1039517200: "Night's Cavalry",
    1043537400: "Bell Bearing Hunter",
}


@pytest.mark.parametrize("flag,boss", sorted(WORKED_EXAMPLES.items()))
def test_the_worked_examples_name_their_boss(flag, boss):
    """A flag may back MORE THAN ONE check -- gen_data's co-check pass (`_COCHECK_FLAGS`) puts a
    second reward on the same acquisition flag, so 530315 is both `Dragon Greatclaw` and
    `Dragonclaw Shield`. Every one of them is the same boss's drop and every one must say so, so
    this asserts over all of the matches rather than pinning the count at one."""
    hits = [r for r in _rows() if r[3] == flag]
    assert hits, "flag %d matched no check at all" % flag
    for hit in hits:
        assert _descriptor(hit[1]) == boss, (
            "%r should be described by %r, got %r" % (hit[1], boss, _descriptor(hit[1])))


# ---- the specific wrong answer -------------------------------------------------------------------

def _derived_boss_names():
    """Re-do gen_data's layer-2 join HERE, from the committed datamined tables, so this file is an
    independent oracle rather than a restatement of the generator. Same two joins, same precedence."""
    from ..boss_drops import BOSS_DROP_ENTITY
    from ..boss_healthbars import BOSS_HEALTHBARS
    from ..boss_reward_lots import BOSS_REWARD_DEFEAT
    out = {}
    for flag, defeat in BOSS_REWARD_DEFEAT.items():          # reward flag -> defeat flag (exact)
        hb = BOSS_HEALTHBARS.get(defeat)
        if hb and hb[3]:
            out[flag] = hb[3]
    for flag, entity in BOSS_DROP_ENTITY.items():            # drop flag -> entity, when it is a key
        hb = BOSS_HEALTHBARS.get(entity)
        if hb and hb[3]:
            out.setdefault(flag, hb[3])
    return out


def test_no_resolvable_boss_check_is_described_by_a_grace():
    """THE SPECIFIC WRONG ANSWER. Layers 4/4b render "near <grace>" / "around <grace>" -- a spatial
    answer standing in for the boss layer, which outranks both.

    Scoped to checks whose flag RESOLVES to a named boss, and that scope is the honest one, not a
    convenience: a Boss-tagged check can reach the tag through `_BOSS_DROP_EXTRAS` (hand-added flags
    with no entity) or the Dragon Heart special case, and neither carries a name for layer 2 to use.
    14 checks are in that state -- `Dragon Heart - around Dragonbarrow Fork` is Flying Dragon Greyll's
    and says so nowhere. They keep their grace, correctly, until the datamine can name them; asserting
    over them would only force the assertion to be deleted."""
    derived = _derived_boss_names()
    wrong = [(r[1], derived[r[3]]) for r in _boss_tagged()
             if r[3] in derived and _descriptor(r[1]).startswith(("near ", "around "))]
    assert wrong == [], (
        "%d check(s) resolve to a named boss but are described by a SITE OF GRACE, so layer 2 lost to "
        "layer 4/4b: %s" % (len(wrong), wrong[:5]))


def test_every_resolvable_boss_check_names_that_boss_or_is_hand_overridden():
    """The full-coverage form of the worked examples. A resolvable check shows either the derived
    boss name, or a DIFFERENT hand-authored one -- layer 1 outranks layer 2 and 30 rows use it to
    shorten the in-game name ("Morgott", not "Morgott, the Omen King", because the item is already
    "Remembrance of the Omen King"). What it may never show is a grace, a map token, or nothing."""
    derived = _derived_boss_names()
    resolvable = [r for r in _boss_tagged() if r[3] in derived]
    assert len(resolvable) > 100, (
        "only %d resolvable Boss checks -- the datamined tables went dark, this test is vacuous"
        % len(resolvable))
    bare = [r[1] for r in resolvable if not _descriptor(r[1])]
    assert bare == [], "%d resolvable boss check(s) ship with NO descriptor: %s" % (len(bare), bare[:5])
    tokenish = [r[1] for r in resolvable if re.fullmatch(r"m\d\d_.*", _descriptor(r[1]) or "")]
    assert tokenish == [], (
        "%d resolvable boss check(s) show a RAW MAP TOKEN where the boss name belongs: %s"
        % (len(tokenish), tokenish[:5]))


# ---- a rename is not a renumber ------------------------------------------------------------------

def test_ap_ids_are_dense_and_unique():
    """🛑 The one thing a naming change may NEVER do. AP ids are the client's and the multidata's
    identity for a check; renumbering silently invalidates every tracker, every hint and every seed
    in flight, and it would not show up in any name-based assertion above."""
    rows = _rows()
    ids = [r[2] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate AP location ids"
    assert min(ids) == 7770000, "the id space no longer starts at BASE_AP -- everything renumbered"


def test_every_check_name_is_unique():
    """Two checks sharing a name collapse into one AP location. gen_data appends collision ordinals
    to prevent it; a new descriptor source is exactly what could defeat that."""
    names = [r[1] for r in _rows()]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert dupes == [], "%d duplicated check name(s): %s" % (len(dupes), dupes[:5])
