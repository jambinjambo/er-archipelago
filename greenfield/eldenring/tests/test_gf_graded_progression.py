"""graded_progression -- the player-power half of the difficulty curve.

WHAT THIS FILE IS DEFENDING, AND WHY IT IS SHAPED THIS WAY
----------------------------------------------------------
The option exists because a real 2026-08-27 six-region multiworld saturated the player's upgrade
curve one or two regions in and then flattened, while `features/scaling.py` went on ramping enemy
difficulty over the whole seed. The mechanism is a receive-ordered ladder: the Kth smithing stone
the multiworld hands you grants the tier the ladder says.

So the property under test is NOT "is there a graded item in the pool". It is:

  1. THE LADDER IS MONOTONE AND EXACTLY AS LONG AS THE POOL. A ladder one rung short of the copy
     count overflows its tail copies to a Lord's Rune client-side -- stones silently becoming
     currency, which is a worse version of the bug the feature exists to fix.
  2. NOTHING BYPASSES IT. Three separate things could hand a player a top rung in one pickup: a
     loose tiered `Smithing Stone [8]` (substitution), a loose vanilla Miner's Bell Bearing
     (features/presence_floor's roster injection), and a loose Golden Seed. Each has its own
     assertion below, because each has its own door, and #539 is the precedent for exactly one of
     those doors being left open while the other was closed.
  3. THE FLOOR SURVIVES THE CEILING. `filler_budget`'s `local_early_items` guarantee is what makes
     +3 affordable in the first area; the ladder must not have quietly replaced it with nothing by
     declaring a name the pool no longer holds.

The pure half runs without Archipelago and without a generation, because the ladder is a closed form
over a fixed cost table and deserves to be checked as one.
"""
import collections

import pytest

WorldTestBase = pytest.importorskip("test.bases").WorldTestBase
pytest.importorskip("worlds.eldenring")

from worlds.eldenring.features import filler_budget as _fb          # noqa: E402
from worlds.eldenring.features import graded_progression as _gp     # noqa: E402
from worlds.eldenring.features import progressive as _prog          # noqa: E402
from worlds.eldenring.item_ids import ITEM_CATALOG                  # noqa: E402
from worlds.eldenring.tests._util import world_pool_items           # noqa: E402

GAME = "Elden Ring"

# Every tiered stone name the ladder replaces. If ANY of these is still in a graded pool, a player
# can be handed that tier out of order and the whole feature is decoration.
TIERED_STONES = frozenset(_prog.VANILLA_STONE_ITEMS)
STONE_LADDERS = (_prog.PROG_SMITHING_STONE, _prog.PROG_SOMBER_STONE)


# =================================================================================================
# PURE -- the ladder is a closed form, so check it as one
# =================================================================================================
def test_the_tier_sequence_agrees_with_the_pool_sizer():
    """🛑 THE MIRROR GATE. `progressive.regular_stone_tier_seq` and `filler_budget._regular_stone_need`
    are two readings of ONE game constant (the 2/4/6 reinforce cost table under
    flatten_regular_upgrades). They live in different modules because one needs the ORDER and the
    other needs the TOTALS, and filler_budget imports progressive so the dependency cannot be
    reversed. Two copies of one constant is exactly the drift this repo gates elsewhere
    (scadu_supply.SCADU_CUM against the Rust ladder, scaling_ladder against SCALING_TIERS), so it is
    gated here too: if the ladder and the reservation ever disagree about what +24 costs, the seed
    buys a number of stones that does not match the ladder it is buying them for."""
    for flatten in range(0, 5):
        seq = _prog.regular_stone_tier_seq(flatten)
        assert collections.Counter(seq) == dict(_fb._regular_stone_need(flatten)), (
            "at flatten_regular_upgrades=%d the ladder's per-tier counts differ from the "
            "reservation's. One of the two copies of the cost table has moved." % flatten)


# The table Alaric gave, verbatim (2026-08-28). Stated here rather than derived, because a test
# that re-derives `floor(N * 2.5)` and compares it to `floor(N * 2.5)` gates nothing -- what needs
# gating is that the code still agrees with the RULING.
SOMBER_EQUIVALENT = {1: 2, 2: 5, 3: 7, 4: 10, 5: 12, 6: 15, 7: 17, 8: 20, 9: 22, 10: 25}


