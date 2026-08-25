"""Golden Seeds and Sacred Tears are `useful`, and useful items can be pushed out to partners.

TWO CHANGES, ONE SUBJECT. Both are about the `useful` tier being wrong in a multiworld:

  * CLASSIFICATION. core._classify_full files every GOODS-nibble item as filler. That is right for
    ~900 consumables and crafting materials and wrong for the permanent power-ups: a Golden Seed is
    consumed once and raises your flask count for the rest of the run. Talismans were already right
    (ACCESSORY nibble -> useful) and this must not disturb them.

  * DISTRIBUTION. Measured on a real four-slot generation (2 Elden Ring, 2 Hollow Knight, stock AP
    0.6.7), 1,473 of 1,473 Elden Ring useful items stayed in Elden Ring worlds. Instrumenting
    Fill.remaining_fill showed why: the progression fill eats locations front-to-back and Hollow
    Knight is small and progression-dense, so its surviving free slots all sit past index 1876, while
    the useful tier only ever reaches the first 1,473. No item_rule of ours can fix that -- our
    locations being ACCEPTABLE is the problem -- so features/share_useful uses the opposite lever,
    AP's `non_local_items`.

🛑 THE ORDER OF THESE TWO MATTERS AND IS THE REASON THEY SHARE A FILE. Promotion alone moves Golden
Seeds OUT of the filler tier, which is the one tier that demonstrably does reach a partner, and INTO
the tier that does not. Shipping the promotion without the sharing lever would have made a partner's
haul strictly worse. A test that only checked the classification would have passed.
"""
import pytest

pytest.importorskip("worlds.eldenring")
WorldTestBase = pytest.importorskip("test.bases").WorldTestBase

from BaseClasses import ItemClassification                                  # noqa: E402

from worlds.eldenring import core                                           # noqa: E402
from worlds.eldenring.item_categories import USEFUL_GOODS, category_of      # noqa: E402
from worlds.eldenring.features import share_useful as su                    # noqa: E402
from worlds.eldenring.features import filler_foreign as ff                  # noqa: E402
from worlds.eldenring.features.filler_curation import displaceable_filler   # noqa: E402

GAME = "Elden Ring"


class _Opt:
    def __init__(self, value):
        self.value = value


class _Stub:
    def __init__(self, **opts):
        self.options = type("O", (), {k: _Opt(v) for k, v in opts.items()})()


# ---- classification ------------------------------------------------------------------------------

def test_the_promoted_goods_classify_useful():
    for name in USEFUL_GOODS:
        if name not in core.ITEM_CATALOG:
            continue                      # DLC name absent from a base-only catalog
        assert core._item_class[name] == ItemClassification.useful, name


def test_talismans_were_already_useful_and_stay_that_way():
    """They are ACCESSORY-nibble, so the pre-existing rule already covered them. If this ever fails
    the promotion has started reaching items it was not meant to."""
    talismans = [n for n in core.ITEM_CATALOG if category_of(n) == "talismans"]
    assert talismans, "no talismans in the catalog -- the fixture is wrong, not the code"
    for n in talismans:
        assert core._item_class[n] == ItemClassification.useful, n
    assert not (USEFUL_GOODS & set(talismans)), "talismans must not be in the goods promotion set"


def test_the_graded_economy_is_untouched():
    """Smithing stones, gloveworts and runes are filler_budget's tuned economy. Promoting them would
    move the whole filler floor, which is explicitly not what this change is."""
    for n in ("Smithing Stone [1]", "Somber Smithing Stone [1]", "Golden Rune [1]"):
        if n in core.ITEM_CATALOG:
            assert core._item_class[n] == ItemClassification.filler, n


def test_every_promoted_name_is_still_client_resolvable():
    """🛑 THE TRAP. A promoted name that had been declared by a FEATURE would already own an AP id,
    so core's catalog loop (`if _nm not in item_name_to_id`) would skip it -- including the
    _AP_IDS_TO_ITEM_IDS line -- and the client could never resolve it to a game item. That is the
    scadu_supply failure. The promotion lives inside the catalog loop precisely to avoid it."""
    for name in USEFUL_GOODS:
        if name not in core.ITEM_CATALOG:
            continue
        ap_id = core.item_name_to_id[name]
        assert str(ap_id) in core._AP_IDS_TO_ITEM_IDS, (
            "%s classifies useful but the client cannot resolve it" % name)
        assert core._AP_IDS_TO_ITEM_IDS[str(ap_id)] == core.ITEM_CATALOG[name]


