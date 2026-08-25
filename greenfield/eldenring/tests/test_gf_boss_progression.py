"""boss_progression -- "the bosses hold the keys", as one option instead of two.

WHAT THE OPTION IS. `progression_surface` already confines this world's own progression to a set of
location CLASSES, enforced as a real fill_restrictive placement with a feasibility ladder and a spill
valve. `Boss` was always in that vocabulary; it was never in the shipped default, and getting the
multiworld half also required knowing that `confine_foreign_progression` is what routes ANOTHER
game's keys onto the same set. boss_progression is that configuration made into one named lever.

WHAT THESE TESTS GUARD, in the order the failures would actually hurt:

  1. THE MULTIWORLD HALF. The ask this feature was built for is "a partner game's progression may
     also sit on an Elden Ring boss". That is enforced by an item_rule core installs on every
     NON-surface check (core._add_locations), and it is only installed when confined_surface_ids()
     returns a set -- which it does not when the enforcement mode reads 0. So the interesting
     assertion is not "our locks are on bosses", it is "a non-boss check REFUSES a foreign
     advancement item and still accepts foreign filler".

  2. THE RNG STREAM. CLAUDE.md rule 6: draw order in create_items / compute_kept is load-bearing and
     reordering a sample changes every already-rolled seed. boss_progression adds branches inside
     apply(), which draws. With the option OFF the module must consume the stream exactly as it did
     before it existed -- otherwise shipping this option silently rerolls every seed in the wild.

  3. THE LADDER STILL WIDENS. apply() is documented "never FillErrors" and the terminal action is
     return-to-pool. A boss ladder that forgot its off-boss tail would turn a small-num_regions seed
     from "degrades and says so" into a hard failure.

  4. THE DEGRADE IS VISIBLE. A mode whose promise quietly stops holding is worse than one that
     refuses. boss_placement_census measures where the items LANDED, not which rung was running.
"""
import pytest

WorldTestBase = pytest.importorskip("test.bases").WorldTestBase
pytest.importorskip("worlds.eldenring")

from Options import OptionError                                            # noqa: E402

from worlds.eldenring import contract                                      # noqa: E402
from worlds.eldenring.features import progression_surface as ps            # noqa: E402
from worlds.eldenring.location_tags import LOCATION_TAGS                   # noqa: E402

GAME = "Elden Ring"
BOSS_TAGS = {"Boss", "MajorBoss", "LegacyBoss", "FieldBoss", "MinorDungeonBoss",
             "Remembrance", "GreatRune"}


def _is_boss(ap_id):
    return bool(BOSS_TAGS & set(LOCATION_TAGS.get(ap_id, ())))


class _Opt:
    def __init__(self, value):
        self.value = value


class _Stub:
    """Enough of a world for the pure resolvers. Deliberately NOT a real world: _boss_mode and _mode
    are called on stubs during the pure suite and must not require an option to exist."""
    def __init__(self, **opts):
        self.options = type("O", (), {k: _Opt(v) for k, v in opts.items()})()


# ---- 0. the option exists and is reachable from yaml ---------------------------------------------
def test_boss_progression_is_a_yaml_option():
    import dataclasses
    from worlds.eldenring import core
    names = {f.name for f in dataclasses.fields(core.GFOptions)}
    assert "boss_progression" in names, (
        "boss_progression must be yaml-settable; if it ended up in defaults.FROZEN_OPTIONS the "
        "feature is unreachable and every test below is testing a knob nobody can turn")


def test_default_is_off_so_existing_seeds_do_not_move():
    assert ps.BossProgression.default == ps.BossProgression.option_off == 0


def test_every_boss_mode_class_is_in_the_shared_vocabulary():
    """A class outside contract.SURFACE_CLASSES is silently dropped by selected_surface, so a typo
    here would not raise -- it would just quietly shrink the surface."""
    for mode, classes in ps._BOSS_MODE_CLASSES.items():
        assert classes, mode
        for c in classes:
            assert c in contract.SURFACE_CLASSES, (mode, c)


def test_boss_mode_classes_really_are_boss_classes():
    """Guards the thing the option's NAME promises. Derived from the live tags, not from the table:
    a class that stopped being a boss class would otherwise keep passing on its name alone."""
    for mode, classes in ps._BOSS_MODE_CLASSES.items():
        tagged = {ap for ap, tags in LOCATION_TAGS.items() if set(classes) & set(tags)}
        assert tagged, mode
        assert all(_is_boss(ap) for ap in tagged), mode


