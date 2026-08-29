#!/usr/bin/env python3
"""analyze_upgrade_curve.py -- does the player's power curve track the enemy curve?

WHY THIS EXISTS, AND WHY IT EXISTED BEFORE
------------------------------------------
A tool by this name used to live here and went out with `stone_ramp` (core.py's tombstone). It is
back because `graded_progression` makes exactly one claim, and the claim is quantitative:

    the reachable weapon level should climb with progress through the multiworld, rather than
    saturating in the first region or two and then flattening.

That is not something a unit test can witness. The apworld suite builds ONE world and never looks at
where items land across slots (`tools/gf_multiworld_smoke.py` exists for the same reason), and the
report this feature came from -- "we became supremely powerful after the first or second region we
unlocked and then decimated every boss" (Alaric, 2026-08-27) -- is a statement about a whole
playthrough. So: build real seeds, read the spheres, and plot the two curves against each other.

🛑 IT MEASURES, IT DOES NOT GATE. There is no pass/fail floor recorded here and there should not be
one yet: the honest baseline is three measured rows (today, Step 0, Step 0 + the ladder), and a
threshold invented before those rows exist would be a number defending itself. `--verdict` prints
the comparison and the shape of it; a CI floor is a separate decision once the rows are in.

INPUT
-----
`GF_SPHERES_<seed>.json`, written by `greenfield/eldenring/core.py` when the environment variable
ER_GF_DUMP_SPHERES is set during a generation. It carries two views and this tool reads the SECOND:

  "spheres"  {player: [[item names in world X, by sphere], ...]}   -- what SITS in a world
  "received" {player: [[item names OWNED by player, by sphere], ...]} -- what REACHES a player

The receive view is the only correct one here. A progressive ladder advances when a copy reaches
you, and under `filler_foreign_pct` most of a slot's own filler sits in other people's worlds -- so
the world view measures stones the player never gets and misses every one they do.

THE TWO CURVES
--------------
PLAYER, per sphere: the highest standard-weapon reinforce level affordable from the stones received
up to and including that sphere, under this seed's `flatten_regular_upgrades` ladder. Expressed as a
fraction of the +24 cap.

ENEMY, per sphere: sphere index / last sphere index.

⭐ WHY THAT IS THE RIGHT ENEMY CURVE AND NOT A SHORTCUT. `features/scaling._targets_from_order`
ramps region difficulty EVENLY over a total order of the regions, and the client then NORMALISES
every target by the maximum emitted target (`scaling_ladder.py`: "scaling the wire up is a literal
no-op -- the deepest region always lands on the last rung"). So the applied enemy curve IS depth
expressed as a fraction of the run, up to the ramp shape.

The one thing this straight line does NOT model is a non-zero `difficulty_ramp_speed`, which bends
the enemy curve forward (`scaling.ramp_pct_from_speed`). At the shipped default of 0 the ramp IS
even and the line is exact; on a ramped seed the enemy curve sits ABOVE this line early, so the gap
reported here is a lower bound on how far ahead the player is. Stated rather than modelled, because
a seed's ramp setting is not in the dump and inferring it would be a guess presented as data.

🛑 WHAT THIS TOOL CANNOT SEE, and it matters for reading a `progressive_stone_bells` row. The
player curve is computed from stones RECEIVED. It does not model the Twin Maidens' shop, which a
bell-bearing rung unlocks for a whole tier band and which a player with runes will absolutely use.
So any row with the bell ladder armed is a LOWER BOUND on that seed's real reachable level. Modelling
it would mean modelling rune income, which is a bigger guess than the thing being measured.

The number that matters is the GAP, player minus enemy, per sphere. A run that spikes early shows a
large positive gap in the first spheres and a flat player curve after; a graded run should hold the
gap small across the whole seed.
"""
import argparse
import json
import os
import re
import sys

# The reinforce cap and cost table, mirrored from features/progressive.regular_stone_tier_seq. This
# tool runs against a JSON dump with no Archipelago on the path, so it cannot call the world -- but a
# second copy of a constant is exactly the drift this repo gates elsewhere (scadu_supply.SCADU_CUM
# against the Rust ladder). The self-test therefore lifts the live definitions straight out of the
# greenfield source and diffs them; see _live_ladder_namespace for why it parses rather than imports.
REGULAR_MAX_LEVEL = 24          # the last level the NUMBERED regular tiers reach
REGULAR_CAP_LEVEL = 25          # ...and the cap, once the Ancient Dragon step is counted
STONE_TIERS = 8
SOMBER_TIERS = 9
ANCIENT_REGULAR_TIER = STONE_TIERS + 1
ANCIENT_SOMBER_TIER = SOMBER_TIERS + 1
SOMBER_EQUIV_RATIO = 2.5        # a somber +N is worth a standard floor(N * 2.5)

PROG_SMITHING_STONE = "Progressive Smithing Stone"
PROG_SOMBER_STONE = "Progressive Somber Smithing Stone"
ANCIENT_REGULAR = "Ancient Dragon Smithing Stone"
ANCIENT_SOMBER = "Somber Ancient Dragon Smithing Stone"


