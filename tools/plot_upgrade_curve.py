#!/usr/bin/env python3
"""plot_upgrade_curve.py -- the upgrade-curve measurement, as committable SVG.

WHY THIS EXISTS
---------------
`tools/analyze_upgrade_curve.py` prints the numbers. Numbers in a terminal answer "is it working";
they do not answer "what SHAPE is the curve", which is the whole question `graded_progression` was
built around -- a run that spikes and flattens and a run that climbs can share a final value. The
shape is what a reader needs to see, and it is what a reviewer should be able to check without
re-running three generations.

So this writes the same data as charts, into the repo, beside the claim they support.

🛑 PURE STDLIB, HAND-WRITTEN SVG, NO PLOTTING LIBRARY. `tools/gf_multiworld_smoke.py` states the
house rule for its partner worlds -- "pure Python with no ROM and no extra pip dependency" -- and a
measurement tool that only runs where someone has installed matplotlib is a measurement nobody
re-runs. The repo already ships hand-built SVG (`poptracker/maps/*.svg`) and hand-built HTML
(`tools/build_check_browser.py`), so this is the grain, not a workaround.

INPUT: the generation ARCHIVE, not a loose dump
------------------------------------------------
One `AP_<seed>.zip` per configuration. The archive carries BOTH halves this needs and they must come
from the same seed or the comparison is meaningless:

  * `GF_SPHERES_<seed>.json` -- written when ER_GF_DUMP_SPHERES is set during a generation; its
    `received` view is what reaches each player, per fill sphere.
  * the `.archipelago` multidata -- carries slot_data, hence `regionSphereTargetRanges`, the seed's
    OWN enemy-scaling wire.

Reading the enemy curve off the wire rather than deriving it is deliberate. The applied difficulty
IS the normalised target (the client divides by the max emitted target, so gen-side magnitude is a
no-op), and a derivation would have to re-implement the finale append, the floor-pinned buckets and
the intra-fold deltas -- three chances to draw a curve the seed does not have.

`--ap-dir` is required for the same reason `gf_multiworld_smoke.py` requires it: `restricted_loads`
lives in the Archipelago root, and the multidata is not readable without it.

USAGE
    python tools/plot_upgrade_curve.py --ap-dir .ap-test \\
        --label today=path/AP_x.zip --label graded=path/AP_y.zip --out docs/measurements
    python tools/plot_upgrade_curve.py --ap-dir .ap-test \
        --across "flasks off=runs/off/*/AP_*.zip" --across "flasks on=runs/on/*/AP_*.zip"
    python tools/plot_upgrade_curve.py --selftest

TWO MODES, TWO QUESTIONS. `--label` compares a few CONFIGURATIONS of ONE seed: does this lever move
the curve. `--across` pools MANY runs of one configuration into an arm and draws the spread: what
does it do to my seeds. One seed shows a mechanism and cannot show a distribution; many runs show a
distribution and bury the mechanism in the median. Mixing them in one invocation is refused.
"""
import argparse
import glob
import html
import importlib.util
import json
import math
import os
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_spec = importlib.util.spec_from_file_location("auc", os.path.join(HERE, "analyze_upgrade_curve.py"))
AUC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AUC)

FLATTEN_DEFAULT = 2          # defaults.py freezes flatten_regular_upgrades at 2
MAXLVL = AUC.REGULAR_CAP_LEVEL      # +25, the Ancient Dragon step included


# ---- palette -------------------------------------------------------------------------------------
# The validated data-viz palette. Every value here cleared `scripts/validate_palette.js`:
# the two series as an adjacent categorical pair (CVD dE 24.7 light / 26.8 dark, both modes PASS),
# and each 4-bin sequential ramp under `--ordinal` (monotone L, adjacent dL >= 0.06, light end
# >= 2:1 against its own surface). Do not hand-edit a step without re-running that script -- the
# whole point of the palette being validated is that it is not eyeballed.
LIGHT = {
    "surface": "#fcfcfb", "plane": "#f9f9f7", "ink": "#0b0b0b", "ink2": "#52514e",
    "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7",
    "player": "#2a78d6", "enemy": "#eb6834",
    # The flask's two axes as a categorical pair; `validate_palette.js "#2a78d6,#eb6834" --mode
    # light` and its dark counterpart both PASS on all five checks (CVD dE 24.7 / 26.8 protan).
    "flcharge": "#2a78d6", "fltear": "#eb6834",
    # 🛑 `flinert` IS DELIBERATELY ACHROMATIC and fails the validator's chroma floor on purpose. It
    # is not a third identity -- it is the absence of one, "this copy granted nothing", the same
    # role the empty outlined cell plays on the stone heatmaps. Giving it a hue would claim it is a
    # kind of upgrade. It is never the only thing distinguishing two real categories.
    "flinert": "#cfcdc4",
    "reg": ["#86b6ef", "#5598e7", "#256abf", "#104281"],
    "som": ["#eda06e", "#e0762f", "#b85618", "#7d3a10"],
}
DARK = {
    "surface": "#1a1a19", "plane": "#0d0d0d", "ink": "#ffffff", "ink2": "#c3c2b7",
    "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835",
    "player": "#3987e5", "enemy": "#d95926",
    "flcharge": "#3987e5", "fltear": "#d95926", "flinert": "#4a4a46",
    "reg": ["#184f95", "#2a78d6", "#6da7ec", "#b7d3f6"],
    "som": ["#8a3d17", "#c25a22", "#e8894e", "#f6bd9c"],
}
# Count bins for the heatmaps. Four classes, because past ~7 adjacent classes blur and the exact
# number is in the tooltip-free case unavailable -- so the cell also carries its count as text.
BINS = [(2, "1-2"), (5, "3-5"), (9, "6-9"), (10 ** 9, "10+")]

FONT_SANS = "system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def header_width(lines, size=12.5, pad=26):
    """The canvas width a block of header lines needs.

    Sizing a figure from its PLOT and then drawing a wider sentence across the top is the bug this
    exists to stop: the geometry audit caught exactly that when the scaling axis made the plots
    narrower than their own subtitle. 0.62em per character is a deliberate over-estimate for a
    proportional sans -- erring wide costs whitespace, erring narrow clips words.
    """
    return int(pad * 2 + max((len(l) for l in lines), default=0) * size * 0.62)


def panel_width(rows, pad=11, gutter=14):
    """The panel width a set of (left, left_size, right, right_size) header/footer rows needs.

    A PANEL IS AS WIDE AS ITS WIDEST SENTENCE, not just its plot. A short seed makes the plot
    narrower than its own title row or footer, and the overflow guard in --selftest fires on exactly
    that -- which is the guard working, not a reason to relax it. Same 0.62em-per-character
    over-estimate header_width uses, for the same reason: erring wide costs whitespace, erring
    narrow clips words.
    """
    return max([int(pad + len(l) * ls * 0.62 + gutter + len(r) * rs * 0.62 + pad)
                for l, ls, r, rs in rows] or [0])


def bin_of(v):
    if v <= 0:
        return -1
    for i, (hi, _lab) in enumerate(BINS):
        if v <= hi:
            return i
    return len(BINS) - 1


# ---- reading a generation --------------------------------------------------------------------
def read_archive(zip_path):
    """(spheres_by_player, slot_data_by_player_name) out of one generation archive."""
    import Utils  # noqa: PLC0415 -- importable only after --ap-dir is on sys.path
    with zipfile.ZipFile(zip_path) as z:
        dumps = [n for n in z.namelist() if os.path.basename(n).startswith("GF_SPHERES_")]
        if not dumps:
            sys.exit("%s carries no GF_SPHERES dump -- generate with ER_GF_DUMP_SPHERES set."
                     % os.path.basename(zip_path))
        dump = json.loads(z.read(dumps[0]).decode("utf-8"))
        mds = [n for n in z.namelist() if n.endswith(".archipelago")]
        if not mds:
            sys.exit("%s carries no multidata." % os.path.basename(zip_path))
        md = Utils.restricted_loads(zlib.decompress(z.read(mds[0])[1:]))

    received = dump.get("received")
    if not received:
        sys.exit("%s predates the `received` view. The `spheres` view answers 'what SITS in a "
                 "world', which is the wrong question for a power curve -- regenerate with a "
                 "current apworld." % os.path.basename(zip_path))

    slot_info = md["slot_info"]
    slot_data = md.get("slot_data", {})
    by_name = {}
    for num, si in slot_info.items():
        name = getattr(si, "name", None) or (si["name"] if isinstance(si, dict) else None)
        if name is not None:
            by_name[name] = slot_data.get(num, {})
    return received, by_name


