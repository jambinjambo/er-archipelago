"""Unified "Progressive Flask Upgrade" -- alternating charge and potency rungs, stretched over the
seed's own copy count.

Every Golden Seed / Sacred Tear check pays a single "Progressive Flask Upgrade" item. The rungs
alternate one axis at a time: Charge, +1 potency, Charge, +1. The item rides both wires, but only the
scheduled wire advances for a given copy:
  * CHARGES = a reconciled LEVELED STATE (contract.flaskLadder). The client reconciles the flask
    charge target to flaskLadder[K-1]["charges"] after K copies -- a direct write, no spend to heal.
  * POTENCY = GRANTED consumed Sacred Tears (progressiveGrants). Each copy grants ONE consumed Sacred
    Tear (good 10020); the player upgrades potency at a grace the vanilla way, which updates every
    flask mirror safely. consumed=True is REQUIRED (an OWNED build re-granted spent tears unbounded and
    CTD'd, playtest 2026-07-12; the in-place potency item-id swap CTD'd on death against the
    half-updated mirrors, playtest 2026-07-19). One tear per copy => one ledger entry per stream index
    => no batching problem.

🛑 THE SCHEDULE IS STRETCHED OVER THE SEED'S OWN COPY COUNT (2026-08-29), which is what most of
this file is now about. The flask holds exactly FLASK_UPGRADES = 22 upgrades: ten charge steps
(4 -> 14) and twelve tears (0 -> 12), and a rung carries at most one. So:

  * a seed with <= 22 copies spends every one of them, on the first N of the alternating sequence --
    identical to the old ordinal schedule, which is why small seeds did not move;
  * a seed with MORE than 22 copies spreads the twenty-two across all of them, first upgrade on the
    first copy and last upgrade on the last, with the surplus interleaved as no-ops.

The surplus is the game's ceiling, not a scheduling failure -- there are only twenty-two upgrades.
The old schedule packed them into the first twenty-two copies whatever the seed held, which left a
flat tail (charges stopped climbing at a median 67% of the run over ten measured slots) and a dead
tail (14% of pickups granted nothing).

This file guards: progressiveGrants grants a consumed Sacred Tear on exactly the rungs where the
flaskLadder's potency advances, and an explicit no-op everywhere else; charges and potency are
monotone and never advance together or by more than one; the first copy always visibly advances the
vanilla starting allocation; a seed with at least 22 copies finishes BOTH axes and finishes them on
its LAST rung; LENGTH == the PROG_FLASK copies the seed has (the substituted seed/tear checks, or
DLC_ONLY_FLASK_COPIES injected under dlc_only).

The vanilla cost tables (FLASK_CHARGE_SEED_COST / FLASK_POTENCY_TEAR_COST) are retained as documented
data; test_cost_tables_match_tools keeps them equal to tools/upgrade_costs.py (one datum, one source).
"""
import pytest

WorldTestBase = pytest.importorskip("test.bases").WorldTestBase
pytest.importorskip("worlds.eldenring")

from worlds.eldenring import contract  # noqa: E402
from worlds.eldenring.features import progressive as pg  # noqa: E402

from ._util import world_item_names  # noqa: E402

GAME = "Elden Ring"


# ---- pure-data guards (no world) ---------------------------------------------------------------
def test_cost_tables_match_tools():
    """The feature MIRRORS tools/upgrade_costs.py rather than importing it (tools/ is a script package
    -- sys.path hacks, no __init__, not guaranteed to ship inside the apworld zip). That is only safe
    if a gate keeps the two copies equal. This is the gate."""
    import importlib.util
    import pathlib

    tools = pathlib.Path(pg.__file__).resolve().parent.parent / "tools" / "upgrade_costs.py"
    if not tools.is_file():
        pytest.skip(f"tools/upgrade_costs.py not shipped here ({tools})")
    spec = importlib.util.spec_from_file_location("_er_upgrade_costs", tools)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert list(mod.FLASK_CHARGE_SEED_COST) == list(pg.FLASK_CHARGE_SEED_COST), (
        "seed cost ladder drifted from tools/upgrade_costs.py -- one datum, one source")
    assert list(mod.FLASK_POTENCY_TEAR_COST) == list(pg.FLASK_POTENCY_TEAR_COST), (
        "tear cost ladder drifted from tools/upgrade_costs.py -- one datum, one source")