def test_the_somber_equivalence_matches_the_ruling():
    for somber, regular in SOMBER_EQUIVALENT.items():
        assert _prog.somber_to_regular(somber) == regular, (
            "somber %d should be worth a standard +%d, got +%d"
            % (somber, regular, _prog.somber_to_regular(somber)))
    assert _prog.SOMBER_EQUIV_RATIO == 2.5


def test_the_inverse_never_overclaims():
    """`regular_to_somber` rounds DOWN. Regular +3 is somber ONE (+2), not somber two (+5) -- an
    early guarantee that took the nearest tier would promise more than it was asked for, which is
    the over-generosity the conversion exists to end (filler_budget._somber_stone_need's note)."""
    assert _prog.regular_to_somber(3) == 1
    assert _prog.regular_to_somber(4) == 1
    assert _prog.regular_to_somber(5) == 2
    assert _prog.regular_to_somber(25) == _prog.ANCIENT_SOMBER_TIER
    assert _prog.regular_to_somber(1) == 0, "nothing is worth less than somber 1 (+2)"
    for somber, regular in SOMBER_EQUIVALENT.items():
        assert _prog.regular_to_somber(regular) == somber, regular


def test_both_tracks_top_out_at_the_same_power():
    """The ladders end level, which is the point of including the two Ancient Dragon steps: the
    numbered tiers alone stop at +24 and somber +22-equivalent, so the tracks used to finish two
    levels apart."""
    assert _prog.somber_to_regular(_prog.ANCIENT_SOMBER_TIER) == _prog.REGULAR_CAP_LEVEL == 25
    assert _prog.graded_regular_seq(2)[-1] == _prog.ANCIENT_REGULAR_TIER
    assert _prog.stone_tier_name(_prog.PROG_SMITHING_STONE,
                                _prog.ANCIENT_REGULAR_TIER) == _prog.ANCIENT_REGULAR
    assert _prog.stone_tier_name(_prog.PROG_SOMBER_STONE,
                                 _prog.ANCIENT_SOMBER_TIER) == _prog.ANCIENT_SOMBER


def test_each_somber_rung_arrives_where_its_equivalent_does():
    """🛑 THE CONVERSION DOING ITS WORK. Somber tier N is worth regular `somber_to_regular(N)`, so
    it must arrive at the fraction of the run where the REGULAR ladder reaches that level. This is
    what replaces the old uniform stretch, which assumed every somber rung was worth the same
    progress -- somber 1->2 spans three regular levels (+2 to +5) and 2->3 spans two (+5 to +7)."""
    for flatten in (0, 2, 3):
        shares = _prog.somber_share_schedule(flatten)
        costs = _prog.regular_level_costs(flatten)
        cum, run = {}, 0
        for lvl, _t, c in costs:
            run += c
            cum[lvl] = run
        cum[_prog.REGULAR_CAP_LEVEL] = run + 1
        total = cum[_prog.REGULAR_CAP_LEVEL]
        assert len(shares) == _prog.ANCIENT_SOMBER_TIER
        assert shares == sorted(shares), shares
        assert abs(shares[-1] - 1.0) < 1e-9, "the last somber rung is the end of the run"
        for n, regular in SOMBER_EQUIVALENT.items():
            assert abs(shares[n - 1] - cum[regular] / total) < 1e-9, (flatten, n)


def test_the_tier_counts_mirror_the_reservation():
    assert _prog.STONE_TIERS == _fb.STONE_TIERS
    assert _prog.SOMBER_TIERS == _fb.SOMBER_TIERS
    assert _prog.somber_stone_tier_seq() == list(range(1, _fb.SOMBER_TIERS + 1)), (
        "somber costs one stone per level and the tier IS the level, so the ladder is the tiers "
        "in order -- see filler_budget._somber_stone_need")


