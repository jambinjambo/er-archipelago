"""SPEC-PARITY Phase 7 -- progressive items (COMPLETE).

Collapses a family of fungible/ordered upgrade pickups into a single "Progressive X" AP item whose
Kth received copy grants tier K, via the client's existing `progressiveGrants` contract. The client
already understands `progressiveGrants = {item_name: [{"goods": FullID, "flags": [...]}, ...]}`: it
tracks how many copies of `item_name` it has received and, on the Kth, grants the goods (and sets
any flags) at ladder index K-1. Copies past the ladder length overflow to a Lord's Rune client-side
(same pipeline the matt-derived apworld uses); we do not need to model overflow here.

Matt-free: every good id below is a *vanilla* EquipParamGoods id (game data, re-expressed here from
the vanilla item tables -- NOT any curated/location set). GOODS FullID = good_id | _GOODS_NIBBLE
(0x40000000), matching core's _AP_IDS_TO_ITEM_IDS convention.

Ships three independent toggles (progressive_flasks default ON; the others default OFF):
  - Progressive Flasks -> ONE item, "Progressive Flask Upgrade", replacing every Golden Seed and
    Sacred Tear check one-for-one. The flask is a HYBRID across two INDEPENDENT axes, and it rides
    BOTH wires at once (intentional, non-overlapping):
      * CHARGES = a reconciled LEVELED STATE (client-side, contract.flaskLadder). The Kth copy moves
        the flask charge target to flaskLadder[K-1]["charges"]; the client reconciles the live flask
        directly (a direct write to PlayerGameData.max_hp_flask -- CONFIRMED SAFE). A leveled charge
        target has no spend to heal, so it cannot trigger the re-grant CTD class.
      * POTENCY = GRANTED SACRED TEARS via progressiveGrants (the proven consumed/ledgered path). The
        Kth copy grants ONE consumed Sacred Tear (good 10020), and the player upgrades flask potency
        at a Site of Grace the vanilla way -- which correctly updates EVERY flask mirror (the
        inventory entry, the equipped/quickslot reference, AND the global GaItem). One Sacred Tear per
        copy => one ledger entry per stream index => no batching problem.
    WHY THE SPLIT: an earlier build tried to raise potency by an in-place inventory item-id swap
    (base+level*2). That CTD'd on death -- ER mirrors the flask tier across the inventory entry, the
    equipped/quickslot reference, AND the global GaItem, and death's flask-refill crashed on the
    half-updated state (playtest 2026-07-19). Granting a Sacred Tear and letting the player upgrade at
    a grace touches every mirror safely, exactly as vanilla does. (An even earlier build shipped the
    tears OWNED rather than consumed; reconcile.rs self-healed a SPENT tear and re-granted unbounded
    until the flask ran past its cap and CTD'd, playtest 2026-07-12 -- hence consumed=True is
    REQUIRED.) The charge axis's "later pickups buy less" deceleration is baked into the escalating
    charge-step weights; the potency axis is a flat +1 tear per copy. The ladder's LENGTH follows the
    kept seed/tear checks (num_regions / DLC scale it for free); when NONE are kept (dlc_only) a fixed
    12 copies are injected -- enough for both charges (max 14) and potency (max 12, one tear each) to
    fully max by copy 12. PROG_FLASK stays a pool item and the Golden Seed / Sacred Tear checks still
    SUBSTITUTE to it; the flask now appears in BOTH progressiveGrants (potency tears) and flaskLadder
    (charges) at once.
  - Progressive Stonesword Keys -> "Progressive Stonesword Key" (good 8000). Each copy grants one
    Stonesword Key; the player spends it on an Imp Statue seal.
  - Progressive Stone Bells -> "Progressive Smithing-Stone Miner's Bell Bearing" (4 tiers) and
    "Progressive Somberstone Miner's Bell Bearing" (5 tiers). Ported from the matt-based apworld
    (SPEC-PARITY: ProgressiveItems stone_bells). The Kth copy sets the Twin Maiden ShopLineupParam
    stock flags for that rung AND its shared release flag -- setting both halves is the shop unlock,
    with no hand-in and no physical bearing grant. Granting both representations makes the game
    reject the bearing as already handed in (live playtest 2026-08-17, #804).
    Flags verified against vanilla_er/ShopLineupParam.csv (Twin Maiden shop 1018xx: item 10100 ->
    stock 280080, tier release 11109751, etc.). 1 copy of each is forced to sphere 0 so the
    upgrade ramp opens at the start; the rest distribute normally. Copies past the last tier are
    silent no-ops client-side (the k < tiers guard). The VANILLA bell bearings SUBSTITUTE to the
    progressive item exactly as the flask checks do (vanilla_substitutions), so the pool cannot hold
    both ladders at once -- before #539 it held BOTH, and a single vanilla `Somberstone Miner's Bell
    Bearing [5]` handed the player the top rung on pickup. That does not degrade the ladder, it
    BYPASSES it (boblerrr, live playtest 2026-08-10).

WHY THE BELLS KEEP A COPY FLOOR AND THE FLASK DOES NOT (the _POOL_COUNTS ruling, #539)
--------------------------------------------------------------------------------------
PROG_FLASK deliberately has no _POOL_COUNTS entry: every copy comes from substitution, which is what
makes it count-exact and lets the ladder length follow the checks the seed actually kept. #539
proposed the same for the bells -- drop their _POOL_COUNTS and let substitution be the only source.
REJECTED, for two reasons the vanilla data makes unavoidable:

  * THE SOMBER LADDER WOULD BE PERMANENTLY ONE RUNG SHORT. `Somberstone Miner's Bell Bearing [1]`
    does not exist in the vanilla item data (it is not a looted item), so the whole game holds only
    FOUR somber bell checks against FIVE somber rungs. Pure substitution therefore caps the somber
    ladder at 4 copies in EVERY seed, and rung 5 -- the Somber Smithing Stone [9] shop unlock, the
    endgame material -- becomes unreachable. The flask has no analogue: its ladder LENGTH is a design
    choice that bends to the copy count, the bells' is fixed by _BELL_GRANTS and cannot bend.
  * A SEED CAN KEEP ZERO BELL CHECKS. The eight checks live in Altus, Liurnia, Mountaintops and Farum
    Azula. A num_regions seed that keeps none of those -- or dlc_only, or item_shuffle off, where
    core never walks the vanilla items at all -- would get a ZERO-copy ladder: the feature silently
    inert, and generate_early asking AP to bias a sphere-0 copy that does not exist. This is exactly
    the case flask_inject_count / DLC_ONLY_FLASK_COPIES exist for on the flask side.

So the bells use the flask's OTHER half. Substitution supplies the copies (count-neutral, and it is
what removes the vanilla bearings from the pool), and create_items TOPS UP to the ladder length --
bell_inject_count. Total copies == len(_BELL_GRANTS[name]) in every seed, 4 smithing and 5 somber, so
every rung is reachable and no copy is a dud. That also retires the old fixed count's 5th smithing
copy, which had no rung to grant.

THE SECOND SOURCE. Substitution alone does NOT empty the pool of vanilla bearings: features/
presence_floor.py injects one copy of every roster item whose home region was not kept, and the bell
bearings are on that roster -- which is why all 8 showed up even in a 4-region seed. With this toggle
on, the progressive ladder IS the guaranteed supply (the floor above holds in every seed, including
the dlc_only case presence_floor was written for), so that feature drops the bell bearings from its
roster. Both edits are required; either one alone leaves the bypass in place.

Every progressive copy is `useful`, NEVER progression -- Region Locks stay the sole progression gate,
so winnability is unaffected. create_items adds a fixed count of copies per active item; core's
count-neutral fill (slots = total_locations - len(pool)) means each copy displaces one filler/Rune
tail item, keeping the pool count-exact.
"""
import itertools
import logging
from typing import Any, Dict, List

from BaseClasses import ItemClassification
from Options import OptionError, Toggle
from ..registry import Feature, register
from .. import contract

try:  # the flask leveled-ladder length follows the kept Golden Seed / Sacred Tear checks
    from ..data import HUB, LOCATIONS
except Exception:
    HUB, LOCATIONS = "Roundtable Hold", {}
try:
    from ..item_ids import ITEM_CATALOG, LOCATION_ITEM
except Exception:  # pre-regen: no catalog -> the stone ladders resolve empty and say so loudly
    ITEM_CATALOG, LOCATION_ITEM = {}, {}