def scaling_ladder():
    """`greenfield/eldenring/scaling_ladder.py`, loaded by path. Plain stdlib, no Archipelago.

    This module is the PINNED Python mirror of the client's `SCALING_TIERS`
    (`tests/test_gf_scaling_ladder_mirror.py` parses the Rust source and fails on divergence), so
    reading the ladder and the two band lookups from here rather than retyping them means this tool
    cannot drift from the client on its own.
    """
    p = os.path.join(ROOT, "greenfield", "eldenring", "scaling_ladder.py")
    spec = importlib.util.spec_from_file_location("gf_scaling_ladder", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SL = scaling_ladder()
NUM_TIERS = len(SL.SCALING_HP_LADDER)


def tier_for_target(target, max_target, floor_t, ceiling_t):
    """The rung a region lands on. MIRROR of er-logic `scaling::tier_for_target`.

    🛑 NORMALISED TO THE BAND, NOT THE LADDER, and that is the whole subtlety. `frac` is this run's
    depth; the band [floor, ceiling] is the range the seed actually chose. Spending the fraction on
    rungs the seed forbade and clamping afterwards collapses every deep region onto the ceiling --
    the saturation bug the Rust function documents at length.

    🛑 `floor(x + 0.5)`, NOT `round(x)`. Rust's `f32::round` is half-away-from-zero; Python's
    `round` is half-to-even. On a 12-rung band the two disagree on exact .5 fractions, which is
    precisely where a region sits when it is halfway through the run -- so the naive port would
    print a different tier than the player's own toast for the most ordinary case there is.
    """
    ceiling = min(ceiling_t, NUM_TIERS - 1)
    floor = min(floor_t, ceiling)                 # ceiling first, then floor into it -- the client's order
    if max_target <= 0:
        return floor
    frac = min(max(target, 0) / max_target, 1.0)
    return min(max(floor + math.floor(frac * (ceiling - floor) + 0.5), floor), ceiling)


def band_of(sd):
    """(floor_tier, ceiling_tier) for a slot, from the same two wire keys the client reads.

    Both are MULTIPLIERS on the wire, not tier indices -- `core._options_echo` unit-converts the
    player's percent before emitting (the 2026-07-27 units bug is documented at length in
    `scaling_ladder.py`). Absent keys mean an unbounded band, which is what an older seed gets.
    """
    opts = sd.get("options", {}) or {}
    fl, ce = opts.get("completion_scaling_floor"), opts.get("completion_scaling_ceiling")
    floor = SL.tier_for_floor_multiplier(fl) if fl else 0
    ceiling = SL.tier_for_ceiling_multiplier(ce) if ce else NUM_TIERS - 1
    return floor, ceiling


def scaling_play_ids():
    """region -> the play_region buckets whose difficulty the wire sets. A plain generated dict, so
    it loads by path with no Archipelago and no apworld import."""
    p = os.path.join(ROOT, "greenfield", "eldenring", "region_play_ids.py")
    spec = importlib.util.spec_from_file_location("rpi", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.SCALING_PLAY_IDS


def region_tiers(sd, play_ids):
    """region -> the ABSOLUTE rung the client resolves it to, plus the seed's band.

    This is the number behind the in-game toast: `region_scaling_toast` prints
    `"<region> - enemy scaling <mult>x (tier <t - floor> of <ceiling - floor>)"`, i.e. the position
    WITHIN the band, because an absolute index means nothing outside the range the seed chose.
    """
    triples = sd.get("regionSphereTargetRanges") or []
    by_bucket = {int(lo): int(t) for lo, _hi, t in triples}
    top = max(by_bucket.values()) if by_bucket else 0
    floor, ceiling = band_of(sd)
    out = {}
    for region, buckets in play_ids.items():
        vals = [by_bucket[b] for b in buckets if b in by_bucket]
        if vals:
            out[region] = tier_for_target(max(vals), top, floor, ceiling)
    return out, floor, ceiling


def enemy_by_region(sd, play_ids):
    """region -> applied enemy difficulty, 0..1.

    `regionSphereTargetRanges` is [[lo, hi, target], ...] per play_region bucket, and the client
    normalises by the MAX emitted target, so the normalised value is what the player actually meets.
    A region with several buckets takes its max -- the hardest ground it contains, which is what
    "how hard has it got" means for a region you have just opened.
    """
    triples = sd.get("regionSphereTargetRanges") or []
    by_bucket = {int(lo): int(t) for lo, _hi, t in triples}
    top = max(by_bucket.values()) if by_bucket else 0
    out = {}
    for region, buckets in play_ids.items():
        vals = [by_bucket[b] for b in buckets if b in by_bucket]
        if vals:
            out[region] = (max(vals) / top) if top else 0.0
    return out


def series_for(spheres, sd, play_ids, flatten):
    """Per sphere: stones received by tier, cumulative reachable levels, enemy difficulty so far."""
    etier = enemy_by_region(sd, play_ids)
    rtier, floor, ceiling = region_tiers(sd, play_ids)
    cur_tier = floor
    tot_reg = sum(r.count(AUC.PROG_SMITHING_STONE) for r in spheres)
    tot_som = sum(r.count(AUC.PROG_SOMBER_STONE) for r in spheres)
    graded = bool(tot_reg or tot_som)
    reg_ladder = (AUC.build_ladder(AUC.graded_regular_seq(flatten), tot_reg,
                                   *AUC.early_segment(False, flatten)) if graded else [])
    # the somber track is paced by the somber<->regular equivalence, not stretched over its tiers
    som_ladder = AUC.build_somber_ladder(tot_som, flatten) if graded else []
    held, som_held = {}, {}
    seen_r = seen_s = 0
    enemy = 0.0
    out = []
    for sidx, items in enumerate(spheres):
        # the top row of each track is the un-numbered Ancient Dragon rung (+25 / +10)
        per_r = {t: 0 for t in range(1, AUC.ANCIENT_REGULAR_TIER + 1)}
        per_s = {t: 0 for t in range(1, AUC.ANCIENT_SOMBER_TIER + 1)}
        for name in items:
            if name.endswith(" Lock"):
                region = name[:-5]
                if region in etier:
                    enemy = max(enemy, etier[region])
                if region in rtier:
                    # The player's live scaling level is the hardest region they have opened -- the
                    # last number their unlock toast showed them. Monotone by construction.
                    cur_tier = max(cur_tier, rtier[region])
                continue
            if name == AUC.PROG_SMITHING_STONE:
                if seen_r < len(reg_ladder):
                    per_r[reg_ladder[seen_r]] += 1
                seen_r += 1
                continue
            if name == AUC.PROG_SOMBER_STONE:
                if seen_s < len(som_ladder):
                    per_s[som_ladder[seen_s]] += 1
                seen_s += 1
                continue
            if name == AUC.ANCIENT_REGULAR:
                per_r[AUC.ANCIENT_REGULAR_TIER] += 1
                continue
            if name == AUC.ANCIENT_SOMBER:
                per_s[AUC.ANCIENT_SOMBER_TIER] += 1
                continue
            m = AUC._TIERED_RE.match(name)
            if m:
                qty = int(m.group(3) or 1)          # ` xN` is most of an ungraded seed's supply
                (per_s if m.group(1).startswith("Somber") else per_r)[int(m.group(2))] += qty
        for t, c in per_r.items():
            held[t] = held.get(t, 0) + c
        for t, c in per_s.items():
            som_held[t] = som_held.get(t, 0) + c
        out.append({
            "sphere": sidx, "regular": per_r, "somber": per_s,
            "level": AUC.reachable_level(held, flatten),
            "somber_level": AUC.somber_reachable_level(som_held),
            "enemy": enemy,
            "raw_regular": sum(per_r.values()), "raw_somber": sum(per_s.values()),
            "graded": graded,
            "tier": cur_tier - floor,               # what the toast prints
            "tier_span": ceiling - floor,
            "tier_mult": SL.SCALING_HP_LADDER[min(cur_tier, NUM_TIERS - 1)],
        })
    # THE FLASK RIDES ALONG, computed by the analyzer so there is one implementation of the
    # alternating ladder and one of the vanilla seed/tear costs. Merged in by position: both walks
    # are over the same `spheres` list in the same order, and zip() would silently truncate a
    # disagreement, so the length is asserted instead.
    flask = AUC.flask_series(spheres)
    assert len(flask) == len(out), (len(flask), len(out))
    for d, f in zip(out, flask):
        d.update(("flask_" + k, v) for k, v in f.items() if k != "sphere")
    return out


def by_scaling_tier(ser):
    """Re-bucket a per-sphere series onto the ENEMY SCALING LEVEL the player was at.

    A fill sphere is an artifact of how Archipelago filled the seed; the scaling tier is the number
    the game itself put on screen when a region opened ("tier 4 of 11, 1.95x"). Asking "what stones
    arrive while the world is at 1.95x" is the question a player actually has, and it is the one
    this axis answers.

    Several spheres can sit at one tier (a sphere that opened no harder region does not move it), so
    counts SUM. The tier is monotone over spheres, so the columns stay in play order.

    🛑 A SEED VISITS A SUBSET OF ITS BAND. Six regions cannot occupy twelve rungs, so the columns
    are the tiers this run actually reaches -- not 0..span with gaps. Rendering the empty rungs
    would draw eleven columns of nothing and imply the player passed through them.
    """
    cols = []
    for d in ser:
        if cols and cols[-1]["tier"] == d["tier"]:
            c = cols[-1]
            for t, v in d["regular"].items():
                c["regular"][t] += v
            for t, v in d["somber"].items():
                c["somber"][t] += v
            c["spheres"].append(d["sphere"])
            c["level"] = d["level"]
            c["somber_level"] = d["somber_level"]
        else:
            cols.append({
                "tier": d["tier"], "tier_span": d["tier_span"], "tier_mult": d["tier_mult"],
                "regular": dict(d["regular"]), "somber": dict(d["somber"]),
                "level": d["level"], "somber_level": d["somber_level"],
                "spheres": [d["sphere"]],
            })
    return cols


# ---- the game's own stone supply -----------------------------------------------------------------
# The ladder tops, which are NOT tier 8 / tier 9.
#
# ⭐ A standard weapon reaches +24 on the eight numbered tiers and takes its LAST step, +24 -> +25,
# on an Ancient Dragon Smithing Stone; a somber weapon reaches +9 on its nine tiers and takes
# +9 -> +10 on a Somber Ancient Dragon Smithing Stone. Both are single, un-numbered items with their
# own supply, so a chart that stops at tier 8 / tier 9 stops one level short of the real ladder and
# silently drops 26 stones. (Alaric, 2026-08-28.)
ANCIENT_REGULAR = "Ancient Dragon Smithing Stone"
ANCIENT_SOMBER = "Somber Ancient Dragon Smithing Stone"


def stone_supply():
    """Every smithing stone that EXISTS as a check in Elden Ring, by the upgrade level it serves.

    -> {"regular": [(lo_level, hi_level, label, single, bundled)], "somber": [...]}

    SEED-INDEPENDENT, on purpose: this is the game's placement, not one generation's. It reads the
    generated `LOCATION_ITEM` / `LOCATION_UNITS` tables directly, so it needs no archive, no
    Archipelago and no `--ap-dir`.

    🛑 BUNDLES ARE COUNTED AS THEIR CONTENTS, AND KEPT SEPARATE. `LOCATION_UNITS` is the per-lot
    quantity, so a check paying `Smithing Stone [2] x3` contributes THREE stones -- counting it as
    one is the same undercount that made the first published curve wrong. The single/bundled split
    is kept because the two are different things to a player: a bundle is one check that pays a
    handful, so a seed's stone supply is far lumpier than its check count suggests.
    """
    p = os.path.join(ROOT, "greenfield", "eldenring", "item_ids.py")
    spec = importlib.util.spec_from_file_location("gf_item_ids", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    single, bundled = {}, {}
    for ap, name in m.LOCATION_ITEM.items():
        qty = m.LOCATION_UNITS.get(ap, 1)
        key = None
        mt = AUC._TIERED_RE.match(name or "")
        if mt and mt.group(3) is None:               # the table's names carry no ` xN` suffix
            key = ("somber" if mt.group(1).startswith("Somber") else "regular", int(mt.group(2)))
        elif name == ANCIENT_REGULAR:
            key = ("regular", AUC.STONE_TIERS + 1)
        elif name == ANCIENT_SOMBER:
            key = ("somber", AUC.SOMBER_TIERS + 1)
        if key is None:
            continue
        (bundled if qty > 1 else single)[key] = (bundled if qty > 1 else single).get(key, 0) + qty

    out = {}
    rows = []
    for t in range(1, AUC.STONE_TIERS + 1):
        # tier t reinforces levels 3t-2 .. 3t: three levels per numbered tier, all the way up
        rows.append((3 * t - 2, 3 * t, "[%d]" % t,
                     single.get(("regular", t), 0), bundled.get(("regular", t), 0)))
    rows.append((25, 25, "Anc.Dragon",
                 single.get(("regular", AUC.STONE_TIERS + 1), 0),
                 bundled.get(("regular", AUC.STONE_TIERS + 1), 0)))
    out["regular"] = rows
    rows = []
    for t in range(1, AUC.SOMBER_TIERS + 1):
        rows.append((t, t, "[%d]" % t,
                     single.get(("somber", t), 0), bundled.get(("somber", t), 0)))
    rows.append((10, 10, "Anc.Dragon",
                 single.get(("somber", AUC.SOMBER_TIERS + 1), 0),
                 bundled.get(("somber", AUC.SOMBER_TIERS + 1), 0)))
    out["somber"] = rows
    return out


def fig_supply(out_path):
    """How many of each smithing stone exist as checks, over the upgrade level they reinforce.

    🛑 A BIN SPANS THE LEVELS ITS STONE SERVES; IT IS NOT REPEATED AT EACH. A numbered regular tier
    reinforces three levels, so its bar is three level-units WIDE and its height is counted once.
    Drawing the same count at +1, +2 and +3 would treble the apparent supply, which is the honest
    trap in putting a per-TIER quantity on a per-LEVEL axis. Somber bins are one level wide, so that
    half is an ordinary bar chart.
    """
    data = stone_supply()
    PAD, GAPY = 26, 20
    L, R, T, B = 46, 14, 26, 46
    UNIT = 34                     # px per upgrade level
    PLOT_H = 190
    widest = max(len(v) and v[-1][1] for v in data.values())
    PW = L + widest * UNIT + R
    HEAD, LEG = 74, 30
    PH = T + PLOT_H + B
    W = max(PAD * 2 + PW, header_width([
        "Smithing stones in Elden Ring, by the level they reinforce",
        "Every stone that exists as a check, counted in stones rather than checks -- a bundled "
        "lot contributes all of its contents.",
        "A numbered tier reinforces three levels, so its bar spans three; the Ancient Dragon "
        "stones are the single-level top of each ladder."], 12.5, PAD))
    H = HEAD + LEG + 2 * PH + GAPY + PAD

    top = 0
    for rows in data.values():
        top = max(top, max(sg + bn for _lo, _hi, _lab, sg, bn in rows))
    step = 25 if top > 60 else 10
    ymax = ((top // step) + 1) * step

    s = svg_open(W, H, "Smithing stones in Elden Ring, by the level they reinforce",
                 "Stone supply across the whole game, split by whether the check pays a single "
                 "stone or a bundled lot.")
    s += text(PAD, 30, "Smithing stones in Elden Ring, by the level they reinforce", 18, "ink",
              mono=False, weight="600")
    s += text(PAD, 50, "Every stone that exists as a check, counted in stones rather than checks "
              "-- a bundled lot contributes all of its contents.", 12.5, "ink2", mono=False)
    s += text(PAD, 66, "A numbered tier reinforces three levels, so its bar spans three; the "
              "Ancient Dragon stones are the single-level top of each ladder.", 12.5, "ink2",
              mono=False)

    ly = HEAD + 14
    for i, (lab, colour) in enumerate((("single-stone checks", "var(--player)"),
                                       ("bundled lots (x2-x5), counted in stones", "var(--enemy)"))):
        lx = PAD + i * 210
        s += ('<rect x="%.1f" y="%.1f" width="13" height="13" rx="2" fill="%s"/>\n'
              % (lx, ly - 10, colour))
        s += text(lx + 19, ly, lab, 11.5, "ink2", mono=False)

    for pi, (kind, label, cap) in enumerate((
            ("regular", "Regular smithing stones", "standard weapons, +1 to +25"),
            ("somber", "Somber smithing stones", "somber weapons, +1 to +10"))):
        rows = data[kind]
        ox, oy = PAD, HEAD + LEG + pi * (PH + GAPY)
        s += card(ox, oy, PW, PH)
        s += text(ox + 13, oy + 19, label, 12, "ink", weight="600")
        s += text(ox + PW - 13, oy + 19, cap, 9.5, "muted", anchor="end")

        py = lambda v: oy + T + PLOT_H - (v / ymax) * PLOT_H
        for g in range(0, ymax + 1, step):
            s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                  % (ox + L, ox + L + rows[-1][1] * UNIT, py(g), py(g),
                     "axis" if g == 0 else "grid"))
            s += text(ox + L - 7, py(g) + 3.4, str(g), 9, "muted", anchor="end")

        for lo, hi, lab, sg, bn in rows:
            x0 = ox + L + (lo - 1) * UNIT
            w = (hi - lo + 1) * UNIT
            # 2px surface gaps: between bars, and between the two stacked segments
            bx, bw = x0 + 1.5, w - 3
            if bn:
                s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" '
                      'fill="var(--enemy)"/>\n' % (bx, py(bn), bw, py(0) - py(bn)))
            if sg:
                y0 = py(bn + sg)
                s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" '
                      'fill="var(--player)"/>\n' % (bx, y0, bw, (py(bn) - y0) - (2 if bn else 0)))
            s += text(x0 + w / 2, py(sg + bn) - 6, str(sg + bn), 10, "ink", anchor="middle")
            s += text(x0 + w / 2, oy + T + PLOT_H + 26, lab, 9, "ink2", anchor="middle")

        # the level axis itself, a tick per upgrade level
        for lvl in range(1, rows[-1][1] + 1):
            cx = ox + L + (lvl - 1) * UNIT + UNIT / 2
            s += text(cx, oy + T + PLOT_H + 14, "+%d" % lvl, 8.5, "muted", anchor="middle")
        s += text(ox + L - 7, oy + T + PLOT_H + 14, "level", 8.5, "muted", anchor="end")
        s += text(ox + L - 7, oy + T + PLOT_H + 26, "stone", 8.5, "muted", anchor="end")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


# ---- SVG -----------------------------------------------------------------------------------------
def esc(s):
    return html.escape(str(s), quote=True)


def svg_open(w, h, title, desc):
    """An SVG that carries its OWN ground and its own dark palette.

    Both halves matter for a file that will be opened straight out of the repo. Without an explicit
    background rect it composites onto whatever the viewer paints -- light text on light in a dark
    file browser. The `prefers-color-scheme` block then re-points every token, so the same file is
    legible in a dark editor and a light one; the class names below are the only thing the drawing
    code refers to.
    """
    css_vars = lambda p: "\n".join(
        "    --%s: %s;" % (k, v) for k, v in p.items() if not isinstance(v, list)
    ) + "\n" + "\n".join(
        "    --%s-%d: %s;" % (k, i + 1, c)
        for k in ("reg", "som") for i, c in enumerate(p[k])
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'role="img" aria-labelledby="t d" font-family="%s">\n'
        '<title id="t">%s</title><desc id="d">%s</desc>\n'
        '<style>\n  svg {\n%s\n  }\n'
        '  @media (prefers-color-scheme: dark) {\n    svg {\n%s\n    }\n  }\n'
        '  .ink { fill: var(--ink); }\n'
        '  .ink2 { fill: var(--ink2); }\n'
        '  .muted { fill: var(--muted); }\n'
        '  .mono { font-family: %s; }\n'
        '</style>\n'
        '<rect width="100%%" height="100%%" fill="var(--plane)"/>\n'
        % (w, h, w, h, esc(FONT_SANS), esc(title), esc(desc),
           css_vars(LIGHT), css_vars(DARK), esc(FONT_MONO))
    )


def text(x, y, s, size=10, cls="muted", anchor="start", mono=True, weight=None):
    return ('<text x="%.1f" y="%.1f" font-size="%s" text-anchor="%s" class="%s%s"%s>%s</text>\n'
            % (x, y, size, anchor, cls, " mono" if mono else "",
               ' font-weight="%s"' % weight if weight else "", esc(s)))


def card(x, y, w, h):
    return ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" fill="var(--surface)" '
            'stroke="var(--grid)"/>\n' % (x, y, w, h))


# ---- the trajectory figure -----------------------------------------------------------------------
def fig_trajectory(cols, out_path):
    """Player power vs enemy scaling, one panel per (config, slot). Both series are percentages of
    their own ceiling, so they share ONE axis -- a dual-axis version of this chart would invent a
    correlation that is not in the data."""
    PW, PH, GAP, PAD = 300, 190, 16, 26
    ncol = len(cols[0][1])
    nrow = len(cols)
    LEGEND_MIN = PAD + 212 + int(len("Enemy scaling (% of ceiling)") * 12 * 0.62) + PAD
    W = max(PAD * 2 + ncol * PW + (ncol - 1) * GAP, LEGEND_MIN, header_width([
        "Player power against enemy scaling",
        "Both series are percentages of their own ceiling, so they share one axis.",
        "A curve that reaches the top early has no run left to climb."], 12.5, PAD))
    HEAD, LEG = 74, 30
    H = HEAD + LEG + nrow * PH + (nrow - 1) * GAP + PAD

    s = svg_open(W, H, "Player power against enemy scaling",
                 "One panel per configuration and slot. Player power is the highest standard "
                 "reinforce level the stones received by that fill sphere can pay for, over +24. "
                 "Enemy is the seed's own normalised regionSphereTargetRanges.")
    s += text(PAD, 30, "Player power against enemy scaling", 18, "ink", mono=False, weight="600")
    s += text(PAD, 50, "Both series are percentages of their own ceiling, so they share one axis.",
              12.5, "ink2", mono=False)
    s += text(PAD, 66, "A curve that reaches the top early has no run left to climb.",
              12.5, "ink2", mono=False)
    # legend
    ly = HEAD + 14
    s += ('<rect x="%.1f" y="%.1f" width="16" height="3" rx="1.5" fill="var(--player)"/>\n'
          % (PAD, ly - 4))
    s += text(PAD + 22, ly, "Player power (+N of +24)", 12, "ink2", mono=False)
    s += ('<rect x="%.1f" y="%.1f" width="16" height="3" rx="1.5" fill="var(--enemy)"/>\n'
          % (PAD + 190, ly - 4))
    s += text(PAD + 212, ly, "Enemy scaling (% of ceiling)", 12, "ink2", mono=False)

    for ri, (slot, panels) in enumerate(cols):
        for ci, (label, tag, ser) in enumerate(panels):
            ox = PAD + ci * (PW + GAP)
            oy = HEAD + LEG + ri * (PH + GAP)
            s += card(ox, oy, PW, PH)
            L, R, T, B = 40, 34, 34, 26
            n = len(ser)
            px = lambda i: ox + L + (i / (n - 1)) * (PW - L - R)
            py = lambda v: oy + T + (1 - v) * (PH - T - B)

            s += text(ox + 13, oy + 20, "%s  %s" % (slot, label), 11.5, "ink", weight="600")
            s += text(ox + PW - 13, oy + 20, tag, 9.5, "muted", anchor="end")

            for g in (0, .25, .5, .75, 1):
                s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                      % (ox + L, ox + PW - R, py(g), py(g), "axis" if g == 0 else "grid"))
                s += text(ox + L - 6, py(g) + 3.4, "%d%%" % round(g * 100), 9, "muted", anchor="end")
            for i in range(n):
                if i % 2 == 0 or i == n - 1:
                    s += text(px(i), oy + PH - 9, str(i), 9, "muted", anchor="middle")
            s += text(ox + PW / 2, oy + PH + 0.5, "", 9)

            for key, colour, val, fmt in (
                ("player", "var(--player)", lambda d: d["level"] / MAXLVL,
                 lambda d: "+%d" % d["level"]),
                ("enemy", "var(--enemy)", lambda d: d["enemy"],
                 lambda d: "%d%%" % round(d["enemy"] * 100)),
            ):
                pts = " ".join("%.1f,%.1f" % (px(i), py(val(d))) for i, d in enumerate(ser))
                s += ('<polyline points="%s" fill="none" stroke="%s" stroke-width="2" '
                      'stroke-linejoin="round" stroke-linecap="round"/>\n' % (pts, colour))
                for i, d in enumerate(ser):
                    s += ('<circle cx="%.1f" cy="%.1f" r="3.1" fill="%s" stroke="var(--surface)" '
                          'stroke-width="2"/>\n' % (px(i), py(val(d)), colour))
                # direct-label the endpoint only -- a number on every point goes unread
                s += text(px(n - 1) + 7, py(val(ser[-1])) + 3.4, fmt(ser[-1]), 10, "ink2")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


