"""graded_progression -- one lever that paces PLAYER POWER against multiworld depth.

THE ASK (Alaric, off the 2026-08-27 six-region multiworld)
---------------------------------------------------------
*"The power scaling of the character was jagged ... we became supremely powerful after the first or
second region we unlocked and then decimated every boss we encountered until we reached the very
end. A power progression that matches progression through the multiworld is the key goal."*

`features/scaling.py` ramps ENEMY difficulty monotonically over the seed's true fill-sphere order.
Nothing ramped the PLAYER. So the two curves crossed early and never met again.

WHY THE PLAYER CURVE SATURATES, MEASURED AGAINST THAT SEED'S YAML
------------------------------------------------------------------
Four mechanisms compound, and only the last one is new work:

  1. THE BELL-BEARING BYPASS. A Miner's Bell Bearing is a permanent UNLIMITED shop unlock for its
     whole tier band, and `features/presence_floor.py` guarantees all nine are in the pool
     (injecting any whose home region was not kept). With `progressive_stone_bells` off they are
     nine independent items, so ONE early bearing ends the upgrade economy for the rest of the run.
     This is not a new finding -- features/progressive.py's docstring records it verbatim from
     boblerrr's 2026-08-10 playtest: *"a single vanilla `Somberstone Miner's Bell Bearing [5]`
     handed the player the top rung on pickup. That does not degrade the ladder, it BYPASSES it."*
     The ladder that fixes it shipped. It was just OFF BY DEFAULT.
  2. THE FLASK. `progressive_flasks` grades Golden Seeds and Sacred Tears into one paced ladder. It
     defaults ON; that seed turned it off, and got 43 interchangeable Golden Seeds instead.
  3. `auto_upgrade` raises every RECEIVED weapon to the top level you already hold on its track, so
     the moment any weapon reaches the ceiling, every future weapon arrives there free. That is a
     step function, and it AMPLIFIES 1 and 2 rather than causing them.
  4. LOOSE STONE TIER IS UNCOUPLED FROM DEPTH. `filler_budget._regular_stone_weights` tapers which
     tiers the seed HOLDS, but nothing constrains where a tier LANDS: a `Smithing Stone [8]` is as
     likely in sphere 0 as in the finale.

So this option is one switch over three ladders: it turns on the two that already exist and adds
the third (features/progressive, PROG_SMITHING_STONE / PROG_SOMBER_STONE) for the loose stones.
ONE OPTION MEANS ONE THING -- the same ruling features/vanilla_pool.py made for the two halves of
pool curation, and this module is deliberately shaped exactly like it.

WHY A RECEIVE-ORDERED LADDER AND NOT A PLACEMENT PASS
-----------------------------------------------------
The obvious design is "put low tiers in early regions". It is not available, twice over:

  * THERE IS NO DEPTH AXIS AT PLACEMENT TIME. The AP region graph is a 1-DEEP STAR: every kept
    region hangs off the always-open hub behind one interchangeable `<Region> Lock`, and
    `region_spine.compute_kept` draws the regions UNIFORMLY AT RANDOM. `SPINE` order is geography,
    not this seed's progression order -- grading by it would put tier-8 stones in whichever region
    the player happens to open first. features/scaling knows this and reads the TRUE fill spheres
    (`_region_fill_spheres`), which do not exist until after fill.
  * IT WAS BUILT ONCE AND DELETED. `stone_ramp` did exactly that, post-fill, and core.py's
    tombstone lists its three failures: an unsound supply model (it measured its deficit against a
    100%-collection fill sphere, so the deficit was ~never positive), a silent failure mode, and a
    fourth pass that relabelled and LOCKED placements after fill. features/filler_budget's doctrine
    is the lesson: *"coupling a player-visible economy to an invisible fill artifact is precisely
    what made stone_ramp both wrong and unfixable."*

A progressive ladder needs no depth axis, because TIER IS RECEIVE-COUNT. The Kth stone the
multiworld hands you grants the tier the ladder says, whoever placed it, wherever it sat, and
whichever world it came from. That is monotone by construction -- the exact inverse of jagged --
and it is the only formulation that survives the multiworld: with `filler_foreign_pct: 70` most of
this seed's stones live in PARTNER worlds and return on THEIR sphere schedule, which no ER-side
placement mechanism can reach. Under a ladder that is not a problem to solve; it is simply
irrelevant. `keep_local` and `filler_foreign_pct` need no change.

It also defuses `auto_upgrade` without touching it: raising a received weapon to your top HELD
track level is correct once that held level is itself paced.

MEASURED (re-rolled 2026-08-29 after the flask-substitution fix below; three real generations off
one seed, two Elden Ring slots each, the shipped template at `num_regions: 6`, charts in
`docs/measurements/`). The player number is the highest standard reinforce level the stones RECEIVED
by that sphere can pay for; the enemy number is the seed's own `regionSphereTargetRanges`,
normalised, for the regions unlocked by then:

    sphere                 0    1    2    3    4    5    6
    enemy   slot 1       29%  43%  57%  71%  71%  86%  86%
    today   slot 1      +14  +25  +25  +25  +25  +25  +25    MAX BY SPHERE 1
    step0   slot 1      +13  +25  +25  +25  +25  +25  +25    unchanged
    graded  slot 1      +13  +18  +21  +24  +24  +25  +25    climbs alongside the enemy curve

    enemy   slot 2       17%  33%  67%  67%  83%  83%  83%
    today   slot 2       +5   +7   +8   +8   +8   +8   +8    stalls at +8 for the whole run
    step0   slot 2       +4   +5   +8   +8   +8   +8   +8    unchanged
    graded  slot 2      +12  +15  +17  +22  +22  +25  +25    climbs, and ends 17 levels higher

⭐ SLOT 2 IS THE OTHER HALF OF THE ARGUMENT, and it was not visible in the first measurement.
Pacing is not a tax paid for a nicer curve: an UNPACED pool wastes itself. Slot 2's ungraded run
tops out at +8 and stays there, because its stones arrive tier-scrambled and the low tiers it
actually needs never accumulate. The identical supply, paced, reaches +25.

SOMBER, the same seed, slot 1, by the scaling level the game announces rather than by sphere, with
each somber level's standard equivalent beside it:

    enemy scaling       1.81x  2.27x  2.41x  3.25x  3.70x
    today   somber       +10    +10    +10    +10    +10   every rung in the easiest kept region
    graded  somber        +4     +6     +7    +10    +10
      = standard         +10    +15    +17    +25    +25

The `today` row is the somber track's version of the same defect: a somber weapon's level IS the
count of consecutive rungs held, so an ungraded seed hands over the whole track in the first region.

🛑 THE TWO TRACKS STILL DRIFT INSIDE A SEED, and the conversion cannot fix that half. Each ladder is
paced against ITS OWN copy stream, and the two supplies are neither the same size nor the same
shape, so somber finishes its ten rungs while the standard track is still short of its own top.
Closing that would mean pacing one ladder against the other's ACTUAL arrivals -- i.e. against the
fill -- which is the coupling this whole feature refuses. The rungs are in the right ORDER and at the
right relative POSITIONS; the two supplies arriving at different rates is fill's business.

`today slot 1` is the complaint this feature came from, reproduced exactly: maximum weapon power one
sphere in, against an enemy curve still at 43% of its ceiling, and then six spheres with nothing left
to gain. Both graded rows climb instead, running a roughly constant distance ahead of the enemy curve
rather than crossing it and flattening.

⭐ `step0` DOES NOT FIX THE STONE CURVE, and that is the measurement's most useful result. Turning
the shipped flask and bell ladders on closes the shop bypass -- worth doing on its own merits, and
this feature forces both on -- but the LOOSE stones still arrive tier-blind, so the seed still maxes
by sphere 1. Pacing the stones is the part that had no lever.

⭐ AND THE FLASK IS THE SAME STORY on its own axis, which is worth stating because the four causes
above treat `progressive_flasks` as a solved problem that a yaml merely switched off. Measured on
the same seed (`docs/measurements/flask-arrivals-by-sphere.svg`): ungraded, BOTH slots stall at 10
flask charges of a possible 14 from sphere 2 onward -- not short of pickups, short of the right ones,
because vanilla's seed cost escalates 1,1,2,2,3,3,4,4,5,5 and thirty seeds are needed to finish.
Slot 2 spends half the run at base POTENCY as well, drawing no Sacred Tear at all until sphere 3 (13
tears exist in the game against 43 seeds). The ladder cannot run out that way: every even copy is a
tear by construction, and the same pickups buy slot 1 four more charges and double the potency.


🛑 THREE HONEST CAVEATS ON THAT TABLE.
  * SPHERE 0 IS MOST OF A SIX-REGION SEED, so every row's opening overstates the real one: a fill
    sphere is a 100%-COLLECTION artifact and nobody clears every start-reachable check before moving
    on. `filler_budget.COLLECTION_RATE` exists because of exactly this, and it is why the early
    rungs still get `local_early_items` rather than being left to the sphere.
  * THE ROWS ARE LOWER BOUNDS WHERE A BELL LADDER IS ARMED. The analyzer counts stones RECEIVED; it
    cannot see the Twin Maiden shop, so `step0` and `graded` both do better in game than their rows.
  * ONE SEED, TWO SLOTS. Enough to reproduce a reported shape and to show the mechanism moving it;
    not enough to characterise the distribution. `tools/analyze_upgrade_curve.py` is the instrument
    for widening it.

🛑 THE FIRST VERSION OF THIS TABLE WAS WRONG, and the way it was wrong is worth keeping. The
analyzer's stone regex was anchored without the ` xN` suffix, so it scored every STACKED lot
(`Smithing Stone [2] x3` -- one check paying three stones, `core.stacked_vanilla_name`) as zero.
That is roughly half the tiered supply, and it made the ungraded seeds look STARVED (+3..+5 all
run) rather than saturated. Same data, opposite conclusion, and the graded rows never moved --
because substitution runs before the stack promotion, so a progressive copy is never stacked. A
measurement instrument that silently skips a name shape is the same failure class as a feature that
silently goes dark; it is now a fixed regex and a stated one.

THE TWO TRACKS ARE PACED AGAINST ONE POWER AXIS (Alaric, 2026-08-28)
--------------------------------------------------------------------
A somber weapon at +N is worth a standard weapon at **floor(N * 2.5)**: somber 1 is a +2, somber 5
a +12, somber 10 a +25. Without that conversion the two ladders were stretched independently --
regular over its cost table, somber uniformly over its nine tiers -- so nothing said whether a
player's somber weapon was ahead of or behind their standard one, and switching weapons could jump
or stall. `progressive.somber_share_schedule` now places each somber rung at the point in the run
where the REGULAR ladder reaches its equivalent, so both tracks climb one shared curve.

It also ends a documented guess. `filler_budget._somber_stone_need` says of the early guarantee:
*"Targeting the same EARLY_TARGET_LEVEL for both is therefore GENEROUS to somber ... somber +3 is
roughly regular +7.5 in effective terms."* Roughly is now exactly, and the answer is that the
regular +3 target converts to somber ONE.

...and it completes both ladders. The conversion's top rung is somber 10 = +25, which is a Somber
Ancient Dragon Smithing Stone; its standard counterpart is the Ancient Dragon Smithing Stone at +25.
Both sat OUTSIDE the ladder, so the tracks stopped at +24 and +22-equivalent and did not finish
level. They are rungs now, substituted like every other stone -- left loose, the top rung of a paced
ladder arrives in one pickup, which is the bell-bearing bypass in miniature.

WHAT IT DOES, EXACTLY
---------------------
  1. `progressive._flasks_on` returns True -- Golden Seeds / Sacred Tears become one paced ladder.
  2. `progressive._bells_on` returns True -- the bell bypass in 1 above is closed.

  🛑 1 AND 2 ARE PREDICATES, AND EVERY SITE ON THOSE PATHS MUST ASK THE PREDICATE, NOT THE OPTION.
  Read the raw yaml value anywhere on the path and the feature goes DARK rather than failing:
  `vanilla_substitutions` did exactly that for the flask until 2026-08-29, so a graded seed emitted a
  full-length `flaskLadder` and a full `progressiveGrants` entry for an item the pool held zero
  copies of, while the Golden Seeds stayed vanilla. Generation succeeded and the wire looked right.
  Same door features/presence_floor.py had to close for the bells (#539); gated now by
  tests/test_gf_graded_progression.py::GradedForcesTheFlaskLadder, whose yaml says
  `progressive_flasks: false` on purpose.

  3. `progressive.vanilla_substitutions` adds the stone names, and `filler_budget._draw_stones`
     mints progressive copies instead of tiered ones, so BOTH sources of stones feed one ladder.
  4. `filler_budget.early_guarantee` declares the progressive name, so the ladder's FIRST rungs are
     still `local_early_items` -- the +3-in-the-first-area floor is unchanged, it is only the
     CEILING that is new.

Each is a read of `is_on()` below, in the module that owns the behaviour: per features/README.md an
option has exactly one declaring feature, and the behaviour stays with the feature that already
implements it. This module owns only the option and the predicate.

OVERRIDE, NOT REJECT
--------------------
`ProgressiveFlasks.default` is 1 and `ProgressiveStoneBells.default` is 0, so every yaml carries a
value for both whether or not its author typed one, and Archipelago cannot tell an explicit value
from the default it filled in. Rejecting `graded_progression: true` alongside
`progressive_stone_bells: false` would reject the shipped template. So this OVERRIDES, and says so
in the generation log, once, by name -- the same ruling features/vanilla_pool.py and
features/vanilla_placement.py made, for the same reason.

🛑 INERT UNDER vanilla_pool AND vanilla_placement, and that is not a courtesy. Both modes promise
that a check pays what vanilla paid it; substituting a Smithing Stone for a synthetic ladder item
is precisely the randomizer behaviour they exist to switch off, and `vanilla_pool` additionally
leaves no stone economy for a ladder to be built from. Gated in `is_on()` so every caller sees the
same answer -- a feature that is off for the pool but on for the predicate is the split that gets
asserted green while the seed disagrees (features/presence_floor.py:169 documents the same trap).

🛑 WHAT IT DELIBERATELY DOES NOT TOUCH: THE GAME'S OWN STONE SOURCES.
The lever is scoped to the AP ITEM POOL -- what your checks pay. Mining an ore node still drops
tiered smithing stones, and the Twin Maidens still sell whatever tiers your bell rungs have unlocked.
Neither is a hole:

  * ORE NODES are already area-graded by FromSoft -- a Limgrave node drops [1]s and a Mountaintops
    node drops [7]s -- so they ramp with exactly the axis this feature ramps with, for free. Barring
    them would mean writing game files, which is the one thing this project does not do.
  * THE SHOP is the bell ladder, which this option forces on. Its four rungs are paced by receipt
    like everything else here, so the shop opens tier band by tier band rather than all at once.

Said out loud because a player who reads "stones are a ladder now" and then mines a [4] should find
the answer here rather than filing it as a bypass.

WORLD-ONLY, NO NEW WIRE KEY, NO VERSION PAIRING
-----------------------------------------------
The stone ladders ride `progressiveGrants`, which is an EXISTING declared ContractKey the client
already understands ("the client tracks how many copies of item_name it has received and, on the
Kth, grants the goods at ladder index K-1"). No `ContractKey` is added, so `CONTRACT_HASH` cannot
move and no client release has to be paired with this. Same footing as vanilla_pool's world-only
note -- except that here the wire is not empty, it is simply a wire that already exists.
"""
import logging