def test_every_rung_names_a_stone_the_client_can_grant():
    """A rung resolves to a game FullID through ITEM_CATALOG. A data rename that dropped one would
    otherwise surface as a stone silently becoming a Lord's Rune in someone's run."""
    missing = sorted(n for n in TIERED_STONES if n not in ITEM_CATALOG)
    assert not missing, (
        "graded_progression substitutes these names but the catalog does not hold them, so the "
        "ladder would have unreachable rungs: %s" % missing)
    for name in STONE_LADDERS:
        tiers = (_prog.ANCIENT_SOMBER_TIER if name == _prog.PROG_SOMBER_STONE
                 else _prog.ANCIENT_REGULAR_TIER)
        for t in range(1, tiers + 1):
            assert _prog.stone_tier_name(name, t) in ITEM_CATALOG, (name, t)


@pytest.mark.parametrize("n", [0, 1, 5, 20, 47, 48, 49, 96, 300])
def test_stretch_ladder_is_length_exact_and_monotone(n):
    """The two properties the client contract needs: exactly one rung per pool copy (else the tail
    copies overflow to a Lord's Rune), and never DECREASING (a ladder that went back down would hand
    a player a worse stone than the one before, which is jaggedness with extra steps)."""
    seq = _prog.regular_stone_tier_seq(2)
    out = _prog.stretch_ladder(seq, n)
    assert len(out) == n
    assert all(a <= b for a, b in zip(out, out[1:])), out


def test_stretch_reaches_the_top_only_at_the_end_on_a_generous_seed():
    # (stretch_ladder is the primitive `build_ladder` lays over each of its two segments)
    """🛑 THE ANTI-PADDING ASSERTION, and the reason `stretch_ladder` is not three lines shorter.

    A large seed holds far more stones than the 48 a +24 costs at flatten 2. The obvious
    implementation truncates the ladder at 48 and pads the rest with the top tier -- which hands the
    player the whole ladder at ~40% depth and flattens the curve for the remaining 60% of the run.
    That is the bug this feature exists to fix, arriving slightly later. So a stretched ladder must
    reach its top tier at the LAST rung and not before."""
    seq = _prog.regular_stone_tier_seq(2)
    out = _prog.stretch_ladder(seq, 4 * len(seq))
    assert out[-1] == seq[-1], "a stretched ladder must still reach the top tier"
    first_top = out.index(seq[-1])
    assert first_top > 0.5 * len(out), (
        "the stretched ladder reaches its top tier at rung %d of %d -- it is padding, not "
        "stretching, and the back half of the run has no curve" % (first_top, len(out)))
    assert out[:6] == [1] * 6, "a generous seed should still open on tier 1"


@pytest.mark.parametrize("n", [0, 1, 5, 12, 47, 48, 49, 96, 300])
def test_build_ladder_is_length_exact_and_monotone(n):
    seq = _prog.graded_regular_seq(2)
    out = _prog.build_ladder(seq, n, 6, 12)
    assert len(out) == n
    assert all(a <= b for a, b in zip(out, out[1:])), out


@pytest.mark.parametrize("n", [0, 1, 5, 9, 10, 11, 40, 119, 300])
def test_the_somber_ladder_is_length_exact_monotone_and_gapless(n):
    """The somber track has its own builder now (paced by the equivalence), so it needs its own
    version of the length/monotonicity contract -- plus one the regular track does not have: NO
    SKIPPED TIER. A somber weapon cannot pass a level it holds no stone for, so a gap is a
    permanent wall, which is what filler_budget._somber_coverage_floor was written about."""
    out = _prog.build_somber_ladder(n, 2)
    assert len(out) == n
    assert all(a <= b for a, b in zip(out, out[1:])), out
    if n >= _prog.ANCIENT_SOMBER_TIER:
        assert set(out) == set(range(1, _prog.ANCIENT_SOMBER_TIER + 1)), (
            "tier(s) %s are skipped -- a somber weapon stops there permanently"
            % sorted(set(range(1, _prog.ANCIENT_SOMBER_TIER + 1)) - set(out)))