# ---- the distribution figures --------------------------------------------------------------------
def fig_heat(cols, out_path, kind, title, blurb):
    """Enemy scaling level x stone tier, cell = stones of that tier received while the world was
    at that level.

    THE X-AXIS IS THE NUMBER THE GAME PUTS ON SCREEN. When a region opens, the client toasts
    `"<region> - enemy scaling 1.95x (tier 4 of 11)"` (er-logic `scaling::region_scaling_toast`),
    and that tier is the player's own sense of how far in they are. Fill spheres are the alternative
    and they are an artifact of how Archipelago filled the seed -- a real number, but not one the
    player can see or feel. Both columns of the comparison read better against the axis the player
    actually experiences.

    The cell carries its count as text as well as a fill bin. A static SVG has no tooltip to fall
    back on and four bins cannot carry a 0-40 range, so the bin makes the shape readable at a glance
    and the number keeps it exact.
    """
    tiers = AUC.ANCIENT_REGULAR_TIER if kind == "reg" else AUC.ANCIENT_SOMBER_TIER
    key = "regular" if kind == "reg" else "somber"
    CELL_W, CELL_H, GAPX, PAD = 44, 17, 16, 26
    L, T, B = 30, 30, 36
    ncol = len(cols[0][1])
    nrow = len(cols)
    widest = max(len(panel[2]) for _slot, panels in cols for panel in panels)
    PW = L + widest * CELL_W + 12
    PH = T + tiers * CELL_H + B
    # The legend below is laid out at fixed offsets, so it is a width floor in its own right --
    # not only the header. (Caught by --selftest on the stub figure, which is narrower than any
    # real one and therefore the only place either floor binds.)
    LEGEND_MIN = PAD + 226 + 58 + len(BINS) * 15 + PAD
    W = max(PAD * 2 + ncol * PW + (ncol - 1) * GAPX,
            header_width([title] + blurb.split(" | "), 12.5, PAD),
            LEGEND_MIN)
    HEAD, LEG = 74, 34
    H = HEAD + LEG + nrow * PH + (nrow - 1) * GAPX + PAD

    s = svg_open(W, H, title, blurb)
    s += text(PAD, 30, title, 18, "ink", mono=False, weight="600")
    for i, line in enumerate(blurb.split(" | ")):
        s += text(PAD, 50 + i * 16, line, 12.5, "ink2", mono=False)

    ly = HEAD + 16
    s += text(PAD, ly, "stones received at that scaling level", 11.5, "ink2", mono=False)
    lx = PAD + 226
    s += ('<rect x="%.1f" y="%.1f" width="13" height="13" rx="2" fill="none" '
          'stroke="var(--grid)"/>\n' % (lx, ly - 10))
    s += text(lx + 18, ly, "none", 11, "muted")
    lx += 58
    for i, (_hi, lab) in enumerate(BINS):
        s += ('<rect x="%.1f" y="%.1f" width="13" height="13" fill="var(--%s-%d)"/>\n'
              % (lx, ly - 10, kind, i + 1))
        s += text(lx + 6.5, ly + 16, lab, 9, "muted", anchor="middle")
        lx += 15

    for ri, (slot, panels) in enumerate(cols):
        for ci, (label, tag, ser) in enumerate(panels):
            ox = PAD + ci * (PW + GAPX)
            oy = HEAD + LEG + ri * (PH + GAPX)
            s += card(ox, oy, PW, PH)
            s += text(ox + 11, oy + 19, "%s  %s" % (slot, label), 11.5, "ink", weight="600")
            s += text(ox + PW - 11, oy + 19, tag, 9.5, "muted", anchor="end")
            s += text(ox + 5, oy + T - 3, "tier", 8, "muted")
            for t in range(tiers, 0, -1):
                y = oy + T + (tiers - t) * CELL_H
                top = ((kind == "reg" and t == AUC.ANCIENT_REGULAR_TIER)
                       or (kind == "som" and t == AUC.ANCIENT_SOMBER_TIER))
                s += text(ox + L - 6, y + CELL_H / 2 + 3.2, "AD" if top else str(t), 9,
                          "ink2" if top else "muted", anchor="end")
                for i, c in enumerate(ser):
                    v = c[key][t]
                    bi = bin_of(v)
                    x = ox + L + i * CELL_W
                    if bi < 0:
                        s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" '
                              'fill="none" stroke="var(--grid)"/>\n'
                              % (x + 1, y + 1, CELL_W - 2, CELL_H - 2))
                    else:
                        s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" '
                              'fill="var(--%s-%d)"/>\n'
                              % (x + 1, y + 1, CELL_W - 2, CELL_H - 2, kind, bi + 1))
                        fill = "var(--ink)" if bi < 2 else "var(--surface)"
                        s += ('<text x="%.1f" y="%.1f" font-size="8.5" text-anchor="middle" '
                              'class="mono" fill="%s">%d</text>\n'
                              % (x + CELL_W / 2, y + CELL_H / 2 + 3, fill, v))
            # x labels: the toast's own two numbers -- the tier within the band, and the multiplier
            axis_y = oy + T + tiers * CELL_H
            s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--axis)"/>\n'
                  % (ox + L, ox + L + len(ser) * CELL_W, axis_y + 3, axis_y + 3))
            for i, c in enumerate(ser):
                cx = ox + L + i * CELL_W + CELL_W / 2
                s += text(cx, axis_y + 16, "tier %d" % c["tier"], 9, "ink2", anchor="middle")
                s += text(cx, axis_y + 27, "%.2fx" % c["tier_mult"], 8.5, "muted", anchor="middle")
            span = ser[0]["tier_span"] if ser else 0
            s += text(ox + PW - 11, oy + PH - 6,
                      "band 0-%d" % span, 8.5, "muted", anchor="end")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