from Options import Toggle

from ..registry import Feature, register


class GradedProgression(Toggle):
    """Pace your power to your progress through the multiworld. Off by default.

    On: smithing stones, bell bearings, Golden Seeds and Sacred Tears stop being interchangeable
    pickups and become ladders. The Nth one you RECEIVE grants the Nth rung -- so early stones are
    low-tier and usable, and the top of the smithing ladder only opens once the multiworld has
    handed you most of your stones. Enemy scaling already ramps with the regions you unlock; this is
    the other half of that curve.

    Turn it on if a run went "we hit maximum weapon power two regions in and then flattened every
    boss". It is the answer to that specific complaint.

    It works no matter WHERE your stones ended up. A rung is counted when the item reaches you, so
    stones sitting in other players' worlds still arrive in ladder order -- you do not need to keep
    your upgrade materials local for this to work, and you should not.

    It switches Progressive Flasks and Progressive Stone Bell Bearings ON for you, overriding those
    two settings if you turned them off, because a loose bell bearing unlocks a whole tier band of
    the smithing shop at once and would walk straight past the stone ladder. The generation log
    names the override when it happens.

    Mining ore nodes and buying from the Twin Maidens still work normally -- ore already drops
    the tier that fits the area you are standing in, and the shop opens one tier band per bell
    rung, so both already ramp the way this does.

    Costs: your reachable weapon level now scales with the size of the seed, so a small
    `num_regions` run tops out lower than it does today. That is deliberate and it mirrors enemy
    scaling, whose own ceiling already drops with the region count. Ignored under Vanilla Item Pool
    and Vanilla Placement, which promise the opposite thing."""
    display_name = "Graded Progression"