def test_a_rich_seed_spreads_evenly_across_the_tiers():
    """🛑 THE REGRESSION THIS PINS, spotted by Alaric in the somber heatmap: "why are there so few
    somber 1's and 2's".

    `early_copies` used to be a CAP on segment 1 rather than a floor, so the tiers below the split
    stopped growing with the seed while the tiers above kept growing. 119 somber copies came out
    **[2, 2, 2, 19, 19, 19, 19, 19, 18]**.

    That is not a cosmetic skew. Somber costs one stone per level and the tier IS the level, so a
    weapon passes +3 only by spending one each of tiers 1, 2 and 3 -- two copies of each caps the
    seed at TWO somber weapons ever getting past +3, while a hundred higher stones sit unreachable.

    So: on a seed far richer than the ladder is long, no tier may be starved relative to the others.
    Half the mean is a deliberately loose bar -- it is not trying to pin a distribution, it is
    trying to make [2, 2, 2, 19, ...] impossible to ship again."""
    N = 200
    seq = _prog.graded_regular_seq(2)
    shares = _prog.somber_share_schedule(2)
    # what each rung is OWED, not a flat mean: the rungs are not interchangeable. A numbered regular
    # tier covers three levels and six stones; the Ancient Dragon rung covers one level and one
    # stone, so a flat mean would call its honest ~1/49 share "starved". Somber rungs are owed their
    # gap in the equivalence schedule -- somber 1->2 spans three regular levels, 2->3 spans two.
    owed_regular = {t: N * seq.count(t) / len(seq) for t in set(seq)}
    owed_somber = {n + 1: N * (shares[n] - (shares[n - 1] if n else 0.0))
                   for n in range(_prog.ANCIENT_SOMBER_TIER)}
    for lad, owed, label in (
        (_prog.build_somber_ladder(N, 2), owed_somber, "somber"),
        (_prog.build_ladder(seq, N, 6, 12), owed_regular, "regular"),
    ):
        counts = collections.Counter(lad)
        tiers = sorted(owed)
        assert set(counts) == set(tiers), (
            "%s: rung(s) %s never appear in a %d-copy ladder"
            % (label, sorted(set(tiers) - set(counts)), N))
        starved = {t: (counts[t], round(owed[t], 1)) for t in tiers if counts[t] < owed[t] / 2}
        assert not starved, (
            "%s ladder starves rung(s) %r (count, owed) -- the early segment is capping the low "
            "tiers instead of flooring them: %r"
            % (label, starved, [counts[t] for t in tiers]))
        assert lad[-1] == tiers[-1], "%s must still top out at the last rung" % label


def test_the_regular_early_promise_survives_a_rich_seed():
    """The REGULAR guarantee is unaffected by the proportional floor, and that is worth pinning
    separately from the somber one: `+EARLY_TARGET_LEVEL` is the whole tier-1 band, so the first
    rungs are tier 1 at any copy count."""
    reg = _prog.build_ladder(_prog.regular_stone_tier_seq(2), 200, 6, 12)
    assert reg[:12] == [1] * 12, reg[:12]


def test_the_somber_early_promise_is_paced_by_the_equivalence():
    """⭐ WHAT THE SOMBER GUARANTEE BECOMES UNDER A LADDER, pinned so the trade is deliberate.

    Somber level IS the current rung -- you hold at least one of every tier below it -- so the
    ladder's shape is the somber pacing curve itself. On a rich seed the proportional floor puts
    many tier-1 copies before tier 2, so the guarantee's early copies buy **+1**, and +3 arrives
    part-way in rather than in the first handful of items.

    That is the right side of the trade: compressing +3 into the first six items is the instant
    saturation this whole feature exists to prevent, in miniature, and it costs the entire rest of
    the distribution to buy. `features/progressive._early_segment` states it; this pins it."""
    lad = _prog.build_somber_ladder(200, 2)
    assert set(lad[:6]) == {1}, (
        "the early somber copies are %r -- if this now spans tiers the ladder has gone back to "
        "front-loading" % lad[:6])
    # SOMBER 1 IS THE EQUIVALENT OF THE REGULAR TARGET (+2 against +3), so the guarantee is met by
    # tier 1 and nothing above it is owed early.
    assert _prog.somber_to_regular(1) <= _fb.EARLY_TARGET_LEVEL < _prog.somber_to_regular(2)
    # ...and the rest must still ARRIVE, spread across the run rather than bunched at the end.
    assert lad.index(3) < 0.5 * len(lad), "somber +7-equivalent arrives too late"
    assert lad.index(_prog.ANCIENT_SOMBER_TIER) > 0.8 * len(lad), (
        "the top somber rung arrives at %d of %d -- it should be the end of the run"
        % (lad.index(_prog.ANCIENT_SOMBER_TIER), len(lad)))