# ---- the flask figures -----------------------------------------------------------------------------
# The flask is the seed's OTHER graded economy, and `features/graded_progression.py` treats it as
# already handled. These two charts are the same pair the stones got -- where the upgrades LAND, and
# what curve that produces -- so the assumption is measured rather than asserted.
FLASK_KINDS = [
    (AUC.CHARGE, "flcharge", "charge (+1 flask use)"),
    (AUC.TEAR, "fltear", "tear (+1 potency)"),
    (AUC.INERT, "flinert", "granted nothing"),
]


def fig_flask_arrivals(cols, out_path):
    """Flask upgrades received per fill sphere, split by what the pickup actually did.

    THE SPHERE AXIS, not the scaling one, because this chart's question is about the multiworld's
    own pacing -- "when in the run does flask power arrive" -- and a sphere is the multiworld's unit
    of when. The scaling tier the player was standing in is printed under each column anyway, so
    both readings are available without drawing the chart twice.

    THE THIRD CLASS IS THE FINDING. A flask pickup is not a tier, it is one of two axes or neither.
    The flask holds exactly 22 upgrades (10 charge steps + 12 tears, one per rung), so a seed with
    more PROG_FLASK copies than that has copies nothing can be done with -- and since the ladder's
    LENGTH is the seed's Golden Seed + Sacred Tear check count, large seeds always do. The loose
    track has the same shape for a different reason: 30 seeds buys every charge step, so the 31st is
    a souvenir. What the stretch changed is WHERE the surplus sits, not how much of it there is.
    """
    BAR, BGAP, PAD, GAPX = 22, 6, 26, 16
    L, T, B, PLOT = 34, 30, 42, 132
    pitch = BAR + BGAP
    ncol, nrow = len(cols[0][1]), len(cols)
    widest = max(len(ser) for _slot, panels in cols for _l, _t, ser in panels)
    PW = max(L + widest * pitch + 14, panel_width(
        [("%s  %s" % (slot, label), 11.5, tag, 9.5)
         for slot, panels in cols for label, tag, _ser in panels]
        + [("", 0, "ends %d charges / %d potency"
            % (ser[-1]["flask_charges"], ser[-1]["flask_potency"]), 8.5)
           for _slot, panels in cols for _l, _t, ser in panels]))
    PH = T + PLOT + B
    ymax = max((sum(d["flask_" + k] for k, _c, _lab in FLASK_KINDS) for _s, panels in cols
                for _l, _t, ser in panels for d in ser), default=0)
    ymax = max(ymax, 1)
    title = "Where flask upgrades land, by fill sphere"
    blurb = ("Each bar is one fill sphere; the stack is what those pickups DID. | "
             "The flask holds 22 upgrades in total, so a seed with more copies than that has "
             "some that grant nothing.")
    LEGEND_MIN = PAD + 250 + len(FLASK_KINDS) * 132 + PAD
    W = max(PAD * 2 + ncol * PW + (ncol - 1) * GAPX,
            header_width([title] + blurb.split(" | "), 12.5, PAD), LEGEND_MIN)
    HEAD, LEG = 74, 30
    H = HEAD + LEG + nrow * PH + (nrow - 1) * GAPX + PAD

    s = svg_open(W, H, title,
                 "One panel per configuration and Elden Ring slot. Bars are fill spheres; segments "
                 "are flask pickups classified by whether they advanced charges, granted a Sacred "
                 "Tear, or fell past both caps and granted nothing.")
    s += text(PAD, 30, title, 18, "ink", mono=False, weight="600")
    for i, line in enumerate(blurb.split(" | ")):
        s += text(PAD, 50 + i * 16, line, 12.5, "ink2", mono=False)

    ly = HEAD + 16
    s += text(PAD, ly, "flask pickups received in that sphere", 11.5, "ink2", mono=False)
    lx = PAD + 250
    for _k, colour, label in FLASK_KINDS:
        s += ('<rect x="%.1f" y="%.1f" width="13" height="13" rx="2" fill="var(--%s)"/>\n'
              % (lx, ly - 10, colour))
        s += text(lx + 19, ly, label, 11, "ink2", mono=False)
        lx += 132

    for ri, (slot, panels) in enumerate(cols):
        for ci, (label, tag, ser) in enumerate(panels):
            ox = PAD + ci * (PW + GAPX)
            oy = HEAD + LEG + ri * (PH + GAPX)
            s += card(ox, oy, PW, PH)
            s += text(ox + 11, oy + 19, "%s  %s" % (slot, label), 11.5, "ink", weight="600")
            s += text(ox + PW - 11, oy + 19, tag, 9.5, "muted", anchor="end")
            base = oy + T + PLOT
            py = lambda v: base - (v / ymax) * PLOT

            for g in (0, .5, 1):
                v = ymax * g
                s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                      % (ox + L, ox + PW - 12, py(v), py(v), "axis" if g == 0 else "grid"))
                s += text(ox + L - 6, py(v) + 3.4, "%d" % round(v), 9, "muted", anchor="end")

            for i, d in enumerate(ser):
                x = ox + L + i * pitch + BGAP / 2
                top = base
                for kind, colour, _lab in FLASK_KINDS:
                    v = d["flask_" + kind]
                    if v <= 0:
                        continue
                    h = (v / ymax) * PLOT
                    # 2px surface gap between stacked segments, so adjacent fills never read as one
                    hh = max(h - 2, 1.5)
                    y = top - h
                    s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" '
                          'fill="var(--%s)"/>\n' % (x, y, BAR, hh, colour))
                    if hh >= 11:
                        fill = "var(--ink)" if kind == AUC.INERT else "var(--surface)"
                        s += ('<text x="%.1f" y="%.1f" font-size="8.5" text-anchor="middle" '
                              'class="mono" fill="%s">%d</text>\n'
                              % (x + BAR / 2, y + hh / 2 + 3, fill, v))
                    top -= h
            # x labels: the sphere, and under it the scaling tier the player stood in
            for i, d in enumerate(ser):
                cx = ox + L + i * pitch + pitch / 2 - BGAP / 2
                s += text(cx, base + 14, str(d["sphere"]), 9, "ink2", anchor="middle")
                s += text(cx, base + 25, "t%d" % d["tier"], 8.5, "muted", anchor="middle")
            s += text(ox + L - 6, base + 14, "sph", 8, "muted", anchor="end")
            last = ser[-1]
            s += text(ox + PW - 11, oy + PH - 6,
                      "ends %d charges / %d potency"
                      % (last["flask_charges"], last["flask_potency"]),
                      8.5, "muted", anchor="end")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


