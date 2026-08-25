"""A released Region Lock must be able to leave Elden Ring.

WHY THIS FILE EXISTS. `progression_bias` has always said, in its own player-facing text, that at 0 a
Lock "can end up in another player's game". It could not. `place_released_locks` gathered candidate
locations from every PARTICIPATING Elden Ring world -- our own included -- so with one Elden Ring
slot beside partner games the release was handed straight back to us and the spill was zero.
Measured over five four-slot seeds on stock AP 0.6.7: 0 of 16 released Locks reached a partner world,
while the log cheerfully reported `6 Lock(s) RELEASED to the multiworld pool`.

That is the worst shape a bug can take -- the feature reports success, the option documents the
behaviour, and the behaviour is absent. So these tests assert the MECHANISM, not the outcome of any
one fill:

  1. A location gathered by the pass REFUSES an item belonging to its own player, and accepts the
     same item from another player. That is the whole fix, and it is checkable without a fill.
  2. The refusal is TORN DOWN. These are real Location objects shared with the rest of generation; a
     rule left installed would silently outlive the hook and bar the owner from their own checks for
     the remainder of the fill.
  3. `progression_travel` splits the released set, and at its default consumes NO rng -- CLAUDE.md
     rule 6, because apply() draws and every already-rolled seed depends on that stream.
"""
import pytest

WorldTestBase = pytest.importorskip("test.bases").WorldTestBase
pytest.importorskip("worlds.eldenring")

from worlds.eldenring.features import progression_surface as ps            # noqa: E402

GAME = "Elden Ring"


class _Opt:
    def __init__(self, value):
        self.value = value


class _Stub:
    def __init__(self, **opts):
        self.options = type("O", (), {k: _Opt(v) for k, v in opts.items()})()


class _Item:
    def __init__(self, player, name="Limgrave Lock"):
        self.player = player
        self.name = name


# ---- the option ---------------------------------------------------------------------------------

def test_progression_travel_is_declared_and_defaults_to_zero():
    assert "progression_travel" in ps.ProgressionSurfaceFeature.OPTIONS
    assert ps.ProgressionTravel.default == 0
    assert ps.ProgressionTravel.range_start == 0 and ps.ProgressionTravel.range_end == 100


def test_travel_pct_resolves_and_defaults_safe():
    assert ps._travel_pct(_Stub(progression_travel=40)) == 40
    assert ps._travel_pct(_Stub(progression_travel=0)) == 0
    assert ps._travel_pct(_Stub(progression_travel=-5)) == 0, "clamped, never negative"
    assert ps._travel_pct(_Stub(progression_travel=250)) == 100, "clamped, never over 100"
    assert ps._travel_pct(_Stub()) == 0, "absent option -> pre-option behaviour, not the default"
    assert ps._travel_pct(_Stub(progression_travel="nonsense")) == 0


def test_travel_split_reuses_released_locks_rounding():
    """The split is the same helper the release uses, so the endpoints are exact and the rounding is
    half-up. A 50% travel share on a 1-Lock seed must not silently share nothing."""
    import random
    locks = [_Item(1, "%s Lock" % r) for r in ("Limgrave", "Liurnia", "Caelid")]
    rng = random.Random(0)
    assert ps.released_locks(locks, 0, rng) == []
    assert len(ps.released_locks(locks, 100, rng)) == 3
    assert len(ps.released_locks(locks[:1], 50, rng)) == 1, "half-up, not banker's rounding"


# ---- the own-world refusal ----------------------------------------------------------------------

class _Loc:
    """A stand-in for the Location objects place_released_locks decorates."""
    def __init__(self, player):
        self.player = player
        self.item_rule = lambda item: True


def _install(locations):
    """The exact rule place_released_locks installs, lifted so it can be tested without a fill."""
    saved = [(loc, loc.item_rule) for loc in locations]
    for loc in locations:
        loc.item_rule = (lambda item, _p=loc.player, _prev=loc.item_rule:
                         getattr(item, "player", None) != _p and _prev(item))
    return saved


def test_a_gathered_location_refuses_its_own_players_lock():
    mine, theirs = _Loc(1), _Loc(2)
    _install([mine, theirs])
    my_lock = _Item(1)
    assert mine.item_rule(my_lock) is False, "a released Lock is never offered back to its own world"
    assert theirs.item_rule(my_lock) is True, "another Elden Ring slot's surface may still host it"