# ---- 1. resolution: one selection, read by placement AND slot_data --------------------------------
def test_selection_returns_the_boss_classes_in_boss_mode():
    assert ps._selection(_Stub(boss_progression=1)) == ps._BOSS_MODE_CLASSES[1]
    assert ps._selection(_Stub(boss_progression=2)) == ps._BOSS_MODE_CLASSES[2]


def test_selection_falls_through_to_the_players_surface_when_off():
    w = _Stub(boss_progression=0, progression_surface={"Church"})
    assert ps._selection(w) == {"Church"}


def test_boss_mode_replaces_rather_than_intersects():
    """progression_surface ships a nine-class default, so an INTERSECTION with {Boss} would be
    {MajorBoss} for everyone who never touched it -- a third surface belonging to neither option."""
    w = _Stub(boss_progression=1, progression_surface=set(contract.SURFACE_DEFAULT_CLASSES))
    assert ps._selection(w) == ("Boss",)


def test_an_unrecognised_rung_reads_as_off_rather_than_raising():
    """_boss_mode runs on every world including stubs; an unknown value must degrade, not crash."""
    assert ps._boss_mode(_Stub(boss_progression=99)) == 0
    assert ps._boss_mode(_Stub()) == 0


def test_the_surface_regime_no_longer_needs_forcing():
    """🛑 THIS TEST USED TO FORCE `_mode` TO STRICT, and the forcing is what mattered: at mode 0
    `confined_surface_ids()` returned None, core installed NO foreign-advancement bar, and the seed
    read as boss-gated while quietly not being.

    `progression_surface_mode` was RETIRED upstream on 2026-08-14 (see `ProgressionSurfaceMode`,
    now `Removed`) -- strict is the only regime and the off-branches were deleted, so there is no
    longer a mode to force. What survives is the assertion the forcing existed to BUY: whatever boss
    mode selects has to resolve to a real, non-empty surface, because that set is what
    `confined_surface_ids` hands core as the foreign-progression bar. An empty one installs no bar
    and the seed reads as boss-gated while quietly not being."""
    assert not hasattr(ps, "_mode"), (
        "_mode is back -- boss_progression must force it to strict again, or the foreign "
        "progression bar silently does not get installed")
    # WITNESS, and the substantive half: every rung resolves through the shared vocabulary to
    # classes that admit real checks. Without this the assertion above passes on a module where
    # boss mode selects nothing at all.
    for mode in ps._BOSS_MODE_CLASSES:
        resolved = ps.selected_surface(ps._BOSS_MODE_CLASSES[mode])
        assert resolved, "boss rung %d resolved to an EMPTY surface" % mode
        admitted = ps.allowed_ap_ids(LOCATION_TAGS, set(resolved))
        assert len(admitted) > 20, (
            "boss rung %d admits only %d check(s) -- it cannot be the foreign bar"
            % (mode, len(admitted)))


# ---- 2. the ladder ------------------------------------------------------------------------------
def test_boss_ladder_starts_at_the_boss_set():
    for mode, classes in ps._BOSS_MODE_CLASSES.items():
        rungs = ps.build_ladder(classes, mode)
        assert rungs, mode
        assert set(rungs[0]) == set(classes), mode


def test_boss_ladder_only_ever_widens():
    """Every rung must be a superset of the one before it. A ladder that NARROWED would make a later
    rung unable to host what an earlier one could, which is not a feasibility ladder at all."""
    for mode, classes in ps._BOSS_MODE_CLASSES.items():
        rungs = ps.build_ladder(classes, mode)
        for a, b in zip(rungs, rungs[1:]):
            assert set(a) < set(b), (mode, a, b)


def test_boss_ladder_keeps_an_off_boss_tail():
    """apply() is documented "never FillErrors" and its terminal action is return-to-pool. Dropping
    the off-boss rungs would turn a starved surface into a hard generation failure."""
    for mode, classes in ps._BOSS_MODE_CLASSES.items():
        final = set(ps.build_ladder(classes, mode)[-1])
        assert final - ps._BOSS_CLASSES, (
            "the last rung must reach beyond the boss classes, or a seed too small to host every "
            "lock on a boss has nowhere left to widen to")


def test_major_bosses_widens_boss_ward_before_leaving_the_bosses():
    """major_bosses is deliberately not closed over FieldBoss/Boss, so its first widen should reach
    the rest of the healthbars -- giving up on bosses is the LAST resort, not the first."""
    rungs = ps.build_ladder(ps._BOSS_MODE_CLASSES[2], 2)
    assert set(rungs[1]) <= ps._BOSS_CLASSES, rungs[1]