def is_on(world) -> bool:
    """True when this seed was asked to pace power against depth.

    Deliberately tolerant of a missing option: `progressive` and `filler_budget` both call this, and
    both are imported by test harnesses and pre-regen tooling that build worlds without the full
    option surface. A missing option means the mode is off, which is the no-change default.

    🛑 THE TWO VANILLA MODES ARE CHECKED HERE, not at each call site. See the module docstring: one
    predicate, one answer, so the pool and the ladder can never disagree about whether the mode is
    armed.
    """
    o = getattr(getattr(world, "options", None), "graded_progression", None)
    if not (o is not None and o.value):
        return False
    # Both modes own an `is_on` predicate; ask THEM rather than re-reading their option here, so a
    # future change to what "armed" means for either cannot leave this one answer behind.
    from . import vanilla_placement as _vpl, vanilla_pool as _vp
    return not (_vp.is_on(world) or _vpl.is_on(world))


def log_override_once(world) -> None:
    """Say, once per world, that the mode turned on two toggles the player may have turned off.

    CONTRIBUTING: an override announces itself. This is the only line the mode prints on a clean
    run, and it exists because `progressive_stone_bells` is the toggle whose OFF state is the bug --
    a player who set it off explicitly deserves to be told that graded progression moved it, rather
    than discovering it by not finding a bell bearing.
    """
    if getattr(world, "_gf_graded_progression_logged", False):
        return
    world._gf_graded_progression_logged = True
    logging.getLogger("Greenfield").info(
        "[eldenring:%s] graded_progression is ON: smithing stones, somber stones, flasks and the "
        "Twin Maiden bell bearings are all paced ladders this seed -- the Nth copy RECEIVED grants "
        "the Nth rung, wherever it was placed and whichever world it came from. "
        "progressive_flasks and progressive_stone_bells are forced ON (a loose bell bearing "
        "unlocks a whole shop tier band at once and would bypass the stone ladder).",
        world.player)


@register
class GradedProgressionFeature(Feature):
    name = "graded_progression"
    # No ITEMS and no slot_data: this feature owns the option and the predicate only. The two
    # progressive stone items are declared by features/progressive.py beside its three siblings,
    # because that is the feature that already implements the ladder mechanism -- see the module
    # docstring's one-option-one-declaring-feature note.
    ITEMS = {}
    OPTIONS = {"graded_progression": GradedProgression}