def test_an_exact_ladder_still_reaches_the_cap():
    """The regression the early segment introduced and the surplus rule fixes: a seed holding
    EXACTLY the full ladder has no surplus to pay the early guarantee's 2x margin out of, so the
    margin must stand down rather than eat the rungs the top of the track needs."""
    for flatten in (0, 1, 2, 3, 4):
        seq = _prog.graded_regular_seq(flatten)
        split, early = _prog._early_segment(_prog.PROG_SMITHING_STONE, flatten)
        out = _prog.build_ladder(seq, len(seq), split, early)
        assert out == seq, (
            "at flatten=%d a seed holding exactly the full ladder does not get the full ladder: "
            "the early segment took %d copies it could not afford" % (flatten, early))
    n = _prog.ANCIENT_SOMBER_TIER
    assert _prog.build_somber_ladder(n, 0) == list(range(1, n + 1)), (
        "a seed holding exactly one somber stone per rung must get exactly that")


def test_a_short_ladder_truncates_rather_than_compressing():
    """A seed too small for the full ladder tops out LOW -- it does not compress the whole reinforce
    track into its handful of stones. Stated in the log by Progressive.set_rules; pinned here."""
    seq = _prog.graded_regular_seq(2)
    out = _prog.stretch_ladder(seq, 20)
    assert out == seq[:20]
    assert out[-1] < seq[-1], "a 20-stone seed must not reach the top tier"


# =================================================================================================
# OFF -- the shipped default must be byte-identical to today
# =================================================================================================
class GradedOff(WorldTestBase):
    game = GAME
    options = {"num_regions": 4, "item_shuffle": True}

    def test_the_default_is_off_and_inert(self):
        self.assertFalse(_gp.is_on(self.world))
        names = {i.name for i in world_pool_items(self)}
        for ladder in STONE_LADDERS:
            self.assertNotIn(ladder, names,
                             "graded_progression is off but its ladder item is in the pool")
        self.assertTrue(names & TIERED_STONES,
                        "with the option off the pool must still hold tiered smithing stones")

    def test_no_stone_ladder_reaches_the_wire(self):
        grants = _prog.Progressive().slot_data(self.world)["progressiveGrants"]
        for ladder in STONE_LADDERS:
            self.assertNotIn(ladder, grants)