def fig_flask_trajectory(cols, out_path):
    """Flask power against enemy scaling, per fill sphere.

    Charges and potency are ONE entity on two axes, so they share a hue and separate by dash rather
    than taking two categorical slots -- the enemy series keeps the second slot. All three are
    percentages of their own ceiling, so they share one axis; a dual-axis version would invent a
    correlation the data does not carry.
    """
    PW, PH, GAP, PAD = 300, 190, 16, 26
    ncol, nrow = len(cols[0][1]), len(cols)
    title = "Flask power against enemy scaling"
    lines = [title,
             "Charges over their 4-to-14 range, potency over 0-to-12, enemy over its own ceiling.",
             "Flat early means the flask is done climbing while the run is not."]
    LEGEND_MIN = PAD + 2 * 190 + int(len("Enemy scaling (% of ceiling)") * 12 * 0.62) + PAD
    W = max(PAD * 2 + ncol * PW + (ncol - 1) * GAP, LEGEND_MIN, header_width(lines, 12.5, PAD))
    HEAD, LEG = 74, 30
    H = HEAD + LEG + nrow * PH + (nrow - 1) * GAP + PAD

    s = svg_open(W, H, title,
                 "One panel per configuration and Elden Ring slot. Flask charges and potency are "
                 "each a percentage of their own maximum; enemy is the seed's own normalised "
                 "regionSphereTargetRanges.")
    s += text(PAD, 30, lines[0], 18, "ink", mono=False, weight="600")
    s += text(PAD, 50, lines[1], 12.5, "ink2", mono=False)
    s += text(PAD, 66, lines[2], 12.5, "ink2", mono=False)

    ly = HEAD + 14
    for i, (colour, dash, label) in enumerate((
            ("flcharge", "", "Flask charges (of 14)"),
            ("flcharge", ' stroke-dasharray="5 3"', "Flask potency (of 12)"),
            ("fltear", "", "Enemy scaling (% of ceiling)"))):
        lxx = PAD + i * 190
        s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)" stroke-width="3" '
              'stroke-linecap="round"%s/>\n' % (lxx, lxx + 16, ly - 3, ly - 3, colour, dash))
        s += text(lxx + 22, ly, label, 12, "ink2", mono=False)

    for ri, (slot, panels) in enumerate(cols):
        for ci, (label, tag, ser) in enumerate(panels):
            ox = PAD + ci * (PW + GAP)
            oy = HEAD + LEG + ri * (PH + GAP)
            s += card(ox, oy, PW, PH)
            L, R, T, B = 40, 40, 34, 26
            n = len(ser)
            px = lambda i: ox + L + (i / max(n - 1, 1)) * (PW - L - R)
            py = lambda v: oy + T + (1 - v) * (PH - T - B)
            s += text(ox + 13, oy + 20, "%s  %s" % (slot, label), 11.5, "ink", weight="600")
            s += text(ox + PW - 13, oy + 20, tag, 9.5, "muted", anchor="end")
            for g in (0, .25, .5, .75, 1):
                s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                      % (ox + L, ox + PW - R, py(g), py(g), "axis" if g == 0 else "grid"))
                s += text(ox + L - 6, py(g) + 3.4, "%d%%" % round(g * 100), 9, "muted", anchor="end")
            for i in range(n):
                if i % 2 == 0 or i == n - 1:
                    s += text(px(i), oy + PH - 9, str(i), 9, "muted", anchor="middle")
            span = AUC.FLASK_CHARGES_MAX - AUC.FLASK_CHARGES_BASE
            for colour, dash, val, fmt in (
                ("flcharge", "", lambda d: (d["flask_charges"] - AUC.FLASK_CHARGES_BASE) / span,
                 lambda d: "%d" % d["flask_charges"]),
                ("flcharge", ' stroke-dasharray="5 3"',
                 lambda d: d["flask_potency"] / AUC.FLASK_POTENCY_MAX,
                 lambda d: "+%d" % d["flask_potency"]),
                ("fltear", "", lambda d: d["enemy"], lambda d: "%d%%" % round(d["enemy"] * 100)),
            ):
                pts = " ".join("%.1f,%.1f" % (px(i), py(val(d))) for i, d in enumerate(ser))
                s += ('<polyline points="%s" fill="none" stroke="var(--%s)" stroke-width="2" '
                      'stroke-linejoin="round" stroke-linecap="round"%s/>\n' % (pts, colour, dash))
                for i, d in enumerate(ser):
                    s += ('<circle cx="%.1f" cy="%.1f" r="3.1" fill="var(--%s)" '
                          'stroke="var(--surface)" stroke-width="2"/>\n'
                          % (px(i), py(val(d)), colour))
                s += text(px(n - 1) + 7, py(val(ser[-1])) + 3.4, fmt(ser[-1]), 10, "ink2")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