_GOODS_NIBBLE = 0x40000000  # ER FullID category nibble for GOODS (mirrors core._GOODS_NIBBLE)
_GOOD_SACRED_TEAR = 10020    # vanilla EquipParamGoods id for Sacred Tear (FullID 0x40000000|10020 =
                             # 1073751844, matches item_ids.py). The flask POTENCY axis grants these
                             # as consumed goods (the player upgrades potency at a grace the vanilla
                             # way, which updates every flask mirror -- see the module docstring).

# ---- progressive item names -------------------------------------------------------------------
PROG_FLASK = "Progressive Flask Upgrade"
PROG_STONESWORD_KEY = "Progressive Stonesword Key"
PROG_SMITHING_BELL = "Progressive Smithing-Stone Miner's Bell Bearing"
PROG_SOMBER_BELL = "Progressive Somberstone Miner's Bell Bearing"
# graded_progression (2026-08-28). The LOOSE stone economy as two ladders -- see the stone-ladder
# section below for why the tier has to be a receive-count and not a placement.
#
# 🛑 BOTH NAMES CONTAIN THE SUBSTRING "Smithing Stone", AND THAT IS LOAD-BEARING.
# `filler_curation._ECONOMY_SUBSTR` protects the placed upgrade economy from junk seizure by
# substring, so these inherit that protection for free and core's extras-sort ranks a substituted
# copy PROTECTED (rank 1) exactly as it ranks the tiered stone it replaced. Rename either one out of
# that substring and the filler tail may displace the ladder it is meant to be pacing.
PROG_SMITHING_STONE = "Progressive Smithing Stone"
PROG_SOMBER_STONE = "Progressive Somber Smithing Stone"

# The two un-numbered stones that finish each track: +24 -> +25 for standard weapons, +9 -> +10 for
# somber. They are ladder RUNGS, not loose items -- see the equivalence note on SOMBER_TO_REGULAR
# for why leaving them out left the two tracks topping out at different power.
ANCIENT_REGULAR = "Ancient Dragon Smithing Stone"
ANCIENT_SOMBER = "Somber Ancient Dragon Smithing Stone"

# ---- vanilla goods ladders (RE-EXPRESSED vanilla EquipParamGoods ids; matt-free) --------------
# Fungible flasks repeat the same good up to the vanilla max; the stonesword key repeats good 8000.
# Ladder length = the meaningful cap (client overflows extra copies to a Lord's Rune).
_GOODS_LADDERS: Dict[str, List[int]] = {
    PROG_STONESWORD_KEY: [8000] * 10,  # Stonesword Key; 10 copies = a generous supply
}

# ---- unified flask LEVELED ladder (CHARGES axis) ----------------------------------------------
# The flask is a HYBRID. Its CHARGES axis is a reconciled LEVELED STATE (client-side): the Kth copy of
# PROG_FLASK moves the player's flask charge target to flaskLadder[K-1]["charges"], and the client
# reconciles the live flask with a direct write (PlayerGameData.max_hp_flask -- CONFIRMED SAFE). A
# leveled charge target has no spend to heal, so it cannot trigger the re-grant CTD class.
#
# Its POTENCY axis is NOT set from this ladder on the client -- it is GRANTED as consumed Sacred Tears
# via progressiveGrants (see _grant_ladder(PROG_FLASK) and the module docstring), because the in-place
# potency item-id swap CTD'd on death (ER mirrors flask tier across the inventory entry, the equipped/
# quickslot reference, AND the global GaItem; death's flask-refill crashed on the half-updated state,
# playtest 2026-07-19). Granting a tear and upgrading at a grace touches every mirror the vanilla way.
# The "potency" field below is therefore DOCUMENTATION ONLY (kept accurate to the even-copy
# schedule); the client takes potency from the ledgered tears, not this ladder.
#
# The deceleration the old design inherited from the vanilla cost table is baked into the ladder's
# escalating charge-step weights below.
#
# The vanilla per-level cost tables are RETAINED as documented vanilla data + the single-source datum
# tests/test_gf_progressive_flasks.py::test_cost_tables_match_tools guards against tools/upgrade_costs.py
# drift. (tools/ is a script package: sys.path hacks, no __init__, not guaranteed to ship in the
# apworld zip -- importing it at runtime would be a load-bearing fragility for a table that ~never
# changes.)
FLASK_CHARGE_SEED_COST: List[int] = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]   # vanilla seeds per charge level -> 30
FLASK_POTENCY_TEAR_COST: List[int] = [1] * 12                        # vanilla tears per potency level -> 12

# Leveled-ladder bounds (the wire contract, contract.flaskLadder): charges climb 2 -> 14 (12 steps),
# potency 0 -> 12 (12 steps); the last rung is (14, 12). NB the wire spec (2->14, 12 steps) is followed
# literally; vanilla's own base is 4 charges + 10 seed-bought steps (tools/upgrade_costs FLASK_BASE_
# CHARGES) -- see the deliverable note. Charge steps carry ESCALATING weights so the ladder rises fast
# early and slow late (the inherited deceleration). The POTENCY axis climbs a flat +1 PER RUNG (capped
# at 12): potency is granted as one consumed Sacred Tear per copy, so a rung MUST NOT advance potency
# by more than 1 (a +2 rung would need 2 tears at one copy = 2 ledger entries at one stream index = the
# batching the consumed-goods ledger forbids). See flask_ladder() -- potency is computed directly as
# min(rung//2, 12), NOT distributed through _cum_levels like charges.
FLASK_CHARGES_BASE = 4
FLASK_CHARGES_MAX = 14
FLASK_POTENCY_MAX = 12
_CHARGE_STEP_WEIGHTS: List[int] = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6]   # 12 steps (2 -> 14), escalating
_POTENCY_STEP_WEIGHTS: List[int] = list(FLASK_POTENCY_TEAR_COST)          # 12 flat steps; documentation only

# When NO Golden Seed / Sacred Tear check is kept (dlc_only, or a num_regions seed that seals every
# flask region), there are no substituted PROG_FLASK copies -- so inject a fixed count of copies and
# build a ladder that maxes by the last rung. 12 copies: one Sacred Tear per copy needs 12 copies to
# reach potency 12 under an alternating schedule. Twenty-four copies fully max both axes.
DLC_ONLY_FLASK_COPIES = 24


def _flasks_on(world) -> bool:
    # graded_progression OVERRIDES this toggle rather than requiring it (2026-08-28). Its whole
    # premise is that every power track is paced, and 43 interchangeable Golden Seeds is the flask
    # half of the jagged curve it exists to fix. Rejecting the combination instead would reject the
    # shipped template, because ProgressiveFlasks.default is 1 and AP cannot tell an explicit `false`
    # from a filled-in default -- see features/graded_progression.py's OVERRIDE, NOT REJECT note.
    if _stones_on(world):
        return True
    o = getattr(world.options, "progressive_flasks", None)
    return bool(o is not None and o.value)


def _shuffle_on(world) -> bool:
    """item_shuffle -- core only walks the vanilla items (and therefore only SUBSTITUTES) when it is
    on. A copy count derived from the walk has to agree with that or it will credit substituted
    copies that core never made."""
    o = getattr(world.options, "item_shuffle", None)
    return bool(o is not None and o.value)


def _kept_check_count(world, regions, names) -> int:
    """How many of `regions`' locations vanilla-hold one of `names` this seed. Mirrors core's extras
    source (LOCATION_ITEM) and honours the DLC-off exclusion -- so it equals the progressive copies
    core.vanilla_substitutions adds for those regions. ONE walk, shared by the flask and the bells:
    a second copy of it would be a second chance to disagree with core about what "kept" means."""
    if not LOCATION_ITEM:
        return 0
    excl = getattr(world, "gf_dlc_excluded", frozenset())
    name_to_id = getattr(world, "item_name_to_id", {})
    names = frozenset(names)
    n = 0
    for rn in regions:
        for (_name, ap_id, _flag) in LOCATIONS.get(rn, []):
            nm = LOCATION_ITEM.get(ap_id)
            if nm in names and nm in name_to_id and nm not in excl:
                n += 1
    return n


def _flask_check_count(world, regions) -> int:
    """How many of `regions`' locations vanilla-hold a Golden Seed / Sacred Tear this seed. Mirrors
    core's extras source (LOCATION_ITEM) and honours the DLC-off exclusion -- so it equals the
    PROG_FLASK copies core.vanilla_substitutions adds for those regions."""
    return _kept_check_count(world, regions, VANILLA_FLASK_ITEMS)