def test_the_filler_economy_predicate_is_unmoved():
    """displaceable_filler already excluded these by name inside _is_junk_consumable, so the pool
    builder's budget must not shift. Asserted over the whole catalog, not a sample."""
    world = _Stub()
    world._class_for = lambda n: core._item_class.get(n, ItemClassification.filler)
    for name in USEFUL_GOODS:
        if name in core.ITEM_CATALOG:
            assert displaceable_filler(world, name) is False, (
                "%s became displaceable filler -- the economy floor moved" % name)


# ---- the two name-lists must agree ---------------------------------------------------------------

def test_filler_foreign_no_longer_calls_a_promoted_good_filler():
    """It reads the nibble, not the classification. Without the subtraction a low
    filler_foreign_pct would localize a Golden Seed as filler while everything else calls it
    useful -- and the count reported to the player would be counting the wrong pool."""
    world = _Stub(item_shuffle=True)
    names = set(ff.filler_names(world))
    for n in USEFUL_GOODS:
        if n in core.ITEM_CATALOG:
            assert n not in names, "%s is in the filler list AND classified useful" % n


def test_the_promoted_goods_are_in_the_shareable_useful_list():
    world = _Stub(item_shuffle=True)
    names = set(su.useful_names(world))
    for n in USEFUL_GOODS:
        if n in core.ITEM_CATALOG:
            assert n in names, "%s classifies useful but cannot be shared" % n


def test_the_two_lists_do_not_overlap():
    """A name cannot be both this world's filler and its shareable useful. If they ever overlap,
    one feature would force it local and the other force it foreign, and Main.py's
    `non_local_items -= local_items` would resolve it silently in favour of local."""
    world = _Stub(item_shuffle=True)
    filler, useful = set(ff.filler_names(world)), set(su.useful_names(world))
    # WITNESS. Without these the intersection is empty whenever either builder silently returns
    # nothing, and this test would pass for the wrong reason (tests/test_gf_vacuous_pass).
    assert len(filler) > 100, "the filler list went blind (%d names)" % len(filler)
    assert len(useful) > 100, "the useful list went blind (%d names)" % len(useful)
    assert not (filler & useful)


def test_useful_names_is_empty_without_item_shuffle():
    assert su.useful_names(_Stub(item_shuffle=False)) == []


# ---- the sharing lever ---------------------------------------------------------------------------

def test_share_useful_is_declared_and_off_by_default():
    assert "share_useful_pct" in su.ShareUsefulFeature.OPTIONS
    assert su.ShareUsefulPct.default == 0


class ShareUsefulDefault(WorldTestBase):
    game = GAME
    options = {"num_regions": 0, "item_shuffle": True}

    def test_default_shares_nothing_and_draws_nothing(self):
        feat = su.ShareUsefulFeature()
        before = self.world.random.getstate()
        self.assertEqual(feat.names_to_share(self.world), [])
        self.assertEqual(self.world.random.getstate(), before,
                         "the default consumed rng -- CLAUDE.md rule 6")

    def test_default_leaves_non_local_items_alone(self):
        self.assertEqual(self.world.options.non_local_items.value, set())


class ShareUsefulPartial(WorldTestBase):
    game = GAME
    options = {"num_regions": 0, "item_shuffle": True, "share_useful_pct": 25}

    def test_a_quarter_of_the_useful_names_are_forced_out(self):
        feat = su.ShareUsefulFeature()
        all_names = su.useful_names(self.world)
        shared = feat.names_to_share(self.world)
        self.assertTrue(shared)
        self.assertEqual(len(shared), (len(all_names) * 25 + 50) // 100)
        self.assertTrue(set(shared) <= set(all_names))

    def test_generate_early_put_them_in_non_local_items(self):
        forced = self.world.options.non_local_items.value
        self.assertTrue(forced, "nothing was forced out -- locality_rules will do nothing")
        self.assertTrue(forced <= set(su.useful_names(self.world)),
                        "a name outside the useful pool was forced out")

    def test_no_progression_item_is_ever_forced_out(self):
        """Region Locks are the progression. This knob must never touch them -- forcing a Lock out
        of its own world is progression_bias's job and it has its own reachability handling."""
        for name in self.world.options.non_local_items.value:
            self.assertNotEqual(core._item_class.get(name), ItemClassification.progression, name)


class ShareUsefulAll(WorldTestBase):
    game = GAME
    options = {"num_regions": 0, "item_shuffle": True, "share_useful_pct": 100}

    def test_the_endpoint_is_exact(self):
        feat = su.ShareUsefulFeature()
        self.assertEqual(set(feat.names_to_share(self.world)), set(su.useful_names(self.world)))