# ---- the across-seeds flask figures ----------------------------------------------------------------
# ONE SEED SHOWS A MECHANISM; IT DOES NOT SHOW A DISTRIBUTION. The paired figures above compare three
# configurations of a single seed, which is the right shape for "does this lever move the curve" and
# the wrong shape for "what does it do to MY seeds". These two take many runs of the same two arms and
# draw the spread.
def _pad(ser, n):
    """Carry the last flask state forward to length `n`.

    Runs have different sphere counts and the panels share one x axis. Carrying forward is not a
    cosmetic fill: the flask state is cumulative and monotone, so after a run's last sphere nothing
    further arrives and the value genuinely stays where it stopped. Padding with zero would draw a
    cliff that does not happen; dropping the short runs would bias the distribution toward long ones.
    """
    return list(ser) + [ser[-1]] * (n - len(ser)) if ser else []


def _median(vals):
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def fig_flask_distribution(arms, out_path):
    """Flask charges and potency across many runs, one faint line per slot plus the median.

    `arms` is [(arm_label, [(slot_label, series), ...]), ...] -- the arms are the columns and the two
    flask axes are the rows, so a reader compares like against like in both directions.

    Spaghetti-plus-median rather than a min/max band: the band hides how many runs sit near its edge,
    and with ten series the individual lines are still legible. The median is drawn in the same hue at
    full weight, so it reads as the summary of those lines rather than as an eleventh one.
    """
    PH, GAP, PAD = 176, 16, 26
    ncol, nrow = len(arms), 2
    nsph = max(len(ser) for _a, runs in arms for _l, ser in runs)
    ROWS = (("flask_charges", "Flask charges", AUC.FLASK_CHARGES_BASE, AUC.FLASK_CHARGES_MAX),
            ("flask_potency", "Flask potency", 0, AUC.FLASK_POTENCY_MAX))
    nruns = max(len(runs) for _a, runs in arms)
    PW = max(330, panel_width([("%s  -  %s" % (rowlabel, arm), 11.5, "%d slots" % len(runs), 9.5)
                               for _k, rowlabel, _lo, _hi in ROWS for arm, runs in arms]))
    title = "Flask progression across %d runs" % nruns
    lines = [title,
             "One faint line per Elden Ring slot; the solid line is the median of those slots.",
             "The dashed rule is the cap on that axis -- the most the game will ever give you."]
    W = max(PAD * 2 + ncol * PW + (ncol - 1) * GAP, header_width(lines, 12.5, PAD))
    HEAD = 74
    H = HEAD + nrow * PH + (nrow - 1) * GAP + PAD + 6

    s = svg_open(W, H, title,
                 "Rows are the flask's two axes, columns are the two configurations. Each faint "
                 "line is one Elden Ring slot of one generated multiworld; the solid line is the "
                 "median across slots. Dashed rules mark each axis's maximum.")
    s += text(PAD, 30, lines[0], 18, "ink", mono=False, weight="600")
    s += text(PAD, 50, lines[1], 12.5, "ink2", mono=False)
    s += text(PAD, 66, lines[2], 12.5, "ink2", mono=False)

    for ri, (key, rowlabel, lo, hi) in enumerate(ROWS):
        for ci, (arm, runs) in enumerate(arms):
            ox = PAD + ci * (PW + GAP)
            oy = HEAD + ri * (PH + GAP)
            s += card(ox, oy, PW, PH)
            L, R, T, B = 42, 46, 32, 26
            px = lambda i: ox + L + (i / max(nsph - 1, 1)) * (PW - L - R)
            py = lambda v: oy + T + (1 - (v - lo) / (hi - lo)) * (PH - T - B)
            s += text(ox + 13, oy + 20, "%s  -  %s" % (rowlabel, arm), 11.5, "ink", weight="600")
            s += text(ox + PW - 13, oy + 20, "%d slots" % len(runs), 9.5, "muted", anchor="end")

            for v in (lo, (lo + hi) / 2, hi):
                s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                      % (ox + L, ox + PW - R, py(v), py(v), "axis" if v == lo else "grid"))
                s += text(ox + L - 6, py(v) + 3.4, "%g" % v, 9, "muted", anchor="end")
            # the cap, called out: reaching it is the point on one arm and never happens on the other
            s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--muted)" '
                  'stroke-dasharray="4 4"/>\n' % (ox + L, ox + PW - R, py(hi), py(hi)))
            for i in range(nsph):
                if i % 2 == 0 or i == nsph - 1:
                    s += text(px(i), oy + PH - 9, str(i), 9, "muted", anchor="middle")
            s += text(ox + L - 6, oy + PH - 9, "sph", 8, "muted", anchor="end")

            padded = [_pad(ser, nsph) for _l, ser in runs]
            for ser in padded:
                pts = " ".join("%.1f,%.1f" % (px(i), py(d[key])) for i, d in enumerate(ser))
                s += ('<polyline points="%s" fill="none" stroke="var(--flcharge)" '
                      'stroke-width="1" stroke-opacity="0.30" stroke-linejoin="round"/>\n' % pts)
            med = [_median([ser[i][key] for ser in padded]) for i in range(nsph)]
            pts = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, v in enumerate(med))
            s += ('<polyline points="%s" fill="none" stroke="var(--flcharge)" stroke-width="2.4" '
                  'stroke-linejoin="round" stroke-linecap="round"/>\n' % pts)
            for i, v in enumerate(med):
                s += ('<circle cx="%.1f" cy="%.1f" r="3" fill="var(--flcharge)" '
                      'stroke="var(--surface)" stroke-width="2"/>\n' % (px(i), py(v)))
            s += text(px(nsph - 1) + 7, py(med[-1]) + 3.4, "med %g" % med[-1], 10, "ink2")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