# =================================================================================================
# THE STRETCH -- pure, no world, because the schedule is pure
# =================================================================================================
def test_the_flask_has_exactly_twenty_two_upgrades():
    """🛑 THE CEILING THIS WHOLE LADDER IS SHAPED AROUND, stated independently of the code that uses
    it: ten charge steps (4 -> 14) and twelve tears (0 -> 12). A rung carries at most one, so a seed
    with more than twenty-two copies has copies that cannot be made to pay. That is the game's
    ceiling, not a scheduling bug -- and it is why `flask_schedule` spreads the surplus instead of
    trying to eliminate it."""
    assert pg.FLASK_CHARGE_STEPS == 10
    assert pg.FLASK_POTENCY_STEPS == 12
    assert pg.FLASK_UPGRADES == 22
    assert pg.FLASK_CHARGES_MAX - pg.FLASK_CHARGES_BASE == pg.FLASK_CHARGE_STEPS
    seq = pg.flask_event_seq()
    assert len(seq) == pg.FLASK_UPGRADES
    assert seq.count(pg.FLASK_CHARGE) == pg.FLASK_CHARGE_STEPS
    assert seq.count(pg.FLASK_TEAR) == pg.FLASK_POTENCY_STEPS


def test_the_sequence_still_alternates():
    """Ruling #798 survives the stretch: the ORDER is Charge, tear, Charge, tear. It can only run
    ten pairs deep because the axes are different lengths, and the two leftover tears finish it."""
    seq = pg.flask_event_seq()
    assert seq[0] == pg.FLASK_CHARGE, "a fresh character must see the flask change on copy 1"
    assert seq[:20] == [pg.FLASK_CHARGE, pg.FLASK_TEAR] * 10
    assert seq[20:] == [pg.FLASK_TEAR, pg.FLASK_TEAR]


@pytest.mark.parametrize("n", [1, 2, 6, 13, 14, 20, 21, 22])
def test_a_small_seed_spends_every_copy_and_did_not_move(n):
    """At or under the upgrade count there is nothing to spread, so the schedule is the first N of
    the sequence -- which is byte-identical to what the old ordinal schedule produced. Small seeds
    not moving is the reason this change is safe to make outside a data rewrite."""
    sched = pg.flask_schedule(n)
    assert sched == pg.flask_event_seq()[:n]
    assert all(e is not None for e in sched), "a copy that grants nothing, with upgrades left over"


@pytest.mark.parametrize("n", [23, 24, 26, 30, 40, 56, 200])
def test_a_large_seed_spreads_the_upgrades_across_the_whole_run(n):
    """THE POINT OF THE CHANGE. Every upgrade still lands, the first is on the first copy and the
    last on the last copy, and nothing is bunched at the front."""
    sched = pg.flask_schedule(n)
    assert len(sched) == n
    assert [e for e in sched if e is not None] == pg.flask_event_seq(), (
        "the stretch must reorder nothing and drop nothing")
    assert sched[0] is not None, "copy 1 must still pay -- a fresh character sees no flask change"
    assert sched[-1] is not None, "the ladder must finish on the run's last copy"
    # ...and the surplus is exactly the copies the flask has no upgrade for
    assert sum(1 for e in sched if e is None) == n - pg.FLASK_UPGRADES