# =================================================================================================
# ON -- the ladder, and the three doors that could bypass it
# =================================================================================================
class GradedOn(WorldTestBase):
    game = GAME
    options = {"num_regions": 4, "item_shuffle": True, "graded_progression": True}

    def _names(self):
        return [i.name for i in world_pool_items(self)]

    def test_it_is_armed(self):
        self.assertTrue(_gp.is_on(self.world))

    def test_no_tiered_stone_survives_in_the_pool(self):
        """DOOR 1 -- the loose tiered stone. Both sources have to be closed: core's item-shuffle walk
        (features/progressive.vanilla_substitutions) and the economy reservation
        (filler_budget._draw_stones). Closing one and not the other leaves a pool that holds a ladder
        AND the tiers it is pacing, which is not a partial fix -- a single `Smithing Stone [8]` in
        sphere 0 is the whole bypass."""
        names = self._names()
        # 🛑 THE WITNESS. `assertEqual(left, [])` passes just as happily when the scan saw nothing at
        # all: if `_names()` ever stopped returning this world's items, this test would go green
        # while the pool was full of tiered stones. tests/test_gf_vacuous_pass.py's ratchet caught
        # exactly that the day this file landed, which is the ratchet doing its job.
        self.assertIn(_prog.PROG_SMITHING_STONE, names,
                      "the pool holds no ladder copies at all -- this test has lost its subject, "
                      "and an empty intersection below would mean nothing")
        left = sorted(set(names) & TIERED_STONES)
        self.assertEqual(left, [], "these tiered stones bypass the ladder: %s" % left)

    def test_the_ladders_are_in_the_pool_and_are_filler(self):
        names = self._names()
        for ladder in STONE_LADDERS:
            self.assertIn(ladder, names, "%s is armed but has no copies" % ladder)
        # `useful` is the head of AP's restitempool; promoting the hundreds-strong smithing economy
        # into that tier would move every seed. See the ITEMS comment in features/progressive.py.
        from BaseClasses import ItemClassification as IC
        for it in world_pool_items(self):
            if it.name in STONE_LADDERS:
                self.assertEqual(it.classification, IC.filler, "%s must stay filler" % it.name)

    def test_the_wire_ladder_is_exactly_as_long_as_the_pool(self):
        """The client counts received copies and grants rung K-1. A ladder shorter than the copy
        count overflows its tail copies to a Lord's Rune; longer, and the last rungs are unreachable
        and the stated cap is a lie."""
        counts = collections.Counter(self._names())
        grants = _prog.Progressive().slot_data(self.world)["progressiveGrants"]
        for ladder in STONE_LADDERS:
            self.assertIn(ladder, grants)
            self.assertEqual(len(grants[ladder]), counts[ladder],
                             "%s: %d rungs against %d pool copies"
                             % (ladder, len(grants[ladder]), counts[ladder]))
            self.assertEqual(_prog.stone_copy_count(self.world, ladder), counts[ladder])

    def test_every_rung_is_a_consumed_goods_grant(self):
        """`consumed` is not optional and does not default (contract._chk_nested_grants). A smithing
        stone is SPENT at a grace, so shipped as OWNED the client's self-healing `unique_goods` path
        would see it leave the inventory and hand it back forever -- the 2026-07-12 flask-tear CTD,
        rebuilt."""
        grants = _prog.Progressive().slot_data(self.world)["progressiveGrants"]
        for ladder in STONE_LADDERS:
            for rung in grants[ladder]:
                self.assertIn("goods", rung)
                self.assertIs(rung.get("consumed"), True, "a spent good must be consumed=True")

    def test_the_wire_ladder_is_monotone(self):
        grants = _prog.Progressive().slot_data(self.world)["progressiveGrants"]
        for ladder in STONE_LADDERS:
            # goods FullID -> rung, built from the ladder's OWN naming rather than by parsing "[n]"
            # out of the item name: the top rung of each track is the un-numbered Ancient Dragon
            # stone, which no such parse can read.
            top = (_prog.ANCIENT_SOMBER_TIER if ladder == _prog.PROG_SOMBER_STONE
                   else _prog.ANCIENT_REGULAR_TIER)
            by_good = {ITEM_CATALOG[_prog.stone_tier_name(ladder, t)]: t
                       for t in range(1, top + 1)}
            tiers = [by_good[r["goods"]] for r in grants[ladder]]
            self.assertEqual(tiers, sorted(tiers),
                             "%s hands out a lower tier after a higher one" % ladder)
            self.assertEqual(tiers, _prog.stone_ladder(self.world, ladder),
                             "the wire disagrees with the ladder the world computed")

    def test_it_forces_the_flask_and_bell_ladders_on(self):
        """DOORS 2 AND 3. A loose Miner's Bell Bearing is a permanent unlimited shop unlock for a
        whole tier band, so it walks straight past the stone ladder (#539, boblerrr 2026-08-10); a
        loose Golden Seed is the same shape for flask charges. Neither toggle is named in this
        class's options, so this is the override doing the work."""
        self.assertTrue(_prog._bells_on(self.world))
        self.assertTrue(_prog._flasks_on(self.world))
        names = set(self._names())
        self.assertIn(_prog.PROG_FLASK, names)
        for bell in (_prog.PROG_SMITHING_BELL, _prog.PROG_SOMBER_BELL):
            self.assertIn(bell, names)
        left = sorted(names & set(_prog.VANILLA_BELL_ITEMS))
        self.assertEqual(left, [], "these vanilla bell bearings bypass the ladder: %s" % left)
        for flask_item in ("Golden Seed", "Sacred Tear"):
            self.assertNotIn(flask_item, names)

    def test_presence_floor_does_not_re_inject_the_bearings(self):
        """The SECOND door onto the bells, and the one #539 needed two edits to close. Substitution
        only removes a bearing that sat on a KEPT check; features/presence_floor injects a copy of
        every roster bearing whose home region was not kept. It reads the predicate, not the raw
        option -- if it ever reads the option again, a graded seed silently regains the bypass for
        precisely the bearings substitution never saw."""
        from worlds.eldenring.features import presence_floor as _pf
        injected = set(_pf.absent_roster(self.world))
        self.assertEqual(sorted(injected & _pf.BELL_BEARING_ITEMS), [])
        self.assertTrue(injected, "the physick half of the roster should still be injected")

    def test_the_early_guarantee_still_pays_and_names_the_ladder(self):
        """THE FLOOR SURVIVES THE CEILING. `early_guarantee` must name the item the pool actually
        holds: declaring `Smithing Stone [1]` in a graded seed would clamp to zero copies and warn
        about a shortfall that is really a rename, silently deleting the +3-in-the-first-area
        promise while looking armed."""
        want = _fb.early_guarantee(self.world)
        self.assertEqual(sorted(want), sorted(STONE_LADDERS))
        self.assertTrue(all(n > 0 for n in want.values()))
        early = self.multiworld.local_early_items[self.player]
        for ladder in STONE_LADDERS:
            self.assertGreater(early.get(ladder, 0), 0,
                               "%s was never declared to local_early_items" % ladder)
            self.assertEqual(early[ladder], want[ladder],
                             "the early guarantee was clamped -- the pool is short of rungs")

    def test_the_declared_early_copies_actually_buy_the_promised_level(self):
        """END TO END, and the reason the two-segment ladder exists.

        `early_guarantee` declares N copies to `local_early_items`; the ladder decides what those N
        copies are worth. Asserting only that the declaration was made (the test above) would have
        passed while the somber half delivered +1 -- the promise lives in the two numbers AGREEING,
        so it has to be checked where they meet."""
        want = _fb.early_guarantee(self.world)
        flatten = _prog._flatten(self.world)

        reg = _prog.stone_ladder(self.world, _prog.PROG_SMITHING_STONE)
        early_reg = reg[:want[_prog.PROG_SMITHING_STONE]]
        # +EARLY_TARGET_LEVEL is the whole tier-1 band, so its cost is that band's stone count.
        need_t1 = _fb._regular_stone_need(flatten)[1]
        self.assertGreaterEqual(
            early_reg.count(1), need_t1,
            "the early guarantee declares %d regular copies but only %d of them are tier 1; +%d "
            "costs %d" % (len(early_reg), early_reg.count(1), _fb.EARLY_TARGET_LEVEL, need_t1))

        # THE SOMBER HALF IS PACED, NOT INSTANT -- see
        # test_the_somber_early_promise_is_paced_not_instant for the ruling. What must hold here is
        # that the declared copies are real rungs at the BOTTOM of the ladder, so they are worth
        # something on arrival rather than being high tiers the player cannot yet spend.
        somber = _prog.stone_ladder(self.world, _prog.PROG_SOMBER_STONE)
        early_somber = somber[:want[_prog.PROG_SOMBER_STONE]]
        self.assertTrue(early_somber, "no somber rungs at all")
        self.assertEqual(
            min(early_somber), 1,
            "the earliest somber copies start at tier %d -- a somber stone above tier 1 cannot be "
            "spent until every tier below it has arrived, so an early guarantee that does not "
            "start at the bottom buys nothing" % min(early_somber))
        want_tier = max(1, _prog.regular_to_somber(_fb.EARLY_TARGET_LEVEL))
        self.assertLessEqual(
            max(early_somber), want_tier,
            "the early somber copies reach tier %d, past the somber %d that regular +%d converts "
            "to -- the guarantee is promising more than it was asked for"
            % (max(early_somber), want_tier, _fb.EARLY_TARGET_LEVEL))

    def test_the_pool_stays_count_exact(self):
        """The ladder is pure substitution, so it must not have moved the count by one either way."""
        self.assertEqual(len(world_pool_items(self)),
                         len(self.multiworld.get_locations(self.player)))