def fig_flask_yield(arms, out_path):
    """What every flask pickup BOUGHT, one bar per slot, both arms side by side.

    The companion to the distribution above, and the half a curve cannot show. A curve that flattens
    looks the same whether the run stopped receiving pickups or kept receiving ones that do nothing,
    and those are opposite problems with opposite fixes. Bars are ordered by pickup count so the
    relationship between "how many did this slot get" and "how many paid" is the reading direction.

    NB the ladder's STRETCH does not change these totals -- it cannot, the flask only has 22 upgrades
    in it -- so this figure looks the same before and after that change. It is the per-sphere and
    per-run curves that move. Keeping the chart is the point: it is the standing evidence that the
    surplus is the game's ceiling rather than something a schedule left on the table.
    """
    BAR, BGAP, PAD, GAPX = 20, 6, 26, 16
    L, T, B, PLOT = 34, 30, 40, 150
    pitch = BAR + BGAP
    widest = max(len(runs) for _a, runs in arms)
    PH = T + PLOT + B
    tot = lambda ser, k: sum(d["flask_" + k] for d in ser)
    PW = max(L + widest * pitch + 16, panel_width(
        [(arm, 11.5, "%d of %d granted nothing"
          % (sum(tot(ser, AUC.INERT) for _l, ser in runs),
             sum(sum(tot(ser, k) for k, _c, _l in FLASK_KINDS) for _l, ser in runs)), 9.5)
         for arm, runs in arms]))
    # `or 1`: a slot CAN legitimately receive no flask pickup at all (a num_regions draw that seals
    # every seed/tear region -- the case DLC_ONLY_FLASK_COPIES exists for), and an all-zero panel
    # must draw an empty axis rather than divide by zero.
    ymax = max([sum(tot(ser, k) for k, _c, _l in FLASK_KINDS)
                for _a, runs in arms for _l, ser in runs] or [0]) or 1
    title = "What each flask pickup bought"
    blurb = ("One bar per Elden Ring slot, ordered by how many flask pickups that slot received. | "
             "The flask holds only 22 upgrades, so pickups beyond that grant nothing at all.")
    LEGEND_MIN = PAD + 210 + len(FLASK_KINDS) * 132 + PAD
    W = max(PAD * 2 + len(arms) * PW + (len(arms) - 1) * GAPX,
            header_width([title] + blurb.split(" | "), 12.5, PAD), LEGEND_MIN)
    HEAD, LEG = 74, 30
    H = HEAD + LEG + PH + PAD

    s = svg_open(W, H, title,
                 "One panel per configuration. Each bar is one Elden Ring slot of one generated "
                 "multiworld, split by whether its flask pickups advanced charges, granted a Sacred "
                 "Tear, or fell past both caps and granted nothing.")
    s += text(PAD, 30, title, 18, "ink", mono=False, weight="600")
    for i, line in enumerate(blurb.split(" | ")):
        s += text(PAD, 50 + i * 16, line, 12.5, "ink2", mono=False)
    ly = HEAD + 16
    s += text(PAD, ly, "flask pickups received", 11.5, "ink2", mono=False)
    lx = PAD + 210
    for _k, colour, label in FLASK_KINDS:
        s += ('<rect x="%.1f" y="%.1f" width="13" height="13" rx="2" fill="var(--%s)"/>\n'
              % (lx, ly - 10, colour))
        s += text(lx + 19, ly, label, 11, "ink2", mono=False)
        lx += 132

    for ci, (arm, runs) in enumerate(arms):
        ox = PAD + ci * (PW + GAPX)
        oy = HEAD + LEG
        s += card(ox, oy, PW, PH)
        base = oy + T + PLOT
        py = lambda v: base - (v / ymax) * PLOT
        ordered = sorted(runs, key=lambda lr: sum(tot(lr[1], k) for k, _c, _l in FLASK_KINDS))
        waste = sum(tot(ser, AUC.INERT) for _l, ser in runs)
        allp = sum(sum(tot(ser, k) for k, _c, _l in FLASK_KINDS) for _l, ser in runs)
        s += text(ox + 11, oy + 19, arm, 11.5, "ink", weight="600")
        s += text(ox + PW - 11, oy + 19, "%d of %d granted nothing" % (waste, allp),
                  9.5, "muted", anchor="end")
        for g in (0, .5, 1):
            v = ymax * g
            s += ('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="var(--%s)"/>\n'
                  % (ox + L, ox + PW - 14, py(v), py(v), "axis" if g == 0 else "grid"))
            s += text(ox + L - 6, py(v) + 3.4, "%d" % round(v), 9, "muted", anchor="end")
        for i, (label, ser) in enumerate(ordered):
            x = ox + L + i * pitch + BGAP / 2
            top = base
            for kind, colour, _lab in FLASK_KINDS:
                v = tot(ser, kind)
                if v <= 0:
                    continue
                h = (v / ymax) * PLOT
                hh = max(h - 2, 1.5)          # 2px surface gap between stacked segments
                y = top - h
                s += ('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" '
                      'fill="var(--%s)"/>\n' % (x, y, BAR, hh, colour))
                if hh >= 11:
                    fill = "var(--ink)" if kind == AUC.INERT else "var(--surface)"
                    s += ('<text x="%.1f" y="%.1f" font-size="8.5" text-anchor="middle" '
                          'class="mono" fill="%s">%d</text>\n'
                          % (x + BAR / 2, y + hh / 2 + 3, fill, v))
                top -= h
            s += text(x + BAR / 2, base + 14, label, 8, "muted", anchor="middle")
    s += "</svg>\n"
    open(out_path, "w", encoding="utf-8", newline="\n").write(s)
    return out_path