def _substituted_flask_copies(world) -> int:
    """PROG_FLASK copies core.vanilla_substitutions puts in the pool == every kept flask check,
    INCLUDING the HUB. (Roundtable Hold always holds one Golden Seed, so this is >= 1 whenever
    item_shuffle is on -- which is why 'dlc_only keeps zero flask checks' is detected on the kept
    REGIONS, not the total: see flask_copy_count.)"""
    kept = list(world._kept()) if hasattr(world, "_kept") else []
    return _flask_check_count(world, [HUB] + kept)


def _region_flask_copies(world) -> int:
    """Kept flask checks EXCLUDING the always-kept HUB. 0 => no kept REGION has a seed/tear check
    (dlc_only, or a num_regions seed that seals every flask region) -- the trigger for the fixed
    ladder floor. (The HUB's lone Golden Seed is not enough to build a real flask curve on its own.)"""
    kept = list(world._kept()) if hasattr(world, "_kept") else []
    return _flask_check_count(world, list(kept))


def flask_copy_count(world) -> int:
    """The number of PROG_FLASK copies this seed will actually have == the flaskLadder length. When a
    kept region has flask checks: every substituted copy (HUB + regions). When none does (dlc_only):
    a fixed floor (DLC_ONLY_FLASK_COPIES) so the mode still has a real flask curve. 0 when flasks
    off."""
    if not _flasks_on(world):
        return 0
    if _region_flask_copies(world) > 0:
        return _substituted_flask_copies(world)
    return DLC_ONLY_FLASK_COPIES


def flask_inject_count(world) -> int:
    """PROG_FLASK copies THIS feature injects (create_items). Normal case: 0 -- the copies come from
    core.vanilla_substitutions of the kept seed/tear checks. dlc_only-style (no kept region has a flask
    check): top the pool up to DLC_ONLY_FLASK_COPIES, accounting for the HUB's lone substituted copy so
    the pool holds EXACTLY flask_copy_count() PROG_FLASK (ladder length == actual copies)."""
    if not _flasks_on(world):
        return 0
    return max(0, flask_copy_count(world) - _substituted_flask_copies(world))


def _cum_levels(n_rungs: int, weights: List[int]) -> List[int]:
    """Cumulative level after each of `n_rungs` rungs, distributing len(weights) unit level-ups across
    the rungs proportionally to cumulative WEIGHT (heavier/later steps take more rungs). Monotonic
    non-decreasing; reaches len(weights) EXACTLY at the last rung (progress is scaled to hit the final
    threshold only at rung n_rungs). n_rungs < len(weights) => some rungs advance multiple levels."""
    thresholds = list(itertools.accumulate(weights))   # thresholds[j] = cost to REACH level j+1
    total = thresholds[-1]
    out: List[int] = []
    for r in range(1, n_rungs + 1):
        spent = total * r / n_rungs
        lvl = sum(1 for t in thresholds if t <= spent + 1e-9)   # +eps so the last rung clears the top
        out.append(lvl)
    return out