@pytest.mark.parametrize("n", [23, 30, 56])
def test_the_old_flat_tail_is_gone(n):
    """The defect, stated as a test. The old schedule put its last upgrade on copy 24 whatever the
    seed held, so a 56-copy seed spent its final 32 copies granting nothing and its last 32 rungs
    identical. The stretched ladder's last upgrade sits in the final tenth of the run."""
    sched = pg.flask_schedule(n)
    last = max(i for i, e in enumerate(sched) if e is not None)
    assert last >= 0.9 * (n - 1), (
        "the last upgrade lands at copy %d of %d -- the ladder still flattens early" % (last, n))
    old_last_upgrade_copy = 24        # what the ordinal schedule did, for the contrast
    if n > old_last_upgrade_copy:
        assert last > old_last_upgrade_copy


@pytest.mark.parametrize("n", list(range(0, 60)) + [120, 200])
def test_the_schedule_never_breaks_the_one_tear_per_rung_rule(n):
    """Exhaustive over every seed size that can occur. Potency may advance at most one per rung --
    two tears at one stream index is the batching the consumed-goods ledger forbids -- and charges
    likewise, since a two-step charge rung is a wasted rung."""
    charges, potency = pg.FLASK_CHARGES_BASE, 0
    for i, event in enumerate(pg.flask_schedule(n), start=1):
        assert event in (pg.FLASK_CHARGE, pg.FLASK_TEAR, None), (n, i, event)
        if event == pg.FLASK_CHARGE:
            charges += 1
        elif event == pg.FLASK_TEAR:
            potency += 1
        assert charges <= pg.FLASK_CHARGES_MAX, (n, i, charges)
        assert potency <= pg.FLASK_POTENCY_MAX, (n, i, potency)
    if n >= pg.FLASK_UPGRADES:
        assert (charges, potency) == (pg.FLASK_CHARGES_MAX, pg.FLASK_POTENCY_MAX), n