# ---- selftest ------------------------------------------------------------------------------------
def selftest():
    """Geometry and binning, with no Archipelago and no generation."""
    assert bin_of(0) == -1 and bin_of(1) == 0 and bin_of(2) == 0
    assert bin_of(3) == 1 and bin_of(9) == 2 and bin_of(10) == 3 and bin_of(999) == 3

    # the client's band arithmetic, including the rounding trap
    assert tier_for_target(0, 100, 0, 11) == 0
    assert tier_for_target(100, 100, 0, 11) == 11
    assert tier_for_target(50, 100, 0, 11) == 6, "half-away-from-zero, not banker's rounding"
    assert tier_for_target(50, 100, 3, 15) == 9
    assert tier_for_target(999, 100, 0, 11) == 11, "frac clamps at 1"
    assert tier_for_target(50, 0, 2, 9) == 2, "no targets -> the floor"
    assert tier_for_target(50, 100, 9, 3) == 3, "ceiling wins a contradictory band"
    assert band_of({}) == (0, NUM_TIERS - 1)

    play_ids = {"A": [1, 2], "B": [3]}
    # A capped band, so the stub exercises band_of end to end rather than defaulting past it:
    # ceiling 4.844x is ladder rung 11, which is what a real `maximum_enemy_difficulty: auto` seed
    # at num_regions 6 resolves to.
    sd = {"regionSphereTargetRanges": [[1, 1, 0], [2, 2, 5000], [3, 3, 10000]],
          "options": {"completion_scaling_ceiling": 4.844}}
    assert band_of(sd) == (0, 11), band_of(sd)
    e = enemy_by_region(sd, play_ids)
    assert e == {"A": 0.5, "B": 1.0}, e
    assert enemy_by_region({}, play_ids) == {}

    spheres = [["A Lock", "Smithing Stone [1] x3", "Smithing Stone [1] x3"],
               ["B Lock", "Somber Smithing Stone [1]", "Smithing Stone [2]"]]
    ser = series_for(spheres, sd, play_ids, 2)
    assert [d["enemy"] for d in ser] == [0.5, 1.0], ser
    assert ser[0]["regular"][1] == 6, "the ` xN` suffix was dropped"
    assert ser[0]["level"] == 3, ser[0]["level"]
    assert ser[1]["somber_level"] == 1
    # the flask ride-along: the analyzer owns the arithmetic, this asserts it ARRIVES in the series
    assert ser[0]["flask_charge"] == 0 and ser[0]["flask_charges"] == AUC.FLASK_CHARGES_BASE
    fser = series_for([["A Lock", "Golden Seed x2"], ["B Lock", "Sacred Tear"]], sd, play_ids, 2)
    assert [d["flask_charge"] for d in fser] == [2, 0], fser
    assert fser[-1]["flask_charges"] == 6 and fser[-1]["flask_potency"] == 1
    gser = series_for([["A Lock"] + [AUC.PROG_FLASK] * 4], sd, play_ids, 2)
    assert gser[-1]["flask_graded"] and gser[-1]["flask_tear"] == 2, gser[-1]

    # the whole-game supply: shape, and the two ladder tops that are not numbered tiers
    sup = stone_supply()
    assert [r[:3] for r in sup["regular"]][:2] == [(1, 3, "[1]"), (4, 6, "[2]")], sup["regular"][:2]
    assert sup["regular"][-1][:3] == (25, 25, "Anc.Dragon"), sup["regular"][-1]
    assert sup["somber"][-1][:3] == (10, 10, "Anc.Dragon"), sup["somber"][-1]
    assert len(sup["regular"]) == AUC.STONE_TIERS + 1
    assert len(sup["somber"]) == AUC.SOMBER_TIERS + 1
    # bins tile the level axis with no gap and no overlap -- a bar drawn over a level it does not
    # reinforce would overstate that level's supply
    for kind in ("regular", "somber"):
        edge = 0
        for lo, hi, _lab, _s, _b in sup[kind]:
            assert lo == edge + 1, (kind, lo, edge)
            edge = hi
    assert sum(s + b for _l, _h, _n, s, b in sup["regular"]) > 100, "no regular stones counted"
    assert sum(s + b for _l, _h, _n, s, b in sup["somber"]) > 100, "no somber stones counted"

    # every emitted figure must be well-formed XML and carry its own ground
    import xml.dom.minidom, tempfile  # noqa: PLC0415
    cols = [("ER1", [("today", "tiered", ser), ("graded", "ladder", ser)])]
    # the across-seeds arms, deliberately RAGGED: runs have different sphere counts and _pad is the
    # only thing standing between that and a chart that draws a cliff where a run simply ended
    across = [("flasks off", [("A1", ser), ("A2", ser[:1])]),
              ("flasks on", [("B1", ser[:1]), ("B2", ser)])]
    heat = [("ER1", [("today", "tiered", by_scaling_tier(ser)),
                     ("graded", "ladder", by_scaling_tier(ser))])]
    collapsed = by_scaling_tier(ser)
    assert [c["tier"] for c in collapsed] == [6, 11], [c["tier"] for c in collapsed]
    assert collapsed[0]["regular"][1] == 6, "counts must survive the re-bucket"
    # _pad carries the last state forward, because a run that ended is not a run that lost its flask
    assert _pad(ser, 4) == [ser[0], ser[1], ser[1], ser[1]]
    assert _pad([], 3) == [], "an empty run pads to nothing rather than inventing a slot"
    assert _pad(ser, len(ser)) == list(ser), "padding to its own length is identity"
    assert _median([3, 1, 2]) == 2 and _median([4, 1, 2, 3]) == 2.5

    same = by_scaling_tier([dict(ser[0]), dict(ser[0])])
    assert len(same) == 1 and same[0]["regular"][1] == 12, "two spheres at one tier must SUM"
    with tempfile.TemporaryDirectory() as td:
        for fn in (lambda p: fig_trajectory(cols, p),
                   lambda p: fig_heat(heat, p, "reg", "T", "a | b"),
                   lambda p: fig_heat(heat, p, "som", "T", "a | b"),
                   lambda p: fig_flask_arrivals(cols, p),
                   lambda p: fig_flask_trajectory(cols, p),
                   lambda p: fig_flask_distribution(across, p),
                   lambda p: fig_flask_yield(across, p),
                   fig_supply):
            p = os.path.join(td, "x.svg")
            fn(p)
            doc = xml.dom.minidom.parse(p)
            assert doc.documentElement.tagName == "svg"
            body = open(p, encoding="utf-8").read()
            assert 'fill="var(--plane)"' in body, "no explicit ground -- unreadable on a dark host"
            assert "prefers-color-scheme: dark" in body, "no dark palette"
            # NOTHING MAY RUN OFF THE CANVAS. There is no browser in this loop to eyeball the
            # output, so the overflow check that a person would do by looking is done by measuring.
            vb = [float(x) for x in doc.documentElement.getAttribute("viewBox").split()]
            for el in doc.getElementsByTagName("text"):
                if not el.firstChild:
                    continue
                size = float(el.getAttribute("font-size") or 10)
                w = len(el.firstChild.data) * size * 0.62
                x = float(el.getAttribute("x"))
                anchor = el.getAttribute("text-anchor") or "start"
                x0 = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
                assert -1 <= x0 and x0 + w <= vb[2] + 1, (
                    "text runs off the canvas: %r" % el.firstChild.data)
    print("selftest: OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", action="append", default=[], metavar="NAME=ARCHIVE.zip",
                    help="one configuration to plot; repeat, in the order to display")
    ap.add_argument("--ap-dir", help="Archipelago root (needed to read the multidata)")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "measurements"))
    ap.add_argument("--flatten", type=int, default=FLATTEN_DEFAULT)
    ap.add_argument("--supply-only", action="store_true",
                    help="emit only the whole-game stone-supply figure (needs no archive)")
    ap.add_argument("--across", action="append", default=[], metavar="NAME=GLOB",
                    help="one ARM of a many-run comparison: every archive matching GLOB is read and "
                         "its Elden Ring slots pooled. Repeat, in display order. Emits the "
                         "across-seeds flask figures instead of the single-seed ones.")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.supply_only:
        os.makedirs(args.out, exist_ok=True)
        p = fig_supply(os.path.join(args.out, "stone-supply-by-upgrade-level.svg"))
        print("wrote", os.path.relpath(p, ROOT), "(%d bytes)" % os.path.getsize(p))
        return 0
    if args.across and args.label:
        ap.error("--across and --label are different questions (spread across runs vs. three "
                 "configurations of one run); run the tool twice rather than mixing them")
    if not args.label and not args.across:
        ap.error("give at least one --label NAME=ARCHIVE.zip or --across NAME=GLOB, or --selftest")
    if not args.ap_dir:
        ap.error("--ap-dir is required: the multidata carries the enemy-scaling wire and is not "
                 "readable without the Archipelago root on the path")
    sys.path.insert(0, os.path.abspath(args.ap_dir))

    play_ids = scaling_play_ids()

    if args.across:
        arms = []
        for spec in args.across:
            if "=" not in spec:
                ap.error("--across wants NAME=GLOB, got %r" % spec)
            name, pattern = spec.split("=", 1)
            paths = sorted(glob.glob(pattern))
            if not paths:
                ap.error("no archives at %r" % pattern)
            runs = []
            for path in paths:
                received, slot_data = read_archive(path)
                for player, spheres in sorted(received.items()):
                    runs.append((player, series_for(spheres, slot_data.get(player, {}),
                                                    play_ids, args.flatten)))
            # Slot names repeat across archives (the same two yamls each time), so number them --
            # a bar chart with ten bars labelled "Jambo" five times is not a chart of ten runs.
            seen = {}
            labelled = []
            for player, ser in runs:
                seen[player] = seen.get(player, 0) + 1
                labelled.append(("%s%d" % (player[:6], seen[player]), ser))
            arms.append((name, labelled))
        counts = {len(runs) for _n, runs in arms}
        if len(counts) != 1:
            # Unequal arms would make the medians answer different questions.
            sys.exit("the arms hold different numbers of slots (%s) -- they are not comparable."
                     % sorted(counts))
        os.makedirs(args.out, exist_ok=True)
        written = [
            fig_flask_distribution(arms, os.path.join(
                args.out, "flask-progression-across-seeds.svg")),
            fig_flask_yield(arms, os.path.join(
                args.out, "flask-pickup-yield-across-seeds.svg")),
        ]
        for p in written:
            print("wrote", os.path.relpath(p, ROOT), "(%d bytes)" % os.path.getsize(p))
        return 0

    configs = []
    for spec in args.label:
        if "=" not in spec:
            ap.error("--label wants NAME=ARCHIVE.zip, got %r" % spec)
        name, path = spec.split("=", 1)
        matches = sorted(glob.glob(path))
        if not matches:
            ap.error("no archive at %r" % path)
        configs.append((name, matches[0]))

    per_slot = {}
    tags = {}
    for name, path in configs:
        received, slot_data = read_archive(path)
        for player, spheres in received.items():
            ser = series_for(spheres, slot_data.get(player, {}), play_ids, args.flatten)
            per_slot.setdefault(player, []).append((name, ser))
            tags[name] = "ladder" if ser and ser[0]["graded"] else "tiered"

    # The trajectory keeps the SPHERE axis (its enemy series is what makes the scaling axis
    # meaningful in the first place, and plotting it against itself would draw a tautology); the
    # distributions move onto the scaling level the player is actually shown.
    cols = [(slot, [(name, tags[name], ser) for name, ser in entries])
            for slot, entries in sorted(per_slot.items())]
    heat_cols = [(slot, [(name, tags[name], by_scaling_tier(ser)) for name, ser in entries])
                 for slot, entries in sorted(per_slot.items())]
    for slot, panels in heat_cols:
        seqs = {tuple(c["tier"] for c in ser) for _n, _t, ser in panels}
        if len(seqs) != 1:
            # Columns are compared ACROSS configs, so they have to mean the same thing in each. If
            # two configs of one slot walk different tier sequences the panels are not comparable
            # and silently aligning them would invent the comparison.
            sys.exit("slot %s: the configurations do not share a scaling-tier sequence (%s) -- "
                     "these panels cannot be put side by side." % (slot, sorted(seqs)))
    if not cols:
        sys.exit("no Elden Ring slots found in those archives")

    os.makedirs(args.out, exist_ok=True)
    written = [
        fig_trajectory(cols, os.path.join(args.out, "upgrade-curve-trajectory.svg")),
        fig_heat(heat_cols, os.path.join(args.out, "upgrade-curve-regular-stones.svg"), "reg",
                 "Regular smithing stones by enemy scaling level",
                 "Columns are the enemy scaling level the game announces when a region opens "
                 "(\"tier 4 of 11, 1.95x\"); rows are stone tier. | A tier-blind seed scatters "
                 "every stone tier across every scaling level; a paced one reads as a diagonal."),
        fig_heat(heat_cols, os.path.join(args.out, "upgrade-curve-somber-stones.svg"), "som",
                 "Somber smithing stones by enemy scaling level",
                 "Somber costs one stone per level and the tier IS the level, so a missing tier is "
                 "a wall rather than thin supply. | That makes the diagonal matter more here than "
                 "on the regular track."),
    ]
    written += [
        # THE SPHERE AXIS for both flask figures, unlike the stone heatmaps. The question here is
        # the multiworld's pacing -- when in the run does flask power arrive -- and the sphere is
        # the multiworld's own unit of when; the scaling tier is printed under each column anyway.
        fig_flask_arrivals(cols, os.path.join(args.out, "flask-arrivals-by-sphere.svg")),
        fig_flask_trajectory(cols, os.path.join(args.out, "flask-curve-trajectory.svg")),
    ]
    written.append(fig_supply(os.path.join(args.out, "stone-supply-by-upgrade-level.svg")))
    for p in written:
        print("wrote", os.path.relpath(p, ROOT), "(%d bytes)" % os.path.getsize(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