def flask_ladder(world) -> List[Dict[str, int]]:
    """The flaskLadder wire: [{"charges", "potency"}, ...], one rung per PROG_FLASK copy. Monotonic
    non-decreasing. CHARGES reaches FLASK_CHARGES_MAX at the last rung (the client reconciles the flask
    charge target via a direct write). POTENCY climbs a flat +1 per rung capped at FLASK_POTENCY_MAX
    (= min(rung//2, 12)) and is DOCUMENTATION ONLY -- the client sets potency from ledgered Sacred
    Tears on even copies. With the normal >=24 copies (full seed, or dlc_only's fixed 24) the last
    rung is (FLASK_CHARGES_MAX, FLASK_POTENCY_MAX); with fewer than 24
    copies potency honestly tops out below 12 (fewer tears granted). Deterministic (closed-form;
    world.random not needed) and cached on the world so create_items and slot_data agree."""
    cached = getattr(world, "gf_flask_ladder", None)
    if cached is not None:
        return cached
    n = flask_copy_count(world)
    if n <= 0:
        world.gf_flask_ladder = []
        return []
    # Alternating ruling (#798): odd copies advance CHARGES, even copies grant +1 POTENCY. Derive
    # both cumulative targets from the copy ordinal so reconnect/retry cannot shift the sequence.
    # The first charge target is 5, one above the vanilla starting allocation of 4; it can therefore
    # never be silently absorbed by a fresh character. Each later scheduled charge advances one more
    # observable step until the vanilla cap. Potency is one consumed Sacred Tear on each even copy.
    charge_copies = (n + 1) // 2
    charge_targets = [min(FLASK_CHARGES_BASE + ordinal, FLASK_CHARGES_MAX)
                      for ordinal in range(1, charge_copies + 1)]
    ladder = []
    for copy in range(1, n + 1):
        charges = charge_targets[(copy - 1) // 2]
        potency = min(copy // 2, FLASK_POTENCY_MAX)
        ladder.append({"charges": charges, "potency": potency})
    world.gf_flask_ladder = ladder
    return ladder


# Vanilla pool items the unified flask ladder REPLACES, one-for-one, when progressive_flasks is on.
# core.create_items substitutes these names as it reads each check's vanilla item, so the copy count
# is exactly the number of seed/tear checks the seed actually kept -- count-neutral, and it scales
# with num_regions / DLC for free (a 4-region seed simply has fewer rungs available, which is the
# honest outcome, not a bug). This is why PROG_FLASK has no _POOL_COUNTS entry.
VANILLA_FLASK_ITEMS = ("Golden Seed", "Sacred Tear")

# Vanilla pool items the progressive stone-bell ladders REPLACE, one-for-one, when
# progressive_stone_bells is on (#539). These are ALL the bell bearings the vanilla item data has:
# Smithing-Stone [1]-[4] and Somberstone [1]-[5].
#
# ⭐⭐⭐ 2026-08-13 (#191): NINE, not eight. This list said eight because
# `Somberstone Miner's Bell Bearing [1]` was "absent from the vanilla name catalog (it is not a
# looted item)". That premise was WRONG, and it was wrong for a reason nothing here could see: the
# catalog is CHECK-derived, the bearing hangs off flag 520670 as lot 20673 -- a SIBLING of a
# shared-flag family -- and until the co-check allowlist widened, siblings were never projected. It
# is looted, it is a real catalog item, and with the ladder on a vanilla copy of it was therefore
# eligible for the pool: the top-rung-bypass leak (#539) this substitution exists to stop, hiding
# behind a data gap. Caught by test_gf_progressive's VANILLA_BELL_ITEMS-vs-catalog gate, which is
# exactly the "a data rename shrinks the substitution LOUDLY" guard below doing its job in reverse.
#
# 🛑 CONSEQUENCE NOT ACTED ON HERE: the module docstring justifies the somber ladder's INJECTED
# FLOOR on this same "Somberstone [1] cannot be found" premise. That premise is now dead, so the
# injected floor may be redundant -- but removing it changes what a seed grants, so it is a ruling,
# not a cleanup. Left in place deliberately; see #191.
# test_gf_progressive asserts every name here resolves against the real item catalog, so a data
# rename shrinks the substitution LOUDLY rather than silently putting the vanilla ladder back.
VANILLA_BELL_ITEMS: Dict[str, str] = dict(
    [("Smithing-Stone Miner's Bell Bearing [%d]" % i, PROG_SMITHING_BELL) for i in range(1, 5)]
    + [("Somberstone Miner's Bell Bearing [%d]" % i, PROG_SOMBER_BELL) for i in range(1, 6)]
)


def vanilla_substitutions(world) -> Dict[str, str]:
    """{vanilla item name -> progressive item name} for core's item_shuffle pool. Empty when every
    substituting toggle is off.

    TWO ladders substitute here, and both must, for the same reason: while a vanilla pickup that
    grants a ladder's TOP RUNG outright is still in the pool, the ladder is not paced, it is bypassed
    (#539). core.create_items reads this at the single place vanilla items are rewritten, so a name
    added here leaves the pool everywhere by construction -- but only where core walks the vanilla
    items at all, which is why presence_floor needs its own guard (see the module docstring)."""
    subs: Dict[str, str] = {}
    # 🛑 THE PREDICATE, NOT THE RAW OPTION -- the same door presence_floor had to close for the
    # bells (#539), found open here on 2026-08-29 by reading a graded archive. `_flasks_on` is True
    # whenever graded_progression is on, so flask_copy_count/flask_ladder/_grant_ladder all built a
    # full ladder; this line asked the yaml instead, so a graded seed whose yaml said
    # `progressive_flasks: false` shipped a 19-rung flaskLadder with ZERO copies in the pool to
    # advance it. Not a crash -- the vanilla Golden Seeds still work vanilla-style -- which is
    # exactly why it survived: the feature went silently dark and the seed looked fine.
    if _flasks_on(world):
        subs.update({n: PROG_FLASK for n in VANILLA_FLASK_ITEMS})
    if _bells_on(world):
        subs.update(VANILLA_BELL_ITEMS)
    if _stones_on(world):
        # THREE ladders substitute here now, for the one reason stated above: a tiered stone left in
        # the pool beside the ladder is a rung handed over out of order. This is also the half that
        # takes the LOOSE stones out -- filler_budget._draw_stones takes the reserved ones.
        subs.update(VANILLA_STONE_ITEMS)
    return subs

# ---- progressive stone-bell grant ladders (shop-unlock flags only) ----------------------------
# Setting the flags IS the shop unlock (no hand-over to the Twin Maidens needed). Do not also grant
# the corresponding physical bearing: once its shop flags are set, Elden Ring treats the bearing as
# already handed in and refuses it as over-capacity (#804).
#
# EACH RUNG NEEDS BOTH PARAM GATES. ShopLineupParam.eventFlag_forStock unlocks the individual rows;
# eventFlag_forRelease makes that bearing's shelf EXIST in the menu. The first implementation set
# only the stock flags, so receipts reconciled forever without the stones appearing. Values below
# are read from vanilla_er/ShopLineupParam.csv block 1018: two stock flags + one shared release flag
# per tier, except Somber [5], which has one stock row.
_BELL_GRANTS: Dict[str, List[Dict[str, Any]]] = {
    PROG_SMITHING_BELL: [
        {"flags": [280080, 280090, 11109751]},  # Smithing Stone [1],[2]
        {"flags": [280110, 280120, 11109752]},  # Smithing Stone [3],[4]
        {"flags": [280140, 280150, 11109753]},  # Smithing Stone [5],[6]
        {"flags": [280160, 280170, 11109754]},  # Smithing Stone [7],[8]
    ],
    PROG_SOMBER_BELL: [
        {"flags": [280180, 280190, 11109755]},  # Somber [1],[2]
        {"flags": [280200, 280210, 11109756]},  # Somber [3],[4]
        {"flags": [280230, 280240, 11109757]},  # Somber [5],[6]
        {"flags": [280250, 280260, 11109758]},  # Somber [7],[8]
        {"flags": [280280, 11109759]},          # Somber [9]
    ],
}

# How many copies of each progressive item to place in the pool when its toggle is on. Bounded well
# under the ladder length so copies land inside the meaningful ladder (no overflow spam), and small
# enough to stay comfortably count-neutral against the filler tail.
_POOL_COUNTS: Dict[str, int] = {
    # PROG_FLASK is deliberately absent: its copies come from substituting the seed/tear checks the
    # seed actually kept (see vanilla_substitutions), not from a fixed count. The two STONE BELLS
    # left this table in #539 for the same reason -- they substitute now, so a fixed count would ADD
    # copies on top of the substituted ones. They are not pure-substitution either: bell_inject_count
    # tops them up to the ladder length, because the vanilla data cannot supply the somber ladder's
    # 5th rung and a seed can keep zero bell checks. See the module docstring for the full ruling.
    PROG_STONESWORD_KEY: 6,
}


def _bells_on(world) -> bool:
    # graded_progression FORCES THIS ON, and this is the load-bearing one. A vanilla Miner's Bell
    # Bearing is a permanent unlimited shop unlock for its whole tier band, so one early bearing
    # sells the player past the stone ladder entirely -- the ladder would not be degraded, it would
    # be BYPASSED, which is the #539 finding this module's docstring already records for the bells'
    # own vanilla copies. A graded seed with loose bearings in it is not a weaker graded seed; it is
    # an ungraded one wearing the option's name.
    #
    # 🛑 features/presence_floor.py MUST ASK THIS FUNCTION, not the raw option. It injects one copy
    # of every roster bearing whose home region was not kept, so reading `progressive_stone_bells`
    # directly there would re-open the bypass for exactly the bearings substitution never saw --
    # the "both edits are required; either one alone leaves the bypass in place" note above, again.
    if _stones_on(world):
        return True
    o = getattr(world.options, "progressive_stone_bells", None)
    return bool(o is not None and o.value)


def bell_ladder_len(name: str) -> int:
    """Rungs in this bell's grant ladder -- 4 smithing, 5 somber. _BELL_GRANTS is the ONLY definition
    of how many copies are meaningful, so it is also the definition of how many copies to have."""
    return len(_BELL_GRANTS.get(name, ()))


def _substituted_bell_copies(world, name: str) -> int:
    """Copies of `name` core.vanilla_substitutions puts in the pool == every kept check whose vanilla
    item is one of that bell's vanilla bearings (HUB included, exactly as the flask counts it). Zero
    when item_shuffle is off: core never walks the vanilla items, so it substitutes nothing."""
    if not _bells_on(world) or not _shuffle_on(world):
        return 0
    kept = list(world._kept()) if hasattr(world, "_kept") else []
    names = [v for v, prog in VANILLA_BELL_ITEMS.items() if prog == name]
    return _kept_check_count(world, [HUB] + kept, names)


def bell_copy_count(world, name: str) -> int:
    """The number of copies of `name` this seed will actually have == the ladder length, in every
    seed: substitution supplies at most 4 (the vanilla data holds only 4 checks per bell) and
    create_items tops up the rest. max(), not a bare ladder length, so a future data regen that adds
    a bell check cannot make this UNDERSTATE the pool and desync the count from what core built."""
    if not _bells_on(world):
        return 0
    return max(bell_ladder_len(name), _substituted_bell_copies(world, name))


def bell_inject_count(world, name: str) -> int:
    """Copies of `name` THIS feature injects (create_items): the top-up between what substitution
    supplied and the ladder length. Always >0 for the somber bell (4 vanilla checks, 5 rungs) and in
    any seed that kept few bell checks; count-neutral either way, because core sizes the filler tail
    as `total_locations - len(pool)` AFTER this runs."""
    return max(0, bell_copy_count(world, name) - _substituted_bell_copies(world, name))

# Copies of each progressive stone bell to FORCE into sphere 0 (no-item-reachable) via early_items,
# so the upgrade ladder has a first rung at the start. Because the item is progressive, 1 early copy
# guarantees an early first tier; the remaining pool copies distribute normally. Soft/capped by AP
# (bounded by pool availability + sphere-0 size), so it never fails gen.
_BELL_EARLY_COUNT: Dict[str, int] = {
    PROG_SMITHING_BELL: 1,
    PROG_SOMBER_BELL: 1,
}

# ---- THE LOOSE STONE LADDERS (graded_progression, 2026-08-28) ----------------------------------
# The bells above unlock the SHOP; these pace the stones the seed actually places. Both halves are
# needed or neither works: a bell rung sells a whole tier band at will, and a loose `Smithing Stone
# [8]` in sphere 0 skips the ladder outright. features/graded_progression.py carries the full
# argument; the short version is that TIER IS RECEIVE-COUNT here, because there is no depth axis at
# placement time (the region graph is a 1-deep star drawn at random) and the one feature that tried
# to build one from fill spheres -- `stone_ramp` -- was deleted for it.
#
# Two sources feed one ladder, and both must, exactly as #539 established for the bells:
#   * SUBSTITUTION -- `vanilla_substitutions` below rewrites every tiered stone the item-shuffle walk
#     reads, so a vanilla stone check pays a rung instead of a tier;
#   * THE ECONOMY RESERVATION -- `filler_budget._draw_stones` mints rungs instead of tiers.
# Anything less leaves tiered stones in the pool beside the ladder, which is the bypass, not a
# degrade.
#
# MULTI-COPY LOTS COLLAPSE TO ONE RUNG, BY CONSTRUCTION AND CORRECTLY. core.create_items applies
# substitution to the BASE name and promotes to `<name> x<n>` afterwards (#616's deliberate order),
# and `Progressive Smithing Stone x3` is not a registered name -- so a lot that vanilla drops three
# stones on pays ONE rung. That is the right arithmetic for a ladder: a rung is a CHECK, and three
# stones out of one chest should advance you once, not three times.
VANILLA_STONE_ITEMS: Dict[str, str] = dict(
    [("Smithing Stone [%d]" % t, PROG_SMITHING_STONE) for t in range(1, 9)]
    + [("Somber Smithing Stone [%d]" % t, PROG_SOMBER_STONE) for t in range(1, 10)]
    # The un-numbered top rung of each track. Left loose they would be the bell-bearing bypass in
    # miniature -- a single pickup handing over the last level of a paced ladder.
    + [(ANCIENT_REGULAR, PROG_SMITHING_STONE), (ANCIENT_SOMBER, PROG_SOMBER_STONE)]
)

# Tier count per track. MIRRORS filler_budget.STONE_TIERS / SOMBER_TIERS; the two are not imported
# because filler_budget imports THIS module (for the names) and a module-level import back would
# cycle. tests/test_gf_graded_progression.py diffs them, the same mirror-and-gate shape
# scadu_supply.SCADU_CUM uses against the Rust ladder.
STONE_TIERS = 8
SOMBER_TIERS = 9
REGULAR_MAX_LEVEL = 24          # the last level the NUMBERED regular tiers reach
REGULAR_CAP_LEVEL = 25          # ...and the cap, once the Ancient Dragon step is counted

# Pseudo-tiers for the un-numbered top rung of each track, so one integer can index every rung.
ANCIENT_REGULAR_TIER = STONE_TIERS + 1      # 9  -> Ancient Dragon Smithing Stone, +25
ANCIENT_SOMBER_TIER = SOMBER_TIERS + 1      # 10 -> Somber Ancient Dragon Smithing Stone, +10


# ---- THE SOMBER <-> REGULAR EQUIVALENCE (Alaric, 2026-08-28) -------------------------------------
# A somber weapon at +N is worth a standard weapon at floor(N * 2.5). Somber 1 is a regular +2,
# somber 5 a +12, somber 10 a +25.
#
# ⭐ WHY IT MATTERS HERE. The two ladders are the same feature applied to two tracks, and without a
# conversion they were paced independently: regular over its cost table, somber uniformly over its
# tiers. Nothing said whether a player's somber weapon was ahead of or behind their standard one, so
# switching weapons could jump or stall. The equivalence turns "how far along is this track" into
# ONE number, and `somber_share_schedule` below paces somber against the regular curve with it.
#
# It also replaces a guess. features/filler_budget's `_somber_stone_need` says of the early
# guarantee: "Targeting the same EARLY_TARGET_LEVEL for both is therefore GENEROUS to somber ...
# somber +3 is roughly regular +7.5 in effective terms". Roughly is now exactly, and the answer is
# that regular +3 is somber ONE.
SOMBER_EQUIV_RATIO = 2.5


def somber_to_regular(somber_level: int) -> int:
    """A somber reinforce level -> the standard level it is worth. floor(N * 2.5)."""
    return int(somber_level * SOMBER_EQUIV_RATIO)


def regular_to_somber(regular_level: int) -> int:
    """The inverse, rounded DOWN to a somber level that does not overclaim.

    Deliberately the largest somber tier whose equivalent still fits inside `regular_level`, not the
    nearest: an early guarantee that promises somber 2 (+5) for a regular target of +3 has promised
    more than it was asked for, which is exactly the over-generosity this conversion exists to end.
    Returns 0 when even somber 1 (+2) overshoots.
    """
    for n in range(ANCIENT_SOMBER_TIER, 0, -1):
        if somber_to_regular(n) <= regular_level:
            return n
    return 0


def regular_level_costs(flatten: int):
    """[(level, tier, stones)] for a standard weapon, levels 1..REGULAR_MAX_LEVEL.

    The ONE place the 2/4/6 reinforce table is written in this module. Both the ladder and the early
    split read it, so they cannot disagree about what a level costs -- which matters because the
    split is "the stones +EARLY_TARGET_LEVEL needs" and the ladder is "the stones in the order they
    are spent", and those are the same table asked two ways.
    """
    out = []
    for lvl in range(1, REGULAR_MAX_LEVEL + 1):
        tier = (lvl - 1) // 3 + 1
        vanilla = (2, 4, 6)[(lvl - 1) % 3]
        out.append((lvl, tier, min(vanilla, flatten) if flatten > 0 else vanilla))
    return out


def regular_stone_tier_seq(flatten: int) -> List[int]:
    """The ORDER a standard weapon actually consumes smithing-stone tiers in, one entry per stone.

    Walks the game's own per-level cost table: level `lvl` sits in tier `(lvl-1)//3 + 1` and costs
    2/4/6 within its tier band, each level capped at `flatten` when `flatten_regular_upgrades` is
    non-zero (the same expression features/upgrades documents and the client mirrors).

    THE ORDER IS THE POINT, which is why this is not `filler_budget._regular_stone_need`. That
    function returns {tier: total}, which is the right shape for sizing a POOL and the wrong shape
    for building a LADDER -- it cannot say which stone is the 19th. The two must agree on the
    totals, and the test asserts `Counter(this) == _regular_stone_need(flatten)` rather than
    trusting that they do.
    """
    seq: List[int] = []
    for _lvl, tier, cost in regular_level_costs(flatten):
        seq += [tier] * cost
    return seq


def graded_regular_seq(flatten: int) -> List[int]:
    """The regular ladder's full rung sequence: the numbered tiers, then the Ancient Dragon step.

    One stone for the last level, because that is what +24 -> +25 costs."""
    return regular_stone_tier_seq(flatten) + [ANCIENT_REGULAR_TIER]


def somber_share_schedule(flatten: int) -> List[float]:
    """Cumulative fraction of the run at which each somber rung should ARRIVE, 1..10.

    This is the conversion doing its work. Somber tier N is worth regular level
    `somber_to_regular(N)`, so it belongs wherever the REGULAR ladder reaches that level -- which is
    the fraction of regular stones spent getting there. Both tracks then climb one shared power
    curve, and the somber ladder inherits the regular cost table's shape for free (at vanilla 2/4/6
    the early levels are cheap, so somber's early rungs come sooner; at a flat `flatten` they space
    out evenly).

    🛑 NOT A UNIFORM STRETCH OVER NINE TIERS, which is what this replaces. Uniform spacing assumes
    every somber rung is worth the same amount of progress; the equivalence says they are not --
    somber 1->2 is +2->+5, three regular levels, while somber 2->3 is +5->+7, two. Spacing them
    evenly puts a weapon ahead of its standard counterpart in some bands and behind in others.
    """
    cum, run = {}, 0
    for lvl, _tier, cost in regular_level_costs(flatten):
        run += cost
        cum[lvl] = run
    cum[REGULAR_CAP_LEVEL] = run + 1            # the Ancient Dragon step costs one stone
    total = cum[REGULAR_CAP_LEVEL]
    return [cum[min(somber_to_regular(n), REGULAR_CAP_LEVEL)] / total
            for n in range(1, ANCIENT_SOMBER_TIER + 1)]


def build_somber_ladder(n: int, flatten: int) -> List[int]:
    """`n` somber rungs, placed by `somber_share_schedule`. PURE, monotone, exactly `n` long.

    🛑 EVERY TIER GETS AT LEAST ONE COPY BEFORE ANY TIER GETS A SECOND. A somber weapon cannot pass
    a level it holds no stone for, so a SKIPPED tier is a permanent wall rather than thin supply --
    the failure mode features/filler_budget's `_somber_coverage_floor` was written for, which this
    has to keep honouring now that it owns the somber distribution. Below one copy per tier the
    ladder simply truncates: a seed that cannot cover the track should end early, not with holes.
    """
    tiers = ANCIENT_SOMBER_TIER
    if n <= 0:
        return []
    if n <= tiers:
        return list(range(1, n + 1))
    shares = somber_share_schedule(flatten)
    spare = n - tiers                    # what is left once every tier has its floor copy
    out: List[int] = []
    for i in range(tiers):
        cum = int(round(shares[i] * spare)) + (i + 1)
        cum = max(cum, i + 1)                       # the floor, cumulatively
        cum = min(cum, n - (tiers - 1 - i))         # ...and leave room for the tiers above
        out += [i + 1] * (cum - len(out))
    return out


def somber_stone_tier_seq() -> List[int]:
    """Somber weapons cost ONE stone per level and the tier IS the level, so the ladder is simply
    the tiers in order. `flatten_regular_upgrades` is regular-only, hence no flatten term (the same
    reason filler_budget._somber_stone_need takes none)."""
    return list(range(1, SOMBER_TIERS + 1))


def stretch_ladder(seq: List[int], n: int) -> List[int]:
    """Map `seq` onto exactly `n` rungs, order-preserving. PURE.

    n <= len(seq): TRUNCATE. The seed holds fewer stones than the full ladder costs, so the run tops
    out below the cap -- honestly, and it is stated (see Progressive.set_rules' log line). Same
    shape as the flask ladder honestly topping out below potency 12 on a small seed.

    n > len(seq): STRETCH, so the top tier is reached at the LAST rung rather than partway through.
    A big seed holds far more stones than the 48 a +24 costs at flatten 2, and padding the tail with
    the top tier instead would hand the player the whole ladder at ~40% depth and flatten the curve
    for the rest of the run -- i.e. reproduce the exact bug this feature exists to fix, just later.
    The surplus is spent as extra copies of the tier you are on, which is what a generous seed
    should feel like.

    ⭐ THE ONE OPEN TUNING QUESTION, stated rather than pre-empted. Reaching the top at the LAST rung
    means reaching it only after the multiworld has handed over every stone it holds -- so a player
    who finishes without receiving all of them tops out below the cap. Whether that wants headroom
    (top out at ~85% of copies, say) is a question for `tools/analyze_upgrade_curve.py` and real
    seeds, not for a constant chosen here. A fudge factor invented before the measurement would be a
    number defending itself, which is the habit this repo keeps writing gates against.
    """
    f = len(seq)
    if n <= 0 or f == 0:
        return []
    if n <= f:
        return list(seq[:n])
    return [seq[min(f - 1, (k * f) // n)] for k in range(n)]


def _early_segment(name: str, flatten: int):
    """`(split_at, early_copies)` for one track: how many of `seq` the early guarantee has to cover,
    and how many pool copies it declares to cover them with.

    Read from features/filler_budget, which OWNS both numbers -- `EARLY_TARGET_LEVEL` (the level a
    player must be able to afford in the first area) and `EARLY_GUARANTEE_MARGIN` (the "you need to
    pick up half of them" factor). Deriving them here would be a third copy of a promise that
    already has one definition and one place that declares it to AP.

    REGULAR: the stones levels 1..EARLY_TARGET_LEVEL cost, summed off the live flatten ladder.
    SOMBER: one stone per level and the tier IS the level, so the split is the LEVEL COUNT -- +3
    needs tiers 1, 2 and 3, not three copies of tier 1.

    🛑 THE REGULAR SPLIT IS A SUM OVER LEVELS, NOT `_regular_stone_need(flatten)[1]`. The two are
    equal today and only by coincidence: tier bands are three levels wide and EARLY_TARGET_LEVEL is
    3, so "the tier-1 stones" and "the stones +3 costs" name the same set. Raise the target to 5 and
    the tier-1 reading silently under-covers the promise -- and the entire reason this segment
    exists is that the early guarantee should not rest on two constants happening to line up.
    """
    from .filler_budget import (EARLY_GUARANTEE_MARGIN,  # local: filler_budget imports this module
                                EARLY_TARGET_LEVEL)
    if name == PROG_SOMBER_STONE:
        # THE CONVERSION, not the raw level. `regular_to_somber(3)` is ONE (+2), where the old
        # reading took three tiers and therefore promised somber +3 == regular +7.
        split = max(1, regular_to_somber(EARLY_TARGET_LEVEL))
    else:
        split = sum(c for lvl, _t, c in regular_level_costs(flatten) if lvl <= EARLY_TARGET_LEVEL)
    return split, split * EARLY_GUARANTEE_MARGIN


def build_ladder(seq, n: int, split_at: int, early_copies: int):
    """`seq` laid over exactly `n` rungs in two segments. PURE, and non-decreasing by construction
    (both segments are, and the second starts no lower than the first ends).

    Segment 1 -- the copies the early guarantee declares carry `seq[:split_at]`, i.e. the stones
    `+EARLY_TARGET_LEVEL` costs. This is what makes the floor structural instead of incidental: the
    promise is kept because the ladder is built to keep it, not because the tier bands happen to
    line up.

    Segment 2 -- everything after that stretches `seq[split_at:]` over the remaining copies, so the
    top tier still arrives at the LAST rung and the back of the run keeps its curve.

    A seed too small to fund even segment 1 gets a plain truncation: there is no early/late split to
    make when the whole supply is early.

    🛑 `early_copies` IS A FLOOR ON SEGMENT 1, NEVER A CAP. This is the correction to the first
    version and the reason the function is not simply `stretch(seq[:split], early_copies) + rest`.
    Handing segment 1 exactly `early_copies` rungs and giving segment 2 everything else means the
    LOW tiers stop growing with the seed while the high ones keep growing: 119 somber copies came
    out [2, 2, 2, 19, 19, 19, 19, 19, 18]. Somber costs one stone per level and the tier IS the
    level, so two copies each of tiers 1-3 caps the seed at TWO somber weapons ever passing +3,
    with a hundred surplus stones no weapon can reach. (Alaric spotted it in the heatmap, which is
    what the heatmap is for.)

    So segment 1 takes the LARGER of the early guarantee's margin and its proportional share of the
    sequence. A thin seed keeps the margin; a rich seed gets a flat spread across the tiers, which
    is both what vanilla feels like and what lets more than two weapons climb.

    🛑 THE MARGIN STILL COMES OUT OF THE SURPLUS. Segment 1 may never take so many copies that
    segment 2 cannot cover the rest of the sequence, or a seed holding exactly the full ladder
    (48 copies at flatten 2) tops out at +21 with no way to say why. That upper clamp is why the
    expression is a clamp and not a max. (Found by tools/analyze_upgrade_curve.py --selftest.)
    """
    if n <= 0 or not seq:
        return []
    if n <= split_at:
        return list(seq[:n])
    proportional = round(n * split_at / len(seq))
    ceiling = n - (len(seq) - split_at)
    early_n = min(max(split_at, early_copies, proportional), max(ceiling, split_at))
    return stretch_ladder(seq[:split_at], early_n) + stretch_ladder(seq[split_at:], n - early_n)


def _stones_on(world) -> bool:
    from . import graded_progression as _gp   # local: graded_progression does not import this file
    return _gp.is_on(world)


def stone_copy_count(world, name: str) -> int:
    """Copies of `name` this seed's pool actually holds == the ladder length.

    READ OFF THE REAL POOL, AND CACHED. Neither half of that is incidental.

    READ, because the count is the sum of two independently-sized contributions -- the substituted
    vanilla stone checks and features/filler_budget's economy reservation -- and only one of them is
    knowable from this module. Re-deriving it would be a second answer to a question core has
    already answered, and a ladder one rung out of step with the pool overflows its tail copies to a
    Lord's Rune client-side: stones silently becoming currency, which is the failure this whole
    feature is about.

    CACHED (`Progressive.set_rules` fills it), because slot_data runs after fill and by then the
    copies sit on locations -- some of them in OTHER PLAYERS' worlds under filler_foreign_pct.
    Counting there would undercount by exactly the share that travelled. set_rules is the one window
    where create_items has populated the pool and nothing has placed anything yet;
    features/filler_foreign picked it for the identical reason and documents the AP step order.
    """
    if not _stones_on(world):
        return 0
    counts = getattr(world, "gf_stone_copies", None)
    if counts is None:
        # 🛑 ABSENT IS NOT ZERO. A zero COUNT is a legitimate seed (no `stones` weight, no kept stone
        # check) and `set_rules` warns about it by name. An absent CACHE means set_rules never ran
        # for this world, and the consequence is silent and total: the ladder comes out empty while
        # the pool still holds copies, so the client overflows every one of them to a Lord's Rune --
        # the seed's entire smithing economy quietly becomes currency. Fail here instead.
        raise OptionError(
            "graded_progression: the %r ladder was asked for its length before "
            "Progressive.set_rules ran, so the pool copy count is unknown. This is a lifecycle bug, "
            "not a seed condition -- an empty ladder would silently turn every stone in the pool "
            "into a Lord's Rune client-side." % name)
    return int(counts.get(name, 0))


def stone_ladder(world, name: str) -> List[int]:
    """The TIER granted by each received copy of `name`: one entry per pool copy, non-decreasing.

    Deterministic (a closed-form stretch of a fixed cost table; `world.random` is not touched) and
    cached, so create_items, slot_data and the tests all read one answer.
    """
    cached = getattr(world, "gf_stone_ladders", None)
    if cached is not None and name in cached:
        return cached[name]
    n = stone_copy_count(world, name)
    flatten = _flatten(world)
    if name == PROG_SOMBER_STONE:
        # The somber track is paced by the equivalence, not by a two-segment stretch of its own
        # tiers -- see somber_share_schedule.
        ladder = build_somber_ladder(n, flatten)
    else:
        ladder = build_ladder(graded_regular_seq(flatten), n, *_early_segment(name, flatten))
    if cached is None:
        cached = {}
        try:
            world.gf_stone_ladders = cached
        except Exception:                      # not a real world (pure callers) -> no cache
            return ladder
    cached[name] = ladder
    return ladder


def _flatten(world) -> int:
    """`flatten_regular_upgrades`, the live stones-per-level cost. Mirrors filler_budget._flatten --
    same tolerance for a missing option, same reason (pure callers build partial worlds)."""
    o = getattr(getattr(world, "options", None), "flatten_regular_upgrades", None)
    return int(o.value) if o is not None else 0


def stone_tier_name(name: str, tier: int) -> str:
    """The vanilla stone a rung hands over. The top rung of each track is an un-numbered item."""
    if name == PROG_SOMBER_STONE:
        return ANCIENT_SOMBER if tier >= ANCIENT_SOMBER_TIER else "Somber Smithing Stone [%d]" % tier
    return ANCIENT_REGULAR if tier >= ANCIENT_REGULAR_TIER else "Smithing Stone [%d]" % tier


_STONE_ITEMS = (PROG_SMITHING_STONE, PROG_SOMBER_STONE)


# Which toggle activates which progressive items.
_FLASK_ITEMS = (PROG_FLASK,)
_KEY_ITEMS = (PROG_STONESWORD_KEY,)
_BELL_ITEMS = (PROG_SMITHING_BELL, PROG_SOMBER_BELL)


class ProgressiveFlasks(Toggle):
    """On (default): every Golden Seed and Sacred Tear check pays out a single "Progressive Flask
    Upgrade" item instead, one-for-one. Copies alternate deterministically: Charge, then +1 potency,
    then Charge, then +1, continuing in that order. The first copy visibly raises total charges above
    the vanilla starting allocation; +1 copies grant a Sacred Tear to spend at a grace. Off: seeds
    and tears stay discrete pickups at their shuffled locations. Flasks never gate logic, so either
    way the seed is always winnable."""
    display_name = "Progressive Flasks"
    default = 1


class ProgressiveStoneswordKeys(Toggle):
    """Off (default). On: add Progressive Stonesword Key items -- each copy grants one Stonesword
    Key for opening Imp Statue seals. Never gates logic (Region Locks are the only progression), so
    this is always winnable."""
    display_name = "Progressive Stonesword Keys"


class ProgressiveStoneBells(Toggle):
    """Off (default). On: the vanilla Miner's Bell Bearings are replaced by two progressive
    items -- Progressive Smithing-Stone and Progressive Somberstone Miner's Bell Bearing -- and each
    copy you receive unlocks the next tier of the Twin Maidens' smithing-stone shop directly (no
    hand-over). One copy of each is forced to sphere 0, so the upgrade ramp opens at the start, and
    there are exactly as many copies as there are shop tiers to unlock (4 and 5), so no copy is
    wasted and no single pickup skips you to the top. Never gates logic (Region Locks are the only
    progression), so this is always winnable."""
    display_name = "Progressive Stone Bell Bearings"


@register
class Progressive(Feature):
    name = "progressive"
    OPTIONS = {
        "progressive_flasks": ProgressiveFlasks,
        "progressive_stonesword_keys": ProgressiveStoneswordKeys,
        "progressive_stone_bells": ProgressiveStoneBells,
    }
    # All progressive copies are `useful` (never progression -> Region Locks stay the sole gate).
    ITEMS = {
        PROG_FLASK: ItemClassification.useful,
        PROG_STONESWORD_KEY: ItemClassification.useful,
        PROG_SMITHING_BELL: ItemClassification.useful,
        PROG_SOMBER_BELL: ItemClassification.useful,
        # 🛑 THE STONE LADDERS ARE `filler`, NOT `useful`, AND THE DIFFERENCE IS NOT COSMETIC.
        # These are the item features/filler_budget allocates BY THE HUNDRED into the filler tail --
        # they ARE the tiered stones, renamed -- and `useful` is the head of AP's restitempool, so
        # promoting them would place the entire smithing economy ahead of all filler and move every
        # seed. item_categories.CATEGORY_CLASS keeps `upgrade_materials` FILLER for exactly this
        # reason and calls it "the closest call on this table"; the ladder does not reopen it.
        # Staying filler is also what keeps filler_foreign / keep_local treating them as they treat
        # the stones today, which is correct here: a rung arriving from a partner world still
        # arrives in ladder order.
        PROG_SMITHING_STONE: ItemClassification.filler,
        PROG_SOMBER_STONE: ItemClassification.filler,
    }

    # ---- helpers ------------------------------------------------------------------------------
    def _active_items(self, world) -> List[str]:
        active: List[str] = []
        keys = getattr(world.options, "progressive_stonesword_keys", None)
        # 🛑 THE PREDICATES, NOT THE RAW OPTIONS, for the flask and the bells: graded_progression
        # forces both on and reading `world.options` here would arm the substitution while leaving
        # the item out of progressiveGrants -- a ladder with no rungs, which is how a feature goes
        # silently dark. Stonesword keys have no override, so they still read their own option.
        if _flasks_on(world):
            active += list(_FLASK_ITEMS)
        if keys and keys.value:
            active += list(_KEY_ITEMS)
        if _bells_on(world):
            active += list(_BELL_ITEMS)
        if _stones_on(world):
            active += list(_STONE_ITEMS)
        return active

    def _grant_ladder(self, world, name: str) -> List[Dict[str, Any]]:
        """Client `progressiveGrants` ladder for one progressive item: an ordered list of
        {"goods": GOODS-packed FullID, "flags": [event flags], "consumed": bool}. Fungible/keyed items
        (flasks, stonesword keys) repeat a single good with no flags; stone bells carry only the
        shop-unlock flags for that rung."""
        # `consumed`: the rung's goods are SPENT by the player, so the client must grant them exactly
        # ONCE (ledgered by the copy's stream index) rather than treating them as something the player
        # should OWN. Absent/false = owned = the client's self-healing `unique_goods` path.
        #
        # This distinction is not a nicety. The flask POTENCY rungs grant Sacred Tears, which are spent
        # at a Site of Grace. Shipped as OWNED, the reconciler saw the spent tear missing from the
        # inventory and handed it straight back -- upgrade, re-grant, upgrade, re-grant, unbounded,
        # until the flask ran past its cap and the game CTD'd. (Alaric, live playtest 2026-07-12.) So
        # the flask tears MUST be consumed=True.
        #
        # The flask rides progressiveGrants for its POTENCY axis ONLY: one consumed Sacred Tear per
        # copy, so the player upgrades potency at a grace the vanilla way (which updates every flask
        # mirror -- inventory entry, equipped/quickslot ref, global GaItem -- correctly). The CHARGES
        # axis is a separate reconciled leveled state (contract.flaskLadder, direct write). The old
        # in-place potency item-id swap CTD'd on death against the half-updated mirrors (playtest
        # 2026-07-19); granting a tear + a grace upgrade is the proven safe path.
        if name == PROG_FLASK:
            # Keep one progressiveGrants rung per pool copy so the tier ordinal is the authoritative
            # schedule. Odd copies are explicit no-ops here (their charge effect rides flaskLadder);
            # even copies grant exactly one consumed Sacred Tear until potency caps.
            return [
                ({"goods": _GOOD_SACRED_TEAR | _GOODS_NIBBLE, "flags": [], "consumed": True}
                 if copy % 2 == 0 and copy // 2 <= FLASK_POTENCY_MAX else {"noop": True})
                for copy in range(1, flask_copy_count(world) + 1)
            ]
        if name in _BELL_GRANTS:
            return [{"flags": list(e["flags"])}
                    for e in _BELL_GRANTS[name]]
        if name in _STONE_ITEMS:
            # One rung per pool copy; the rung's TIER is the ladder's whole content. `consumed`:
            # a smithing stone is spent at a grace, so it must be ledgered and granted exactly once.
            # Shipped as OWNED it would be the 2026-07-12 flask-tear bug again -- the reconciler sees
            # the spent stone missing and hands it back, forever.
            out = []
            for tier in stone_ladder(world, name):
                stone = stone_tier_name(name, tier)
                good = ITEM_CATALOG.get(stone)
                if good is None:
                    # A tier the catalog cannot resolve is a rung the client cannot grant, i.e. a
                    # stone silently becoming a Lord's Rune. Fail the generation instead: the whole
                    # point of the ladder is that every rung lands.
                    raise OptionError(
                        "graded_progression: %r is not in the item catalog, so the %s ladder has a "
                        "rung the client cannot grant. Regenerate the data modules "
                        "(python greenfield/gen_data.py)." % (stone, name))
                out.append({"goods": good, "flags": [], "consumed": True})
            return out
        # Stonesword Keys are spent on Imp Statue seals -> consumed.
        return [{"goods": good | _GOODS_NIBBLE, "flags": [], "consumed": True}
                for good in _GOODS_LADDERS[name]]

    # ---- hooks --------------------------------------------------------------------------------
    def generate_early(self, world) -> None:
        # Force a small number of stone-bell copies into sphere 0 (no-item-reachable) so the upgrade
        # ladder has an early first rung. AP's early_items biases placement of copies ALREADY in the
        # pool (added by create_items); it is soft + capped by pool availability and sphere-0 size, so
        # it never fails gen. Only the bells opt in (flasks/keys are fine wherever they land).
        active = set(self._active_items(world))
        early = world.multiworld.early_items[world.player]
        for name, n in _BELL_EARLY_COUNT.items():
            if name in active and n > 0:
                early[name] = early.get(name, 0) + n

    def set_rules(self, world) -> None:
        """Count the stone-ladder copies the pool actually holds, and cache them.

        🛑 NOT `create_items`, and not `slot_data`. AP's order (Main.py) is create_items (115) ->
        set_rules (118) -> ... -> fill. The two contributions to the count are made by DIFFERENT
        owners inside create_items -- core.vanilla_substitutions rewrites the item-shuffle walk, and
        features/filler_budget._draw_stones mints the reserved copies -- so no single point inside
        create_items has seen both. set_rules is the first point that has, and it is still before
        anything has been placed. slot_data is too late: by then the copies are on locations, some
        of them in other players' worlds, and a count taken there is short by exactly the share that
        travelled. features/filler_foreign.set_rules chose this window for the identical reason.
        """
        if not _stones_on(world):
            return
        counts: Dict[str, int] = {name: 0 for name in _STONE_ITEMS}
        for it in world.multiworld.itempool:
            if it.player == world.player and it.name in counts:
                counts[it.name] += 1
        world.gf_stone_copies = counts
        world.gf_stone_ladders = {}     # the count is known now; drop any zero-count pure-call cache
        log = logging.getLogger("Greenfield")
        for name in _STONE_ITEMS:
            ladder = stone_ladder(world, name)
            full = (ANCIENT_SOMBER_TIER if name == PROG_SOMBER_STONE
                    else len(graded_regular_seq(_flatten(world))))
            if not ladder:
                # INERT, WITH THE REASON. A recipe with no `stones` weight and a seed that kept no
                # stone check has no ladder to climb, and the option would otherwise look armed.
                log.warning(
                    "[eldenring:%s] graded_progression: %s has ZERO copies in the pool, so that "
                    "ladder is INERT this seed -- no `stones`/`somber_stones` weight in "
                    "curated_filler, and no kept check pays one. Add the weight, or keep more "
                    "regions.", world.player, name)
            elif len(ladder) < full:
                # A STATED CAP, NOT A SILENT ONE. The seed is smaller than the full ladder costs, so
                # the run tops out below the reinforce cap. That is the design (it mirrors enemy
                # scaling's own ceiling dropping with num_regions, scaling_ladder.auto_ceiling_pct),
                # but a player who cannot reach +24 deserves to find the reason in the log.
                log.info(
                    "[eldenring:%s] graded_progression: %s ladder is %d rung(s) of a full %d, so "
                    "this seed tops out at tier %d. The ladder length is the copies the pool holds; "
                    "a larger num_regions or a heavier `stones` weight buys more of it.",
                    world.player, name, len(ladder), full, ladder[-1])
            else:
                log.info(
                    "[eldenring:%s] graded_progression: %s ladder is %d rung(s), reaching tier %d "
                    "at the last copy (full ladder %d).",
                    world.player, name, len(ladder), ladder[-1], full)

    def create_items(self, world) -> List:
        # Add the configured number of copies of each active progressive item. core's count-neutral
        # fill (slots = total_locations - len(pool)) trims one filler-tail item per copy added here.
        pool: List = []
        for name in self._active_items(world):
            if name == PROG_FLASK:
                # Normal case: PROG_FLASK copies come from core.vanilla_substitutions of the kept
                # seed/tear checks (inject 0). dlc_only-style (no flask check kept): inject a fixed
                # count so the leveled ladder still has copies to advance. Count-neutral either way.
                pool += [world.create_item(PROG_FLASK) for _ in range(flask_inject_count(world))]
                continue
            if name in _BELL_GRANTS:
                # Same model as the flask, for the same reason: substituting the kept bell checks
                # supplies the copies (count-neutral, and it is what takes the vanilla bearings OUT
                # of the pool), and this tops up to the ladder length so every rung is reachable even
                # in a seed that kept no bell check at all. #539 -- see the module docstring for why
                # the bells need that floor when the flask's substitution-only model does not.
                pool += [world.create_item(name) for _ in range(bell_inject_count(world, name))]
                continue
            if name in _STONE_ITEMS:
                # PURE SUBSTITUTION, deliberately -- no injection and no _POOL_COUNTS entry. Both
                # sources of stone copies (the item-shuffle walk and the economy reservation) are
                # rewrites of slots that already existed, so the ladder is count-neutral without
                # this feature adding anything. A top-up like the bells' would be wrong here for the
                # reason the bells need one and this does not: the bell ladder has a FIXED length
                # that the vanilla data cannot supply, whereas this ladder's length IS the copy
                # count, so there is nothing to top up TO.
                continue
            if name not in _POOL_COUNTS:
                continue
            pool += [world.create_item(name) for _ in range(_POOL_COUNTS[name])]
        return pool

    def slot_data(self, world) -> Dict[str, Any]:
        # progressiveGrants = {item_name: [{"goods": FullID, "flags": [...], "consumed": bool}, ...]}.
        # Empty {} when no progressive toggle is on. Stonesword keys carry empty flags (spend-at-seal
        # goods); stone bells carry the Twin Maiden shop-unlock flags per rung (set = unlock). PROG_FLASK
        # IS INCLUDED: its POTENCY axis is consumed Sacred Tears on even copies (the player upgrades potency at a
        # grace the vanilla way, which updates every flask mirror safely). Its CHARGES axis rides the
        # SEPARATE flaskLadder wire below (a reconciled leveled state, direct write). The flask appearing
        # in BOTH wires is intentional and non-overlapping (tears != charges): the old in-place potency
        # item-id swap CTD'd on death against ER's half-updated flask mirrors (playtest 2026-07-19), and
        # an even older OWNED-tears build re-granted spent tears unbounded (playtest 2026-07-12) -- so
        # potency is now consumed-goods grants and consumed=True is required.
        grants: Dict[str, List[Dict[str, Any]]] = {}
        for name in self._active_items(world):
            grants[name] = self._grant_ladder(world, name)
        out: Dict[str, Any] = {contract.PROGRESSIVE_GRANTS: grants}
        # flaskLadder: the cumulative {charges, potency} target per received PROG_FLASK copy (charges are
        # the load-bearing axis client-side; potency is documentation). Emitted only when
        # progressive_flasks is on (absent otherwise).
        if _flasks_on(world):
            out[contract.FLASK_LADDER] = flask_ladder(world)
        return out