def test_two_upgrades_can_never_share_a_copy():
    """The spread places upgrade j on copy floor(j*(n-1)/21). A collision would silently DROP an
    upgrade -- and if the dropped one were a tear, the surviving copy would owe two ledger entries at
    one stream index. `flask_schedule` raises rather than returning a short ladder; this pins that
    the arithmetic never gets there in the first place."""
    for n in range(pg.FLASK_UPGRADES, 400):
        slots = [(j * (n - 1)) // (pg.FLASK_UPGRADES - 1) for j in range(pg.FLASK_UPGRADES)]
        assert len(set(slots)) == pg.FLASK_UPGRADES, n
        assert slots == sorted(slots), n


def _assert_leveled_ladder_invariants(testcase, ladder):
    """A flaskLadder is a non-empty list of {charges 4..14, potency 0..12}, monotone non-decreasing,
    advancing at most one axis by at most one step per rung.

    The per-rung bound is not a style rule. Potency is granted as ONE consumed Sacred Tear per rung,
    so a +2 rung would need two ledger entries at one stream index -- the batching the consumed-goods
    ledger forbids. Charges could physically move further (they are a reconciled leveled state), but
    a rung that jumped two charge levels would be a rung the ladder wasted, which is the whole defect
    the stretch exists to remove.
    """
    testcase.assertIsInstance(ladder, list)
    testcase.assertGreater(len(ladder), 0)
    for r in ladder:
        testcase.assertIsInstance(r, dict)
        testcase.assertIn("charges", r)
        testcase.assertIn("potency", r)
        testcase.assertTrue(pg.FLASK_CHARGES_BASE <= r["charges"] <= pg.FLASK_CHARGES_MAX,
                            f"charges out of [{pg.FLASK_CHARGES_BASE},{pg.FLASK_CHARGES_MAX}]: {r}")
        testcase.assertTrue(0 <= r["potency"] <= pg.FLASK_POTENCY_MAX, f"potency out of [0,12]: {r}")
    prev = {"charges": pg.FLASK_CHARGES_BASE, "potency": 0}
    for i, r in enumerate(ladder, start=1):
        dc, dp = r["charges"] - prev["charges"], r["potency"] - prev["potency"]
        testcase.assertGreaterEqual(dc, 0, f"charges not monotonic at rung {i}")
        testcase.assertGreaterEqual(dp, 0, f"potency not monotonic at rung {i}")
        testcase.assertLessEqual(dp, 1, f"rung {i} advances potency by {dp} -- one tear per rung")
        testcase.assertLessEqual(dc, 1, f"rung {i} advances charges by {dc} -- one step per rung")
        testcase.assertFalse(dc and dp, f"rung {i} advanced BOTH axes: {prev} -> {r}")
        prev = r
    testcase.assertEqual(ladder[0]["charges"], pg.FLASK_CHARGES_BASE + 1,
                         "copy 1 must visibly advance the vanilla starting allocation of 4")

    n = len(ladder)
    if n >= pg.FLASK_UPGRADES:
        # 🛑 THE STRETCH, ASSERTED AS AN OUTCOME rather than by re-running the scheduler: a seed with
        # at least as many copies as the flask has upgrades must finish BOTH axes, and must finish
        # them on its LAST rung. The old ordinal schedule finished them on rung 19 and 24 no matter
        # how long the ladder was, which is exactly the flat tail this replaces.
        testcase.assertEqual(ladder[-1], {"charges": pg.FLASK_CHARGES_MAX,
                                          "potency": pg.FLASK_POTENCY_MAX},
                             "a seed with >= 22 copies must finish both flask axes")
        testcase.assertNotEqual(ladder[-1], ladder[-2] if n > 1 else None,
                                "the last rung must ADVANCE something -- a ladder whose final copy "
                                "grants nothing has not been stretched to the end of the run")
    else:
        # Under 22 copies there is nothing to spread: every rung carries an upgrade.
        advancing = sum(1 for a, b in zip([{"charges": pg.FLASK_CHARGES_BASE, "potency": 0}] + ladder,
                                          ladder)
                        if a != b)
        testcase.assertEqual(advancing, n,
                             "a seed under 22 copies must spend every copy -- %d of %d did nothing"
                             % (n - advancing, n))


def _assert_flask_potency_grants(testcase, rungs, ladder):
    """The flask's progressiveGrants ladder grants a consumed Sacred Tear (good 10020|nibble) on
    exactly the rungs where the flaskLadder's POTENCY advances, and an explicit no-op on every other.

    🛑 CROSS-CHECKED AGAINST THE LADDER, not against a copy ordinal. The flask is one item riding two
    wires; the failure that matters is the two wires DISAGREEING about which copy does what -- a
    potency step on the ladder with no tear behind it is a flask the player can never actually
    upgrade. Asserting each wire against the ordinal separately would let both drift together.

    consumed=True is required: shipping it OWNED re-granted spent tears unbounded and CTD'd
    (playtest 2026-07-12).
    """
    expected_goods = pg._GOOD_SACRED_TEAR | pg._GOODS_NIBBLE
    testcase.assertEqual(pg._GOOD_SACRED_TEAR, 10020, "Sacred Tear good id must be 10020")
    testcase.assertEqual(expected_goods, 1073751844, "Sacred Tear FullID must match item_ids.py")
    testcase.assertEqual(len(rungs), len(ladder),
                         "the two flask wires must have one entry per copy each")
    prev = 0
    tears = 0
    for copy, (r, rung) in enumerate(zip(rungs, ladder), start=1):
        advanced = rung["potency"] > prev
        prev = rung["potency"]
        if advanced:
            tears += 1
            testcase.assertEqual(r["goods"], expected_goods,
                                 "rung %d advances potency but grants no Sacred Tear" % copy)
            testcase.assertEqual(r["flags"], [], "flask potency rungs carry no flags")
            testcase.assertIs(r["consumed"], True, "flask tears MUST be consumed")
        else:
            testcase.assertEqual(r, {"noop": True},
                                 "rung %d does not advance potency and must be an explicit no-op "
                                 "so the copy keeps its stream index" % copy)
    testcase.assertEqual(tears, ladder[-1]["potency"],
                         "one tear per potency step, no more and no fewer")


# ---- the ladder on a FULL seed -----------------------------------------------------------------
class ProgressiveFlaskLadder(WorldTestBase):
    game = GAME
    options = {"progressive_flasks": True, "enable_dlc": True, "num_regions": 0}

    def _ladder(self):
        return pg.flask_ladder(self.world)

    def test_ladder_invariants(self):
        _assert_leveled_ladder_invariants(self, self._ladder())

    def test_ladder_length_matches_copy_count(self):
        """The wire length == the PROG_FLASK copies actually in the pool (so no rung is dead and no
        copy lacks a rung). On a full seed every kept Golden Seed / Sacred Tear substitutes to a copy."""
        ladder = self._ladder()
        copies = world_item_names(self).count(pg.PROG_FLASK)
        self.assertEqual(len(ladder), copies,
                         f"ladder rungs ({len(ladder)}) != PROG_FLASK copies ({copies})")
        self.assertEqual(len(ladder), pg.flask_copy_count(self.world))

    def test_ladder_is_deterministic_per_seed(self):
        """create_items and fill_slot_data must never disagree about the ladder (it is cached)."""
        self.assertEqual(self._ladder(), self._ladder(), "flask_ladder must be cached, not re-rolled")

    def test_vanilla_seeds_and_tears_replaced_one_for_one(self):
        names = world_item_names(self)
        for vanilla in pg.VANILLA_FLASK_ITEMS:
            self.assertEqual(names.count(vanilla), 0,
                             f"{vanilla} still in the pool alongside {pg.PROG_FLASK}")
        self.assertGreater(names.count(pg.PROG_FLASK), 0, "no progressive flask copies in the pool")

    def test_slot_data_emits_flask_ladder_and_potency_tears(self):
        """The flask rides BOTH wires: CHARGES on flaskLadder (leveled state) and POTENCY on
        progressiveGrants (tears on even copies). The split is the whole point -- charges are a
        reconciled state (no spend to heal), potency is granted/ledgered tears the player upgrades at a
        grace (which updates every flask mirror safely)."""
        sd = self.world.fill_slot_data()
        self.assertIn(contract.FLASK_LADDER, sd, "flaskLadder must be emitted when flasks are on")
        self.assertEqual(sd[contract.FLASK_LADDER], self._ladder(),
                         "emitted flaskLadder disagrees with the ladder create_items used")
        grants = sd[contract.PROGRESSIVE_GRANTS]
        self.assertIn(pg.PROG_FLASK, grants,
                      "PROG_FLASK MUST be in progressiveGrants now (its POTENCY axis grants tears)")
        _assert_flask_potency_grants(self, grants[pg.PROG_FLASK], self._ladder())
        # both wires pass their contract shape checkers
        self.assertIsNone(contract._chk_flask_ladder(sd[contract.FLASK_LADDER]))
        self.assertIsNone(contract._chk_nested_grants({pg.PROG_FLASK: grants[pg.PROG_FLASK]}))


# ---- the ladder under dlc_only (the fixed floor) -----------------------------------------------
class ProgressiveFlaskLadderDLCOnly(WorldTestBase):
    """dlc_only seals every base region, so no kept REGION holds a seed/tear check (only the HUB's
    lone Golden Seed substitutes). The feature tops the pool up to FLASK_UPGRADES copies and builds a
    ladder of that length -- one copy per upgrade the flask actually has, so both axes max exactly on
    the last rung and not one injected copy is wasted."""
    game = GAME
    options = {"num_regions": 0, "dlc_only": True, "progressive_flasks": True}

    def test_dlc_only_injects_a_ladder_with_no_wasted_copy(self):
        w = self.world
        self.assertEqual(pg._region_flask_copies(w), 0,
                         "dlc_only should keep no REGION flask check (only the HUB's Golden Seed)")
        # 🛑 THE FLOOR IS THE UPGRADE COUNT, and it is not a coincidence that has to be maintained by
        # hand: injecting more than 22 copies would inject copies that grant nothing, and fewer would
        # leave an axis short. It was 24 under the old schedule, which needed two spare copies to
        # reach potency 12 and then wasted them.
        self.assertEqual(pg.DLC_ONLY_FLASK_COPIES, pg.FLASK_UPGRADES)
        ladder = pg.flask_ladder(w)
        self.assertEqual(len(ladder), pg.DLC_ONLY_FLASK_COPIES,
                         "dlc_only ladder must be exactly the fixed floor length")
        _assert_leveled_ladder_invariants(self, ladder)
        self.assertEqual(ladder[-1], {"charges": pg.FLASK_CHARGES_MAX,
                                      "potency": pg.FLASK_POTENCY_MAX})
        self.assertTrue(all(e is not None for e in pg.flask_schedule(len(ladder))),
                        "the injected floor must not contain a copy that grants nothing")

    def test_dlc_only_potency_grants_twelve_tears(self):
        """The dlc_only seed grants exactly 12 consumed Sacred Tears so potency reaches its cap the
        ledgered/consumed way."""
        grants = self.world.fill_slot_data()[contract.PROGRESSIVE_GRANTS]
        self.assertIn(pg.PROG_FLASK, grants)
        ladder = pg.flask_ladder(self.world)
        _assert_flask_potency_grants(self, grants[pg.PROG_FLASK], ladder)
        self.assertEqual(sum(1 for r in grants[pg.PROG_FLASK] if r != {"noop": True}),
                         pg.FLASK_POTENCY_MAX)

    def test_pool_holds_exactly_ladder_length_copies(self):
        """Count-consistency: ladder length == PROG_FLASK copies actually in the pool (HUB substitution
        + injected top-up)."""
        w = self.world
        copies = world_item_names(self).count(pg.PROG_FLASK)
        self.assertEqual(copies, pg.DLC_ONLY_FLASK_COPIES)
        self.assertEqual(copies, len(pg.flask_ladder(w)))

    def test_maxes_by_the_last_rung_only(self):
        """The last rung is the max, and it is load-bearing (an earlier rung is below it) -- so the
        short ladder actually climbs rather than jumping to max and idling."""
        ladder = pg.flask_ladder(self.world)
        self.assertEqual(ladder[-1], {"charges": pg.FLASK_CHARGES_MAX, "potency": pg.FLASK_POTENCY_MAX})
        self.assertNotEqual(ladder[-2], ladder[-1], "the last rung buys nothing -- ladder idles at max")


# ---- the toggle's OFF half ---------------------------------------------------------------------
class ProgressiveFlasksOff(WorldTestBase):
    game = GAME
    options = {"progressive_flasks": False, "enable_dlc": True, "num_regions": 0}

    def test_vanilla_seeds_and_tears_stay_discrete(self):
        names = world_item_names(self)
        self.assertEqual(names.count(pg.PROG_FLASK), 0,
                         "progressive copies in the pool with the toggle OFF")
        for vanilla in pg.VANILLA_FLASK_ITEMS:
            self.assertGreater(names.count(vanilla), 0,
                               f"{vanilla} missing from the pool with progressive_flasks off")

    def test_slot_data_emits_no_flask_ladder(self):
        sd = self.world.fill_slot_data()
        self.assertNotIn(contract.FLASK_LADDER, sd,
                         "no flaskLadder may be emitted when the toggle is off")
        self.assertNotIn(pg.PROG_FLASK, sd[contract.PROGRESSIVE_GRANTS])


def test_option_is_a_real_toggle_default_on():
    """progressive_flasks is a REAL yaml toggle (un-frozen 2026-07-15), default ON: the unified ladder
    is the intended v0.2 flask economy. Flipping either silently reverts it."""
    from worlds.eldenring import defaults
    from worlds.eldenring.features.progressive import ProgressiveFlasks
    assert "progressive_flasks" not in defaults.FROZEN_OPTIONS, (
        "progressive_flasks went back into FROZEN_OPTIONS -- it is supposed to be a real yaml toggle")
    assert ProgressiveFlasks.default == 1, (
        "progressive_flasks must default ON: the unified ladder is the intended v0.2 flask economy")


# ---- the CTD, as a contract invariant (consumed vs owned) ---------------------------------------
def test_flask_potency_grants_consumed_tears_bells_are_flags_only():
    """The flask's POTENCY axis rides progressiveGrants as 12 CONSUMED Sacred Tears (spent at a grace;
    shipping them OWNED re-granted spent tears unbounded and CTD'd, playtest 2026-07-12). Bell rungs
    ride the same wire as flags only: the stock flags already represent a handed-in bearing, so a
    physical good is rejected as over-capacity (#804)."""
    from worlds.eldenring.features import progressive as pgg

    class _W:
        class options:
            class progressive_flasks: value = 1
            class progressive_stone_bells: value = 1
            class progressive_stonesword_keys: value = 0
        import random as _r
        random = _r.Random(1)
        player = 1

    feat = pgg.Progressive()
    active = feat._active_items(_W)
    assert pgg.PROG_FLASK in active, "flasks are on, so PROG_FLASK is an active pool item"

    flask = feat._grant_ladder(_W, pgg.PROG_FLASK)
    assert len(flask) == pgg.DLC_ONLY_FLASK_COPIES == pgg.FLASK_UPGRADES
    for rung, event in zip(flask, pgg.flask_schedule(len(flask))):
        if event == pgg.FLASK_TEAR:
            assert rung == {"goods": pgg._GOOD_SACRED_TEAR | pgg._GOODS_NIBBLE,
                            "flags": [], "consumed": True}
        else:
            assert rung == {"noop": True}

    bell = feat._grant_ladder(_W, pgg.PROG_SMITHING_BELL)
    assert bell, "bell ladder is empty"
    assert all(set(r) == {"flags"} and r["flags"] for r in bell), (
        "bell rungs must carry only their non-empty stock flags, never a physical bearing")


def test_contract_rejects_a_rung_that_forgets_to_declare():
    """The progressiveGrants validator must still REFUSE a rung with no `consumed` (the field whose
    absence CTD'd a live playtest), so a bell/key rung can never again ship by omission."""
    bad = {"Progressive Smithing-Stone Miner's Bell Bearing": [{"goods": 1073751844, "flags": []}]}
    err = contract._chk_nested_grants(bad)
    assert err and "consumed" in err, f"validator accepted a rung with no `consumed`: {err!r}"


def test_contract_accepts_flags_only_bell_rung_but_not_an_empty_rung():
    assert contract._chk_nested_grants({"Bell": [{"flags": [280080]}]}) is None
    assert contract._chk_nested_grants({"Bell": [{"flags": []}]}) is not None

    good = {"Progressive Smithing-Stone Miner's Bell Bearing":
            [{"goods": 1073751844, "flags": [280080], "consumed": False}]}
    assert contract._chk_nested_grants(good) is None


def test_bell_rungs_set_stock_and_release_gates():
    """A stock flag alone does not put a release-gated row on the Twin Maiden shelf."""
    from worlds.eldenring.features import progressive as pgg

    expected = {
        pgg.PROG_SMITHING_BELL: [
            [280080, 280090, 11109751],
            [280110, 280120, 11109752],
            [280140, 280150, 11109753],
            [280160, 280170, 11109754],
        ],
        pgg.PROG_SOMBER_BELL: [
            [280180, 280190, 11109755],
            [280200, 280210, 11109756],
            [280230, 280240, 11109757],
            [280250, 280260, 11109758],
            [280280, 11109759],
        ],
    }
    assert {name: [rung["flags"] for rung in rungs]
            for name, rungs in pgg._BELL_GRANTS.items()} == expected
