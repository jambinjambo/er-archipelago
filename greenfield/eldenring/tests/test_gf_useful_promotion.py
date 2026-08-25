"""Golden Seeds and Sacred Tears are `useful`, and the promotion has to be per-NAME.

WHY IT IS NOT A CATEGORY FLIP. `item_categories.CATEGORY_CLASS` promoted `spells`, `spirit_ashes`,
`crystal_tears` and `upgrade_bells` wholesale, and that is the right shape when the param separates
the items. It does not here: `GOODS_TYPE` files **Golden Seed, Sacred Tear, Scadutree Fragment and
Revered Spirit Ash under type 14 -- the same type as `Smithing Stone [1]`** -- so all four land in
`upgrade_materials`, the one goods category the table deliberately keeps FILLER because it is
features/filler_budget's economy, allocated by the hundred into the filler tail. Promoting the
category would move that whole tail into the useful tier: an economy change wearing a classification
change's clothes.

WHAT THESE TESTS GUARD:

  1. The four names classify `useful`, and the CATEGORY they sit in does not move -- a player who
     asks to keep_local their upgrade materials still means these too.
  2. 🛑 THE ECONOMY DID NOT MOVE. Smithing Stones, gloveworts and runes stay filler, and
     `displaceable_filler` still refuses the promoted names. This is the assertion that would fail
     if someone "simplified" the carve-out into a category flip.
  3. 🛑 ONE TAXONOMY, ASKED ONCE. features/filler_foreign builds its candidate list from `class_of`;
     if the promotion had gone into `core._class_for` instead, that list would still call a Golden
     Seed filler while core called it useful, and a low `filler_foreign_pct` would hold back an item
     the classification says may travel. The two lists must not overlap.
  4. Every promoted name is still resolvable to a game item by the client (the scadu_supply trap).
"""
import pytest

pytest.importorskip("worlds.eldenring")

from BaseClasses import ItemClassification                                  # noqa: E402

from worlds.eldenring import core                                           # noqa: E402
from worlds.eldenring import item_categories as ic                          # noqa: E402
from worlds.eldenring.features import filler_foreign as ff                  # noqa: E402
from worlds.eldenring.features.filler_curation import displaceable_filler   # noqa: E402

GAME = "Elden Ring"


class _Opt:
    def __init__(self, value):
        self.value = value


class _Stub:
    def __init__(self, **opts):
        self.options = type("O", (), {k: _Opt(v) for k, v in opts.items()})()


def _present():
    """The promoted names this build actually has (a base-only catalog lacks the DLC two)."""
    return [n for n in sorted(ic.USEFUL_GOODS) if n in core.ITEM_CATALOG]


# ---- 1. classification ---------------------------------------------------------------------------

def test_the_promotion_set_is_not_empty():
    """WITNESS. Every test below quantifies over USEFUL_GOODS; an empty set passes all of them."""
    assert len(_present()) >= 2, "the promotion set went empty -- these tests assert nothing"


def test_the_promoted_goods_classify_useful():
    for name in _present():
        assert ic.class_of(name) == ic.USEFUL, name
        assert core._item_class[name] == ItemClassification.useful, name


def test_their_category_is_unchanged_and_is_the_reason_this_is_per_name():
    """They stay `upgrade_materials`: the promotion is about how much finding one MATTERS, not about
    which inventory tab it is in. This is also the proof that a category flip was unavailable --
    they share the category with the smithing stones."""
    for name in _present():
        assert ic.category_of(name) == "upgrade_materials", name
    assert ic.CATEGORY_CLASS["upgrade_materials"] == ic.FILLER, (
        "upgrade_materials was promoted wholesale -- that moves filler_budget's entire tail into "
        "the useful tier, which is the change this carve-out exists to avoid")


def test_the_smithing_economy_is_untouched():
    for n in ("Smithing Stone [1]", "Somber Smithing Stone [1]", "Golden Rune [1]"):
        if n in core.ITEM_CATALOG:
            assert core._item_class[n] == ItemClassification.filler, n


def test_talismans_were_already_useful_and_stay_that_way():
    """They are ACCESSORY-nibble and were promoted by category long before this. If this ever fails
    the carve-out has started reaching items it was not meant to."""
    talismans = [n for n in core.ITEM_CATALOG if ic.category_of(n) == "talismans"]
    assert talismans, "no talismans in the catalog -- the fixture is wrong, not the code"
    for n in talismans:
        assert core._item_class[n] == ItemClassification.useful, n
    assert not (ic.USEFUL_GOODS & set(talismans)), "a talisman is in the goods promotion set"


# ---- 2. the economy floor ------------------------------------------------------------------------

def test_the_filler_economy_predicate_is_unmoved():
    """displaceable_filler already excluded these by name inside _is_junk_consumable, so the pool
    builder's budget must not shift. Asserted over every promoted name, not a sample."""
    world = _Stub()
    world._class_for = lambda n: core._item_class.get(n, ItemClassification.filler)
    for name in _present():
        assert displaceable_filler(world, name) is False, (
            "%s became displaceable filler -- the economy floor moved" % name)


# ---- 3. one taxonomy, asked once -----------------------------------------------------------------

def test_filler_foreign_does_not_call_a_promoted_good_filler():
    """🛑 THE REASON THE PROMOTION LIVES IN class_of AND NOT core._class_for. filler_foreign builds
    its candidate list from class_of; a promotion core knew about and this list did not would make
    a low filler_foreign_pct hold back an item the classification says may travel."""
    world = _Stub(item_shuffle=True)
    names = set(ff.filler_names(world))
    assert len(names) > 100, "the filler list went blind (%d names)" % len(names)
    for n in _present():
        assert n not in names, "%s is in the filler candidate list AND classified useful" % n


# ---- 4. the client can still resolve them --------------------------------------------------------

def test_every_promoted_name_is_still_client_resolvable():
    """🛑 THE TRAP. A promoted name that had been declared by a FEATURE would already own an AP id,
    so core's catalog loop (`if _nm not in item_name_to_id`) would skip it -- including the
    _AP_IDS_TO_ITEM_IDS line -- and the client could never resolve it to a game item. That is the
    scadu_supply failure. Promoting through the taxonomy rather than through a feature's ITEMS is
    precisely what avoids it, and this is the assertion that says so."""
    for name in _present():
        ap_id = core.item_name_to_id[name]
        assert str(ap_id) in core._AP_IDS_TO_ITEM_IDS, (
            "%s classifies useful but the client cannot resolve it" % name)
        assert core._AP_IDS_TO_ITEM_IDS[str(ap_id)] == core.ITEM_CATALOG[name]