def test_an_unknown_boss_mode_falls_back_to_todays_ladder():
    assert ps.build_ladder({"MajorBoss"}, 0) == ps.build_ladder({"MajorBoss"})


# ---- 3. rejection rather than a silent no-op -----------------------------------------------------
class TestVanillaPlacementIsRejected:
    def _generate(self, **options):
        from test.general import setup_multiworld
        from worlds.eldenring.core import GreenfieldEldenRingWorld
        return setup_multiworld(GreenfieldEldenRingWorld, ("generate_early",), options=options)

    def test_vanilla_placement_plus_boss_progression_raises(self):
        """vanilla_placement pins every location and mints no Locks, so there is no progression left
        to place on a boss. The message must name BOTH options -- "it did nothing" is a bug report."""
        with pytest.raises(OptionError) as excinfo:
            self._generate(num_regions=0, vanilla_placement="all", boss_progression="bosses")
        msg = str(excinfo.value)
        assert "boss_progression" in msg and "vanilla_placement" in msg, msg


# ---- 4. the RNG stream, with the option off ------------------------------------------------------
class BossProgressionOffIsInert(WorldTestBase):
    """🛑 CLAUDE.md rule 6. Shipping this option must not reroll a single seed already in the wild."""
    game = GAME
    options = {"num_regions": 6, "item_shuffle": True}

    def test_off_resolves_exactly_as_before(self):
        assert ps._boss_mode(self.world) == 0
        surf = set(self.world.options.progression_surface.value)
        assert set(ps._selection(self.world)) == surf

    def test_off_reports_no_boss_census(self):
        assert getattr(self.world, "gf_boss_progression", 0) == 0
        assert ps.boss_placement_census(self.world, 0) == (0, 0)


# ---- 5. a real seed: our own progression lands on bosses -----------------------------------------
class BossProgressionSoloSeed(WorldTestBase):
    # progression_bias 100 keeps every Lock on OUR surface. At the shipped default of 0 they are all
    # RELEASED to the multiworld pool and placed by stage_pre_fill instead -- still onto a boss, but
    # through a second code path with its own spill valve, which is a different assertion. That path
    # gets its own coverage below; this class is about apply().
    game = GAME
    options = {"num_regions": 6, "item_shuffle": True, "boss_progression": "bosses",
               "progression_bias": 100}

    def test_the_surface_resolved_to_the_bosses(self):
        assert ps._boss_mode(self.world) == 1
        assert set(ps._selection(self.world)) == {"Boss"}

    def test_every_placed_own_progression_item_is_on_a_boss(self):
        """The mode's whole promise. Anything the ladder could not fit is reported as SPILLED and is
        allowed to be off-boss -- winnability is guarded independently -- so this asserts the census
        agrees with where the items actually are."""
        on_boss, off_boss = ps.boss_placement_census(self.world, 1)
        assert on_boss > 0, "a 6-region seed mints several locks; none of them reached a boss"
        assert off_boss == 0, (
            "%d own progression item(s) were placed off the boss surface on a seed with room to "
            "spare; the ladder widened when it should not have" % off_boss)

    def test_the_census_matches_the_locations(self):
        placed = [loc for loc in self.multiworld.get_locations(self.world.player)
                  if loc.item is not None
                  and ps.is_restricted_progression(loc.item, self.world.player)]
        assert placed, "no own progression was placed at all -- the census below would be vacuous"
        for loc in placed:
            assert _is_boss(loc.address), (
                "%s is on %s, which carries tags %s -- not a boss"
                % (loc.item.name, loc.name, LOCATION_TAGS.get(loc.address)))

    def test_the_client_stars_the_bosses(self):
        """slot_data reads the SAME resolution as the placement (_selection). If they ever diverge
        the tracker points at checks progression cannot be on, which teaches the player something
        false -- the bug bigTicketLocations was."""
        starred = self.world.fill_slot_data()[contract.PROGRESSION_SURFACE_LOCATIONS]
        assert starred
        for ap in starred:
            assert _is_boss(ap), ap