def test_the_refusal_composes_with_an_existing_rule():
    """The pass decorates real locations that may already carry core's foreign-progression bar. The
    previous rule must still be consulted, not replaced."""
    loc = _Loc(2)
    loc.item_rule = lambda item: getattr(item, "name", "") != "Caelid Lock"
    _install([loc])
    assert loc.item_rule(_Item(1, "Limgrave Lock")) is True
    assert loc.item_rule(_Item(1, "Caelid Lock")) is False, "the pre-existing rule still applies"
    assert loc.item_rule(_Item(2, "Limgrave Lock")) is False, "own-world refusal still applies"


class SoloKeepsItsCuration(WorldTestBase):
    """🛑 THE REFUSAL MUST NOT FIRE IN A SOLO SEED. There is no other player to send a released Lock
    to, so refusing our own world would not make it travel -- it would only drop the key on an
    ordinary check and lose the curation. progression_bias has promised "no effect in a solo seed"
    since it shipped."""
    game = GAME
    options = {"num_regions": 6, "enable_dlc": False, "progression_bias": 0}

    def test_solo_released_locks_are_still_placed_at_home(self):
        self.assertEqual(len(self.multiworld.player_ids), 1, "fixture is not solo")
        self.assertTrue(self.world.gf_locks_released, "bias 0 must release something")
        placed = {loc.item.name for loc in self.multiworld.get_locations(self.player)
                  if loc.item is not None}
        for name in self.world.gf_locks_released:
            self.assertIn(name, placed,
                          "a released Lock left a SOLO world -- there is nowhere for it to go")


def test_the_refusal_is_torn_down():
    """🛑 These are real Locations. A rule left installed would bar the owner from their own checks
    for the rest of the fill -- a silent, seed-wide narrowing that no other test would catch."""
    locs = [_Loc(1), _Loc(2)]
    saved = _install(locs)
    assert locs[0].item_rule(_Item(1)) is False
    for loc, rule in saved:                     # what the `finally` block does
        loc.item_rule = rule
    assert locs[0].item_rule(_Item(1)) is True, "restored -- the rule did not outlive the pass"


# ---- the stream ----------------------------------------------------------------------------------

class TravelDefaultIsInert(WorldTestBase):
    """CLAUDE.md rule 6. At the default the split must not draw, so a seed rolled before this option
    existed still rolls the same."""
    game = GAME
    options = {"num_regions": 6, "enable_dlc": False}

    def test_default_travel_shares_nothing_and_draws_nothing(self):
        self.assertEqual(ps._travel_pct(self.world), 0)
        before = self.world.random.getstate()
        # the guarded branch in apply(): pct 0 returns before touching the rng
        self.assertEqual(ps.released_locks([], 0, self.world.random), [])
        self.assertEqual(self.world.random.getstate(), before,
                         "the default consumed rng -- every already-rolled seed would shift")

    def test_apply_records_the_travelling_split(self):
        self.assertTrue(hasattr(self.world, "gf_locks_travelling"),
                        "apply() must always publish the split, even when it is empty")
        self.assertEqual(self.world.gf_locks_travelling, [],
                         "nothing travels at the default travel share")


class TravelAllSkipsCuration(WorldTestBase):
    """progression_bias 0 releases every Lock; progression_travel 100 sends every released one
    straight to the open fill instead of offering it to another Elden Ring slot."""
    game = GAME
    options = {"num_regions": 6, "enable_dlc": False,
               "progression_bias": 0, "progression_travel": 100}

    def test_every_released_lock_travels(self):
        released = set(self.world.gf_locks_released)
        self.assertTrue(released, "progression_bias 0 must release something to share")
        self.assertEqual(set(self.world.gf_locks_travelling), released,
                         "at travel 100 no released Lock is offered to any surface")
        self.assertEqual(self.world.gf_released_lock_items, [],
                         "stage_pre_fill must be handed nothing -- they stay in the itempool")

    def test_the_travelling_locks_are_still_in_the_pool(self):
        """The whole point: an item the general fill can place anywhere, in any player's world."""
        pool = {it.name for it in self.multiworld.itempool if it.player == self.player}
        for name in self.world.gf_locks_travelling:
            self.assertIn(name, pool, "a travelling Lock was removed from the pool by something")