def somber_to_regular(n):
    """A somber reinforce level -> the standard level it is worth: floor(N * 2.5). Somber 1 is a
    regular +2, somber 10 a +25. Mirrors features/progressive.somber_to_regular."""
    return int(n * SOMBER_EQUIV_RATIO)


def regular_to_somber(level):
    """The largest somber level whose equivalent still fits inside `level`. Mirrors
    features/progressive.regular_to_somber -- rounded DOWN so it never overclaims."""
    for n in range(ANCIENT_SOMBER_TIER, 0, -1):
        if somber_to_regular(n) <= level:
            return n
    return 0

# 🛑 THE ` xN` SUFFIX IS NOT DECORATION -- IT IS MOST OF THE SUPPLY (2026-08-28, Alaric).
# `core.stacked_vanilla_name` promotes a lot that vanilla drops several copies from to a STACKED AP
# item: `Smithing Stone [2] x3` is one check paying three stones. This regex was anchored without
# the suffix, so every stacked stone fell through the match and was counted as ZERO -- and stacks are
# not a rounding error here. Measured over these three dumps: 1040 single-stone names against 272
# stacked ones carrying 2-5 stones each, i.e. the tiered rows were undercounted by roughly half
# their supply, which makes an ungraded seed look poorer than it is and flatters the comparison.
#
# The graded rows were never affected, and for a reason worth keeping: substitution runs BEFORE the
# stack promotion (core.py's #616 ordering), and `Progressive Smithing Stone x3` is not a registered
# name, so a multi-copy lot pays exactly one rung. That asymmetry is real and is the point of the
# `raw stones` series in any comparison -- a graded seed hands over FEWER stones and more PROGRESS.
_TIERED_RE = re.compile(r"^(Somber Smithing Stone|Smithing Stone) \[(\d)\](?: x(\d+))?$")


def level_costs(flatten):
    """[(level, tier, stones)] for a standard weapon, level 1..24. The game's 2/4/6 ladder, each
    level capped at `flatten` when flatten_regular_upgrades is non-zero."""
    out = []
    for lvl in range(1, REGULAR_MAX_LEVEL + 1):
        tier = (lvl - 1) // 3 + 1
        vanilla = (2, 4, 6)[(lvl - 1) % 3]
        out.append((lvl, tier, min(vanilla, flatten) if flatten > 0 else vanilla))
    return out


def regular_stone_tier_seq(flatten):
    seq = []
    for _lvl, tier, cost in level_costs(flatten):
        seq += [tier] * cost
    return seq


def graded_regular_seq(flatten):
    """The numbered tiers, then the Ancient Dragon step (+24 -> +25, one stone). Mirrors
    features/progressive.graded_regular_seq."""
    return regular_stone_tier_seq(flatten) + [ANCIENT_REGULAR_TIER]


def somber_stone_tier_seq():
    """Mirrors features/progressive.somber_stone_tier_seq -- the nine NUMBERED somber tiers."""
    return list(range(1, SOMBER_TIERS + 1))


def somber_share_schedule(flatten):
    """Cumulative fraction of the run at which each somber rung arrives, via the equivalence.
    Mirrors features/progressive.somber_share_schedule."""
    cum, run = {}, 0
    for lvl, _t, cost in level_costs(flatten):
        run += cost
        cum[lvl] = run
    cum[REGULAR_CAP_LEVEL] = run + 1
    total = cum[REGULAR_CAP_LEVEL]
    return [cum[min(somber_to_regular(n), REGULAR_CAP_LEVEL)] / total
            for n in range(1, ANCIENT_SOMBER_TIER + 1)]


def build_somber_ladder(n, flatten):
    """Mirrors features/progressive.build_somber_ladder."""
    tiers = ANCIENT_SOMBER_TIER
    if n <= 0:
        return []
    if n <= tiers:
        return list(range(1, n + 1))
    shares = somber_share_schedule(flatten)
    spare = n - tiers
    out = []
    for i in range(tiers):
        cum = int(round(shares[i] * spare)) + (i + 1)
        cum = max(cum, i + 1)
        cum = min(cum, n - (tiers - 1 - i))
        out += [i + 1] * (cum - len(out))
    return out