# ---- 6. THE MULTIWORLD HALF: other games' progression on our bosses -------------------------------
class ForeignProgressionIsHeldToOurBosses(WorldTestBase):
    """The requirement this feature was actually asked for.

    core._add_locations installs `not foreign_barred(item, player)` on every NON-surface check, so a
    partner game's advancement item can land on our bosses and nowhere else in our world. This is a
    BAR, not a magnet: it fixes WHERE foreign progression lands here, not how much arrives.
    """
    game = GAME
    options = {"num_regions": 6, "item_shuffle": True, "boss_progression": "bosses",
               "confine_foreign_progression": 100}

    def _foreign(self, advancement):
        """An item-like belonging to another player. A stand-in is enough and does not need a second
        real world -- but it must carry `.classification` as well as `.advancement`, because the
        rules it meets are COMPOSED: features/missable_locations chains its own rule onto the same
        location and masks on `item.classification`. A stand-in that satisfies only the predicate
        under test raises AttributeError inside a neighbouring one."""
        from BaseClasses import ItemClassification
        return type("I", (), {
            "player": self.world.player + 1,
            "advancement": advancement,
            "classification": (ItemClassification.progression if advancement
                               else ItemClassification.filler),
            "name": "Foreign Thing"})()

    def test_the_foreign_bar_is_installed_at_all(self):
        """If confined_surface_ids() returns None, core installs nothing and every assertion below
        would pass vacuously against an unconstrained world."""
        ids = ps.confined_surface_ids(self.world)
        assert ids, ("no foreign-confinement surface was resolved; core would install no bar and "
                     "foreign progression would scatter over every check we own")
        for ap in ids:
            assert _is_boss(ap), ap

    def test_a_non_boss_check_refuses_foreign_progression(self):
        non_boss = [loc for loc in self.multiworld.get_locations(self.world.player)
                    if loc.address is not None and not _is_boss(loc.address)]
        assert non_boss, "this seed emitted no non-boss checks; the assertion would be vacuous"
        for loc in non_boss[:200]:
            assert not loc.item_rule(self._foreign(True)), (
                "%s accepted another player's progression item; it is not a boss check" % loc.name)

    def test_a_non_boss_check_still_accepts_foreign_filler(self):
        """The bar must refuse ADVANCEMENT only. Refusing everything foreign would make us a dead
        end for the whole multiworld's filler, which is a different (and much worse) option."""
        non_boss = [loc for loc in self.multiworld.get_locations(self.world.player)
                    if loc.address is not None and not _is_boss(loc.address)]
        accepted = [loc for loc in non_boss[:200] if loc.item_rule(self._foreign(False))]
        assert accepted, "every non-boss check refused foreign filler too -- the bar is too wide"

    def test_a_boss_check_accepts_foreign_progression(self):
        """The other direction, and the one that makes an Elden Ring boss worth killing for someone
        else's sake. A surface that barred foreign progression everywhere would pass the test above
        and still be useless."""
        ids = ps.confined_surface_ids(self.world)
        boss_locs = [loc for loc in self.multiworld.get_locations(self.world.player)
                     if loc.address in ids]
        assert boss_locs
        assert any(loc.item_rule(self._foreign(True)) for loc in boss_locs), (
            "no boss check would accept another player's progression item, so this world can never "
            "host a partner's key -- the feature's headline claim")


class ForeignProgressionUnconfined(WorldTestBase):
    """confine_foreign_progression: 0 with boss mode on. Our OWN locks stay on bosses; other players'
    progression is explicitly NOT held to them. The two directions are independent knobs and this is
    what stops them being quietly welded together."""
    game = GAME
    options = {"num_regions": 6, "item_shuffle": True, "boss_progression": "bosses",
               "confine_foreign_progression": 0, "progression_bias": 100}

    def test_our_own_progression_is_still_boss_only(self):
        on_boss, off_boss = ps.boss_placement_census(self.world, 1)
        assert on_boss > 0 and off_boss == 0

    def test_foreign_progression_is_not_confined(self):
        assert ps.confined_surface_ids(self.world) is None


class BossProgressionWithReleasedLocks(WorldTestBase):
    """The SHIPPED default path: progression_bias 0 releases every Lock to the multiworld pool, and
    features/progression_surface.place_released_locks (stage_pre_fill) puts them onto an Elden Ring
    surface instead. In boss mode that surface is the bosses, so the promise must hold through this
    route too -- it is the one a player who never touches progression_bias will actually get."""
    game = GAME
    options = {"num_regions": 6, "item_shuffle": True, "boss_progression": "bosses"}

    def test_locks_were_released_rather_than_placed_by_apply(self):
        assert getattr(self.world, "gf_locks_released", []), (
            "progression_bias defaults to 0, so every Lock should have been released; if this is "
            "empty the test below is exercising apply() again and not the released path")

    def test_released_locks_still_landed_on_bosses(self):
        on_boss, off_boss = ps.boss_placement_census(self.world, 1)
        assert on_boss > 0
        assert off_boss == 0, (
            "%d own progression item(s) ended up off the boss surface via the released-lock path "
            "on a seed with room to spare" % off_boss)