# =================================================================================================
# THE FOURTH DOOR -- the flask, which graded_progression FORCES ON and therefore has to substitute
# =================================================================================================
class GradedForcesTheFlaskLadder(WorldTestBase):
    """🛑 THE YAML SAYS `progressive_flasks: false` ON PURPOSE. That is not a stress case, it is the
    shipped shape of the seed this whole feature came from, and it is the exact combination that hid
    the bug this class exists to stop coming back (found 2026-08-29 by reading a graded archive).

    `features/progressive.vanilla_substitutions` asked `world.options.progressive_flasks` directly
    while everything else on the flask path -- `flask_copy_count`, `flask_ladder`, `_grant_ladder`,
    the slot_data emit -- asked the `_flasks_on` PREDICATE, which graded_progression overrides. So a
    graded seed shipped a full-length `flaskLadder` and a full `progressiveGrants` entry for an item
    the pool held ZERO copies of, while the Golden Seeds stayed vanilla.

    Nothing crashed. The vanilla seeds still worked the vanilla way, generation succeeded, and the
    wire looked correct -- which is precisely why it survived: the feature went silently dark. That
    is the failure mode CLAUDE.md rule 3 names, and the same door `features/presence_floor.py` had to
    close for the bells (#539).
    """
    game = GAME
    options = {"num_regions": 4, "item_shuffle": True,
               "graded_progression": True, "progressive_flasks": False}

    def _names(self):
        return [i.name for i in world_pool_items(self)]

    def test_the_predicate_overrides_the_yaml(self):
        self.assertTrue(_gp.is_on(self.world))
        self.assertFalse(self.world.options.progressive_flasks.value,
                         "this class is pointless unless the yaml really does say false")
        self.assertTrue(_prog._flasks_on(self.world),
                        "graded_progression must force the flask ladder on")

    def test_no_vanilla_flask_item_survives_in_the_pool(self):
        names = self._names()
        self.assertIn(_prog.PROG_FLASK, names,
                      "the pool holds no flask ladder copies at all -- the substitution did not "
                      "run, so the empty intersection below would mean nothing")
        left = sorted(set(names) & set(_prog.VANILLA_FLASK_ITEMS))
        self.assertEqual(left, [], "these bypass the flask ladder: %s" % left)

    def test_the_wire_agrees_with_the_pool(self):
        """A ladder emitted for an item with no copies is the bug wearing a working wire. Both
        lengths must equal the copies the pool actually holds."""
        copies = self._names().count(_prog.PROG_FLASK)
        self.assertGreater(copies, 0)
        sd = _prog.Progressive().slot_data(self.world)
        self.assertEqual(len(sd["flaskLadder"]), copies)
        self.assertEqual(len(sd["progressiveGrants"][_prog.PROG_FLASK]), copies)
        self.assertEqual(copies, _prog.flask_copy_count(self.world))

    def test_the_pool_stays_count_exact(self):
        self.assertEqual(len(world_pool_items(self)),
                         len(self.multiworld.get_locations(self.player)))


# =================================================================================================
# THE TWO VANILLA MODES STAND IT DOWN
# =================================================================================================
class GradedUnderVanillaPool(WorldTestBase):
    game = GAME
    options = {"num_regions": 4, "item_shuffle": True,
               "graded_progression": True, "vanilla_pool": True}

    def test_vanilla_pool_wins(self):
        """Both modes promise a check pays what vanilla paid it, and vanilla_pool additionally
        leaves no stone economy for a ladder to be built out of. Gated inside `is_on` so the pool
        and the predicate cannot disagree."""
        self.assertFalse(_gp.is_on(self.world))
        names = {i.name for i in world_pool_items(self)}
        for ladder in STONE_LADDERS:
            self.assertNotIn(ladder, names)
        self.assertTrue(names & TIERED_STONES,
                        "vanilla_pool should leave the vanilla tiered stones where they were")