def stretch_ladder(seq, n):
    f = len(seq)
    if n <= 0 or f == 0:
        return []
    if n <= f:
        return list(seq[:n])
    return [seq[min(f - 1, (k * f) // n)] for k in range(n)]


# Mirrors features/filler_budget's early guarantee (EARLY_TARGET_LEVEL 3, EARLY_GUARANTEE_MARGIN 2)
# and features/progressive.build_ladder. --selftest diffs the construction against the live source.
EARLY_TARGET_LEVEL = 3
EARLY_GUARANTEE_MARGIN = 2


def early_segment(somber, flatten):
    """Mirrors features/progressive._early_segment: the stones +EARLY_TARGET_LEVEL costs, and the
    copies the early guarantee declares to cover them with. Summed over LEVELS, not over tier 1 --
    see that function for why the two are only coincidentally equal."""
    if somber:
        split = max(1, regular_to_somber(EARLY_TARGET_LEVEL))
    else:
        split = sum(c for lvl, _t, c in level_costs(flatten) if lvl <= EARLY_TARGET_LEVEL)
    return split, split * EARLY_GUARANTEE_MARGIN


def build_ladder(seq, n, split_at, early_copies):
    """Mirrors features/progressive.build_ladder -- see there for why segment 1 is a FLOOR and not
    a cap (the [2, 2, 2, 19, 19, ...] somber distribution), and why a clamp sits above it."""
    if n <= 0 or not seq:
        return []
    if n <= split_at:
        return list(seq[:n])
    proportional = round(n * split_at / len(seq))
    ceiling = n - (len(seq) - split_at)
    early_n = min(max(split_at, early_copies, proportional), max(ceiling, split_at))
    return stretch_ladder(seq[:split_at], early_n) + stretch_ladder(seq[split_at:], n - early_n)


def reachable_level(held, flatten):
    """Highest standard level affordable from `held` = {tier: copies}. Greedy and exact: the ladder
    is strictly ordered, so a level is reachable iff every level below it was paid for first.

    🛑 SPENDS FROM THE EXACT TIER ONLY. Elden Ring does not let a Smithing Stone [4] pay for a level
    that wants a [2], so a model that pooled the tiers would report a curve no player can walk --
    and reporting a healthier curve than the seed has is the failure mode this whole tool exists to
    catch. That asymmetry is also precisely what `graded_progression` fixes: under the ladder the
    tiers arrive in the order they are spent, so "held" and "spendable" converge.
    """
    left = dict(held)
    lvl = 0
    for level, tier, cost in level_costs(flatten):
        if left.get(tier, 0) < cost:
            return lvl
        left[tier] -= cost
        lvl = level
    # ...and the un-numbered last step, +24 -> +25 on one Ancient Dragon Smithing Stone. Stopping at
    # the numbered tiers reports the cap a level low and ignores that stone's supply entirely.
    if left.get(ANCIENT_REGULAR_TIER, 0) >= 1:
        lvl = REGULAR_CAP_LEVEL
    return lvl


def somber_reachable_level(held):
    """Somber weapons cost one stone per level and the tier IS the level, so the reachable level is
    the longest unbroken run of tiers held from 1.

    🛑 ONE FUNCTION FOR BOTH SEEDS, deliberately. An earlier version short-circuited the graded case
    to `min(copies, 9)` -- i.e. assumed the Nth copy grants tier N -- which is exactly what
    `build_ladder` does NOT do on a seed with more copies than rungs. It would have reported somber
    +6 where the ladder actually delivers +1, which is the class of error this tool exists to catch,
    committed by the tool itself. Both seeds now go through the same held-tiers count.
    """
    lvl = 0
    for t in range(1, ANCIENT_SOMBER_TIER + 1):   # ...through +10, the Somber Ancient Dragon step
        if held.get(t, 0) < 1:
            break
        lvl = t
    return lvl


# ---- the flask track -------------------------------------------------------------------------------
# MIRRORS the flask half of features/progressive.py. The flask is the OTHER graded economy in a
# seed, and graded_progression's own docstring treats it as already solved ("it defaults ON; that
# seed turned it off") -- so it deserves the same measurement the stones got rather than an
# assumption. Everything here is closed-form and seed-independent; only the ARRIVALS come from a
# generation.
PROG_FLASK = "Progressive Flask Upgrade"
VANILLA_GOLDEN_SEED = "Golden Seed"
VANILLA_SACRED_TEAR = "Sacred Tear"

FLASK_CHARGES_BASE = 4          # vanilla starting allocation
FLASK_CHARGES_MAX = 14
FLASK_POTENCY_MAX = 12
# vanilla Golden Seeds per charge level; 30 seeds buys all ten steps (4 -> 14)
FLASK_CHARGE_SEED_COST = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
FLASK_SEED_TOTAL = sum(FLASK_CHARGE_SEED_COST)

# ⭐ The flask holds exactly TWENTY-TWO upgrades, and one rung carries at most one of them. A seed
# with more copies than that has copies that cannot be made to pay -- the game's ceiling, not a
# scheduling failure. Mirrors features/progressive.
FLASK_CHARGE_STEPS = FLASK_CHARGES_MAX - FLASK_CHARGES_BASE     # 10
FLASK_POTENCY_STEPS = FLASK_POTENCY_MAX                         # 12
FLASK_UPGRADES = FLASK_CHARGE_STEPS + FLASK_POTENCY_STEPS       # 22

# What a received copy DOES. Not a tier -- the flask has no tier, it has two axes and a cap on each,
# so the honest categorical is "which axis did this copy move, or neither". The first two strings are
# also features/progressive's FLASK_CHARGE / FLASK_TEAR, and --selftest diffs them.
CHARGE, TEAR, INERT = "charge", "tear", "inert"
FLASK_CHARGE, FLASK_TEAR = CHARGE, TEAR
FLASK_KINDS = (CHARGE, TEAR, INERT)

_STACK_RE = re.compile(r"^(.*?) x(\d+)$")


def flask_event_seq():
    """The flask's twenty-two upgrades in hand-out order. Mirrors features/progressive."""
    out, charges, tears = [], FLASK_CHARGE_STEPS, FLASK_POTENCY_STEPS
    while charges or tears:
        if charges:
            out.append(FLASK_CHARGE)
            charges -= 1
        if tears:
            out.append(FLASK_TEAR)
            tears -= 1
    return out


def flask_schedule(n):
    """What each of `n` copies does: CHARGE, TEAR or None. Mirrors features/progressive.

    THE STRETCH. Up to 22 copies every one pays, on the first N of the alternating sequence. Past
    that the twenty-two upgrades spread evenly across all N -- first on copy 1, last on copy N -- and
    the surplus is interleaved rather than dumped at the end.
    """
    seq = flask_event_seq()
    if n <= 0:
        return []
    if n <= len(seq):
        return list(seq[:n])
    out = [None] * n
    for j, event in enumerate(seq):
        out[(j * (n - 1)) // (len(seq) - 1)] = event
    if sum(1 for e in out if e is not None) != len(seq):
        raise ValueError("flask_schedule(%d) lost an upgrade to a collision" % n)
    return out


def flask_ladder(n):
    """[{"charges", "potency"}] per received copy, walked off the schedule. Mirrors
    features/progressive.flask_ladder."""
    charges, potency = FLASK_CHARGES_BASE, 0
    out = []
    for event in flask_schedule(n):
        if event == FLASK_CHARGE:
            charges = min(charges + 1, FLASK_CHARGES_MAX)
        elif event == FLASK_TEAR:
            potency = min(potency + 1, FLASK_POTENCY_MAX)
        out.append({"charges": charges, "potency": potency})
    return out


def flask_waste(n):
    """Copies that grant nothing in a seed holding `n`. Zero at or below the upgrade count."""
    return max(0, n - FLASK_UPGRADES)


def vanilla_flask_state(seeds, tears):
    """(charges, potency) for a player holding `seeds` Golden Seeds and `tears` Sacred Tears.

    The vanilla path, i.e. progressive_flasks OFF. Seeds are spent against the ESCALATING cost table
    -- the tenth charge step alone costs five -- which is why a pile of loose seeds converts to far
    less flask than the same number of ladder copies does.
    """
    lvl, spent = 0, 0
    for cost in FLASK_CHARGE_SEED_COST:
        if seeds < spent + cost:
            break
        spent += cost
        lvl += 1
    return FLASK_CHARGES_BASE + lvl, min(tears, FLASK_POTENCY_MAX)


def _flask_names(items):
    """Yield (name, qty) for every flask-economy item in a sphere, stacked lots expanded."""
    for raw in items:
        name, qty = raw, 1
        m = _STACK_RE.match(raw)
        if m:
            name, qty = m.group(1), int(m.group(2))
        if name in (PROG_FLASK, VANILLA_GOLDEN_SEED, VANILLA_SACRED_TEAR):
            yield name, qty


def flask_series(spheres):
    """Per fill sphere: arrivals by kind, and the flask state reached.

    Two shapes, one series. With the ladder on, every arrival is a PROG_FLASK copy and its kind is
    its ordinal. With it off, arrivals are loose Golden Seeds and Sacred Tears, and a pickup is
    INERT once its own axis can take no more -- 30 seeds buys every charge step, 12 tears every
    potency step, and the 31st seed is a souvenir. Both are answering "did this pickup make you
    stronger", which is the only question that makes the two comparable.
    """
    graded = any(n == PROG_FLASK for sph in spheres for n, _q in _flask_names(sph))
    # 🛑 THE SCHEDULE NEEDS THE TOTAL UP FRONT, and that is the whole point of the stretch: a copy's
    # effect depends on how many the SEED holds, not on its ordinal alone. Counting them first is not
    # foreknowledge the player needs -- the apworld builds the same ladder at generation time.
    total_copies = sum(q for sph in spheres for n, q in _flask_names(sph) if n == PROG_FLASK)
    schedule = flask_schedule(total_copies)
    copies = seeds = tears = 0
    out = []
    for sidx, items in enumerate(spheres):
        per = {k: 0 for k in FLASK_KINDS}
        for name, qty in _flask_names(items):
            for _ in range(qty):
                if name == PROG_FLASK:
                    per[schedule[copies] or INERT] += 1
                    copies += 1
                elif name == VANILLA_GOLDEN_SEED:
                    seeds += 1
                    per[CHARGE if seeds <= FLASK_SEED_TOTAL else INERT] += 1
                else:
                    tears += 1
                    per[TEAR if tears <= FLASK_POTENCY_MAX else INERT] += 1
        if graded:
            # the state after `copies` of the seed's `total_copies` -- read off the full ladder, not
            # a ladder rebuilt for a shorter seed, which would be a different schedule entirely
            lad = flask_ladder(total_copies)
            charges = lad[copies - 1]["charges"] if copies else FLASK_CHARGES_BASE
            potency = lad[copies - 1]["potency"] if copies else 0
        else:
            charges, potency = vanilla_flask_state(seeds, tears)
        out.append({"sphere": sidx, "graded": graded, "charges": charges, "potency": potency,
                    "received": copies if graded else seeds + tears, **per})
    return out


def curve_for_player(spheres, flatten):
    """[(sphere, regular_level, somber_level)] cumulatively over `spheres` (a list of item-name
    lists). Detects graded vs tiered from the names present, because the two need different
    arithmetic and guessing wrong would silently report the other seed's curve."""
    total_prog = sum(row.count(PROG_SMITHING_STONE) for row in spheres)
    total_somber_prog = sum(row.count(PROG_SOMBER_STONE) for row in spheres)
    graded = bool(total_prog or total_somber_prog)
    # The ladders are a function of the TOTAL copy count, so they are built from the whole dump
    # before the walk -- the same way the world builds them from the whole pool in set_rules.
    reg_ladder = build_ladder(graded_regular_seq(flatten), total_prog,
                              *early_segment(False, flatten)) if graded else []
    # The somber track is paced by the equivalence rather than stretched over its own tiers.
    somber_ladder = build_somber_ladder(total_somber_prog, flatten) if graded else []

    held = {}
    somber_held = {}
    prog_seen = 0
    somber_prog_seen = 0
    out = []
    for sidx, row in enumerate(spheres):
        for name in row:
            if name == PROG_SMITHING_STONE:
                # The ladder decides the tier: this is the (prog_seen+1)-th copy received.
                if prog_seen < len(reg_ladder):
                    held[reg_ladder[prog_seen]] = held.get(reg_ladder[prog_seen], 0) + 1
                prog_seen += 1
                continue
            if name == PROG_SOMBER_STONE:
                if somber_prog_seen < len(somber_ladder):
                    t = somber_ladder[somber_prog_seen]
                    somber_held[t] = somber_held.get(t, 0) + 1
                somber_prog_seen += 1
                continue
            if name == ANCIENT_REGULAR:
                held[ANCIENT_REGULAR_TIER] = held.get(ANCIENT_REGULAR_TIER, 0) + 1
                continue
            if name == ANCIENT_SOMBER:
                somber_held[ANCIENT_SOMBER_TIER] = somber_held.get(ANCIENT_SOMBER_TIER, 0) + 1
                continue
            m = _TIERED_RE.match(name)
            if m:
                bucket = somber_held if m.group(1).startswith("Somber") else held
                t = int(m.group(2))
                bucket[t] = bucket.get(t, 0) + int(m.group(3) or 1)
        out.append((sidx, reachable_level(held, flatten), somber_reachable_level(somber_held)))
    return out, graded


def report(path, flatten, verdict):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    view = data.get("received")
    if not view:
        print("  !! this dump has no `received` view -- it predates the 2026-08-28 core change.\n"
              "     The `spheres` view answers 'what SITS in a world', which is the wrong question\n"
              "     for a power curve. Re-generate with a current apworld.")
        return 1
    rc = 0
    for player, spheres in sorted(view.items()):
        curve, graded = curve_for_player(spheres, flatten)
        if len(curve) < 2:
            print("  %s: only %d sphere(s) -- no depth to measure over." % (player, len(curve)))
            continue
        last = len(curve) - 1
        print("\n  %s  [%s, flatten=%d, %d spheres]"
              % (player, "GRADED" if graded else "tiered", flatten, len(curve)))
        print("    sphere   depth%   +N    power%   gap")
        worst = 0.0
        for sidx, lvl, _somber in curve:
            depth = sidx / last
            power = lvl / REGULAR_CAP_LEVEL
            gap = power - depth
            worst = max(worst, gap)
            print("    %6d   %5.0f%%  %3d   %5.0f%%  %+5.0f%%"
                  % (sidx, 100 * depth, lvl, 100 * power, 100 * gap))
        final = curve[-1][1]
        print("    peak gap %+.0f%%   final +%d of +%d   somber +%d (= regular +%d)"
              % (100 * worst, final, REGULAR_CAP_LEVEL, curve[-1][2],
                 somber_to_regular(curve[-1][2])))
        if verdict:
            # The SHAPE, stated in words. A spike is a large early gap followed by a flat top; a
            # tracked curve holds the gap small the whole way. No threshold is asserted -- see the
            # measures-not-gates note in the module docstring.
            half = curve[len(curve) // 2][1]
            if final and half >= final:
                print("    VERDICT: SATURATED -- the curve reached its top (+%d) by the halfway "
                      "sphere and the back half of the run has no progression." % final)
                rc = max(rc, 1)
            elif worst > 0.35:
                print("    VERDICT: FRONT-LOADED -- peak gap %+.0f%%; power ran ahead of depth."
                      % (100 * worst))
            else:
                print("    VERDICT: TRACKING -- peak gap %+.0f%% across the run." % (100 * worst))
    return rc


def _live_ladder_namespace():
    """The ladder's pure half, lifted out of `features/progressive.py` BY SOURCE.

    🛑 DELIBERATELY NOT `import worlds.eldenring...`. Importing the apworld pulls in Archipelago's
    world loader, which scans every shipped world, fails noisily on the ones whose optional
    dependencies are absent, and can block on an interactive install prompt. A measurement tool that
    can hang on someone else's missing `pyevermizer` is not a tool anyone will run.

    So: parse the module, keep only the constants and the three pure functions this file mirrors,
    and exec that. No Archipelago, no side effects, no import of anything but `typing`. Returns None
    when the source is not beside this tool (a packaged copy), in which case the gate says it was
    skipped rather than passing vacuously.
    """
    import ast  # noqa: PLC0415 -- only needed on the selftest path
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "greenfield", "eldenring", "features", "progressive.py")
    if not os.path.exists(src_path):
        return None
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    want_fns = {"regular_stone_tier_seq", "somber_stone_tier_seq", "stretch_ladder",
                "regular_level_costs", "build_ladder", "graded_regular_seq",
                "somber_share_schedule", "build_somber_ladder", "somber_to_regular",
                "regular_to_somber", "flask_event_seq", "flask_schedule"}
    want_consts = {"STONE_TIERS", "SOMBER_TIERS", "REGULAR_MAX_LEVEL", "REGULAR_CAP_LEVEL",
                   "ANCIENT_REGULAR_TIER", "ANCIENT_SOMBER_TIER", "SOMBER_EQUIV_RATIO",
                   "ANCIENT_REGULAR", "ANCIENT_SOMBER",
                   "PROG_SMITHING_STONE", "PROG_SOMBER_STONE",
                   # the flask half: the ladder builder there takes a `world` and caches on it, so
                   # it cannot be lifted -- but every number it is built out of can be, and a drifted
                   # constant is the realistic drift.
                   "PROG_FLASK", "VANILLA_FLASK_ITEMS", "FLASK_CHARGES_BASE", "FLASK_CHARGES_MAX",
                   "FLASK_POTENCY_MAX", "FLASK_CHARGE_SEED_COST",
                   "FLASK_CHARGE_STEPS", "FLASK_POTENCY_STEPS", "FLASK_UPGRADES",
                   "FLASK_CHARGE", "FLASK_TEAR", "DLC_ONLY_FLASK_COPIES"}
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want_fns:
            keep.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in want_consts for t in node.targets):
            keep.append(node)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and (
                isinstance(node.target, ast.Name) and node.target.id in want_consts):
            # 🛑 ANNOTATED CONSTANTS COUNT. `FLASK_CHARGE_SEED_COST: List[int] = [...]` is an
            # AnnAssign, not an Assign, so an Assign-only walk skips it and the `missing` assert
            # below fires -- which is the gate failing safe, but only because something asked for
            # one. Handling both node types is what stops the next annotated constant from being
            # quietly unmirrorable.
            keep.append(node)
    # The lifted source carries its own annotations (`List[Optional[str]]`), which are evaluated at
    # def time -- so the namespace has to supply the names the module imported from `typing`, not a
    # stand-in that only happens to work for the un-subscripted cases.
    import typing  # noqa: PLC0415
    ns = {"List": typing.List, "Optional": typing.Optional, "Dict": typing.Dict, "Any": typing.Any}
    exec(compile(ast.Module(body=keep, type_ignores=[]), src_path, "exec"), ns)
    missing = (want_fns | want_consts) - set(ns)
    assert not missing, (
        "features/progressive.py no longer defines %s at module level -- the mirror gate cannot "
        "see the ladder any more, so fix the extraction rather than deleting the gate." % sorted(missing))
    return ns


def selftest():
    """The classification and curve logic, against synthetic dumps, with no AP and no game data.

    The tool this replaces had no self-test, and `tools/fill_regression.py` records what that costs:
    one harness fault wearing nine verdicts. A measurement nobody can check is not a measurement.
    """
    seq = regular_stone_tier_seq(2)
    assert len(seq) == 48 and seq[0] == 1 and seq[-1] == STONE_TIERS, seq[:5]
    assert stretch_ladder(seq, 48) == seq
    assert len(stretch_ladder(seq, 96)) == 96 and stretch_ladder(seq, 96)[-1] == STONE_TIERS
    assert stretch_ladder(seq, 10) == seq[:10]

    # exact-tier spending: six [1] buys +3 at flatten 2, and a pile of [8] buys nothing
    assert reachable_level({1: 6}, 2) == 3
    assert reachable_level({8: 99}, 2) == 0
    assert reachable_level({1: 6, 2: 6, 3: 6}, 2) == 9

    # STACKED LOTS COUNT AS N STONES, NOT ONE, AND NOT ZERO. The regression that made the first
    # published table wrong: an anchored regex without the ` xN` suffix scored every stacked lot as
    # zero, which is roughly half a tiered seed's supply.
    assert _TIERED_RE.match("Smithing Stone [2] x3").group(3) == "3"
    assert _TIERED_RE.match("Smithing Stone [2]").group(3) is None
    assert _TIERED_RE.match("Ancient Dragon Smithing Stone") is None, (
        "the +25 step is not a ladder tier and must not be counted as one")
    assert _TIERED_RE.match(PROG_SMITHING_STONE) is None, "a ladder copy is not a tiered stone"
    bundled, _g = curve_for_player([["Smithing Stone [1] x3", "Smithing Stone [1] x3"]], 2)
    assert bundled[0][1] == 3, (
        "six tier-1 stones arriving as two x3 lots must buy +3 at flatten 2, not %d -- the ` xN` "
        "suffix is being dropped again" % bundled[0][1])

    # a spike: everything in sphere 0
    spike = [[f"Smithing Stone [{t}]" for t in range(1, 9) for _ in range(6)], [], [], []]
    curve, graded = curve_for_player(spike, 2)
    assert not graded
    assert curve[0][1] == REGULAR_MAX_LEVEL, curve
    assert curve[-1][1] == REGULAR_MAX_LEVEL

    # a graded seed: 48 rungs spread evenly over 4 spheres climbs instead of spiking
    graded_rows = [[PROG_SMITHING_STONE] * 12 for _ in range(4)]
    curve, graded = curve_for_player(graded_rows, 2)
    assert graded
    levels = [lvl for _s, lvl, _so in curve]
    assert levels == sorted(levels) and levels[0] < levels[-1], levels
    assert levels[0] <= REGULAR_MAX_LEVEL // 3, (
        "a graded first sphere must not already be most of the way up: %r" % levels)
    assert levels[-1] == REGULAR_MAX_LEVEL, (
        "a seed holding exactly the full ladder must still reach the cap -- the early segment is "
        "eating the tail: %r" % levels)

    live = _live_ladder_namespace()
    if live is None:
        print("selftest: OK (greenfield source not beside this tool -- mirror gate skipped)")
        return 0
    for flatten in range(0, 5):
        assert live["regular_stone_tier_seq"](flatten) == regular_stone_tier_seq(flatten), flatten
        assert live["stretch_ladder"](live["regular_stone_tier_seq"](flatten), 70) == \
            stretch_ladder(regular_stone_tier_seq(flatten), 70), flatten
    assert live["somber_stone_tier_seq"]() == list(range(1, SOMBER_TIERS + 1))
    for flatten in (0, 2):
        for somber in (False, True):
            seq = (live["somber_stone_tier_seq"]() if somber
                   else live["regular_stone_tier_seq"](flatten))
            mine_seq = somber_stone_tier_seq() if somber else regular_stone_tier_seq(flatten)
            for n in (7, 40, 200):
                assert live["build_ladder"](seq, n, *early_segment(somber, flatten)) == \
                    build_ladder(mine_seq, n, *early_segment(somber, flatten)), (somber, flatten, n)
    assert live["regular_level_costs"](2) == level_costs(2)[:REGULAR_MAX_LEVEL], (
        "level_costs must mirror regular_level_costs over the NUMBERED tiers; the +25 step is "
        "appended here and by graded_regular_seq there, not folded into the cost table")

    # ---- the equivalence, and everything paced by it ------------------------------------------
    # THE TABLE ALARIC GAVE, verbatim. Deriving it from floor(N * 2.5) and then testing the
    # derivation against itself would gate nothing; this is the independent statement.
    stated = {1: 2, 2: 5, 3: 7, 4: 10, 5: 12, 6: 15, 7: 17, 8: 20, 9: 22, 10: 25}
    for n, reg in stated.items():
        assert somber_to_regular(n) == reg, (n, somber_to_regular(n), reg)
        assert live["somber_to_regular"](n) == reg, "the world disagrees at somber %d" % n
    assert regular_to_somber(3) == 1 and live["regular_to_somber"](3) == 1, (
        "regular +3 converts to somber ONE (+2) -- somber 2 is +5 and overshoots")
    assert regular_to_somber(25) == 10 and regular_to_somber(1) == 0
    for flatten in (0, 2, 3):
        assert live["somber_share_schedule"](flatten) == somber_share_schedule(flatten), flatten
        assert live["graded_regular_seq"](flatten) == graded_regular_seq(flatten), flatten
        for n in (4, 10, 11, 40, 119, 300):
            mine = build_somber_ladder(n, flatten)
            assert live["build_somber_ladder"](n, flatten) == mine, (flatten, n)
            assert len(mine) == n and mine == sorted(mine)
            if n >= ANCIENT_SOMBER_TIER:
                # a SKIPPED somber tier is a permanent wall, not thin supply
                assert set(mine) == set(range(1, ANCIENT_SOMBER_TIER + 1)), (flatten, n, sorted(set(mine)))

    # the two tracks now top out at the same power
    assert somber_to_regular(ANCIENT_SOMBER_TIER) == REGULAR_CAP_LEVEL
    assert reachable_level({ANCIENT_REGULAR_TIER: 1, **{t: 99 for t in range(1, 9)}}, 2) == (
        REGULAR_CAP_LEVEL), "the Ancient Dragon step must reach +25"
    assert reachable_level({t: 99 for t in range(1, 9)}, 2) == REGULAR_MAX_LEVEL, (
        "...and without it the numbered tiers stop at +24")
    assert somber_reachable_level({t: 1 for t in range(1, ANCIENT_SOMBER_TIER + 1)}) == 10
    assert (live["PROG_SMITHING_STONE"], live["PROG_SOMBER_STONE"]) == \
        (PROG_SMITHING_STONE, PROG_SOMBER_STONE)
    assert (live["STONE_TIERS"], live["SOMBER_TIERS"], live["REGULAR_MAX_LEVEL"]) == \
        (STONE_TIERS, SOMBER_TIERS, REGULAR_MAX_LEVEL)

    # ---- the flask track ----------------------------------------------------------------------
    assert (live["PROG_FLASK"], tuple(live["VANILLA_FLASK_ITEMS"])) == (
        PROG_FLASK, (VANILLA_GOLDEN_SEED, VANILLA_SACRED_TEAR))
    assert (live["FLASK_CHARGES_BASE"], live["FLASK_CHARGES_MAX"], live["FLASK_POTENCY_MAX"]) == (
        FLASK_CHARGES_BASE, FLASK_CHARGES_MAX, FLASK_POTENCY_MAX)
    assert live["FLASK_CHARGE_SEED_COST"] == FLASK_CHARGE_SEED_COST

    # the alternating ruling (#798) -- kept by the stretch, stated rather than re-derived
    assert (FLASK_CHARGE_STEPS, FLASK_POTENCY_STEPS, FLASK_UPGRADES) == (10, 12, 22)
    assert flask_event_seq()[:20] == [CHARGE, TEAR] * 10
    assert flask_event_seq()[20:] == [TEAR, TEAR], "the two axes are different lengths"
    assert live["flask_event_seq"]() == flask_event_seq()
    lad = flask_ladder(6)
    assert [r["charges"] for r in lad] == [5, 5, 6, 6, 7, 7], lad
    assert [r["potency"] for r in lad] == [0, 1, 1, 2, 2, 3], lad
    assert lad[0]["charges"] == FLASK_CHARGES_BASE + 1, (
        "the first charge rung must be one ABOVE the vanilla allocation, or a fresh character "
        "absorbs it silently")

    # 🛑 THE STRETCH, diffed against the live apworld at every size a seed can be. A drift here is a
    # chart that draws a schedule the game does not run.
    for n in list(range(0, 60)) + [120, 232]:
        assert flask_schedule(n) == live["flask_schedule"](n), n
        sched = flask_schedule(n)
        assert len(sched) == n
        assert sum(1 for e in sched if e is None) == flask_waste(n), n
        if n >= FLASK_UPGRADES:
            assert [e for e in sched if e] == flask_event_seq(), n
            assert sched[0] and sched[-1], "the ladder must start on copy 1 and finish on copy n"
            assert flask_ladder(n)[-1] == {"charges": FLASK_CHARGES_MAX,
                                           "potency": FLASK_POTENCY_MAX}, n
    assert flask_waste(22) == 0 and flask_waste(30) == 8 and flask_waste(56) == 34
    assert live["DLC_ONLY_FLASK_COPIES"] == FLASK_UPGRADES, (
        "the dlc_only floor must inject one copy per upgrade -- more would inject dead copies")

    # the vanilla path, and the reason the two are worth charting side by side: the SAME pickups
    # buy less flask loose than they do as ladder copies, because vanilla's seed cost escalates
    assert vanilla_flask_state(FLASK_SEED_TOTAL, FLASK_POTENCY_MAX) == (
        FLASK_CHARGES_MAX, FLASK_POTENCY_MAX)
    assert vanilla_flask_state(0, 0) == (FLASK_CHARGES_BASE, 0)
    assert vanilla_flask_state(19, 19)[0] < flask_ladder(19)[-1]["charges"], (
        "19 loose Golden Seeds must buy FEWER charges than 19 ladder copies -- if this ever stops "
        "being true the comparison chart has no story")

    # arrivals: stacked lots expand, and a non-flask stack is not miscounted as one
    ser = flask_series([["Golden Seed x2", "Smithing Stone [1] x3"], ["Sacred Tear"]])
    assert [d[CHARGE] for d in ser] == [2, 0] and [d[TEAR] for d in ser] == [0, 1], ser
    # two seeds buy the first TWO charge steps (they cost 1 each), so 4 -> 6; the escalation only
    # bites later, which is exactly why the loose track looks fine early and stalls afterwards
    assert not ser[0]["graded"] and ser[-1]["charges"] == 6 and ser[-1]["potency"] == 1, ser[-1]
    gser = flask_series([[PROG_FLASK] * 3, [PROG_FLASK]])
    assert gser[0]["graded"] and gser[-1]["received"] == 4
    assert gser[-1]["charges"] == 6 and gser[-1]["potency"] == 2, gser[-1]
    # a seed past the upgrade count: the surplus must be scored INERT and spread, not trailing
    big = flask_series([[PROG_FLASK] * 30])
    assert big[-1][INERT] == flask_waste(30) == 8, big[-1]
    assert big[-1]["charges"] == FLASK_CHARGES_MAX and big[-1]["potency"] == FLASK_POTENCY_MAX

    print("selftest: OK (mirror gate against greenfield/eldenring/features/progressive.py passed)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dumps", nargs="*", help="GF_SPHERES_*.json files to read")
    ap.add_argument("--flatten", type=int, default=2,
                    help="the seed's flatten_regular_upgrades (defaults.py freezes it at 2)")
    ap.add_argument("--verdict", action="store_true", help="print the shape of each curve in words")
    ap.add_argument("--selftest", action="store_true", help="check the logic, no data needed")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.dumps:
        ap.error("give at least one GF_SPHERES_*.json (set ER_GF_DUMP_SPHERES during a generation "
                 "to produce one), or pass --selftest")
    rc = 0
    for path in args.dumps:
        print("== %s" % os.path.basename(path))
        rc = max(rc, report(path, args.flatten, args.verdict))
    return rc


if __name__ == "__main__":
    sys.exit(main())
