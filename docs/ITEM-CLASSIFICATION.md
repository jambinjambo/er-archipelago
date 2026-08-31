# Item classification

How this world answers "what *is* this item?" — three separate questions, three
different owners, and the options that read each one.

Companion to `docs/ARCHITECTURE.md`. Source of truth is
`greenfield/eldenring/item_categories.py`; everything here is either quoted from it
or measured against it.

---

## The three questions

An item name gets asked three things, in this order. They are **not** the same
question and no two of them are derivable from each other.

| # | Question | Answer space | Decided in | Read by |
|---|---|---|---|---|
| 1 | **Category** — what kind of thing is it? | 17 keys, a strict partition | `item_categories.category_of` (`:229`) | `keep_local`, `keep_out_of_shops`, `filler_foreign_pct`'s per-category budget |
| 2 | **Class** — is it gear or is it junk? | `useful` / `filler` / `None` | `item_categories.class_of` (`:430`) | `core._classify_catalog`, `filler_foreign.filler_names` |
| 3 | **AP classification** — what must fill guarantee? | `progression` / `useful` / `filler` / `trap` | `core._class_for` (`core.py:1183`) | AP's fill algorithm, `filler_foreign._pool_filler_counts`, the per-slot report |

Worked, on five names:

| name | category | class | AP classification | why |
|---|---|---|---|---|
| `Moonveil` | `weapons` | `useful` | `useful` | nibble `0x0` → weapons; `CATEGORY_CLASS[weapons] = USEFUL` |
| `Golden Rune [1]` | `runes` | `filler` | `filler` | goodsType 0, but `rune_payout` = 200 → carved out to `runes` |
| `Golden Seed` | `upgrade_materials` | `useful` | `useful` | goodsType 14 → the smithing-stone category, then **promoted by name** via `USEFUL_GOODS` |
| `Godrick's Great Rune` | `key_items` | `filler` | `useful` **or** `progression` | the category cannot see the goal; `_class_for` decides per seed |
| `Smithing Stone [1] x3` | `progressive` | `None` | `filler` | no FullID → outside `ITEM_CATALOG`; the feature that minted it declares the class |

That last row is the shape of every surprise in this file: **a name outside
`ITEM_CATALOG` falls out of layers 1 and 2 entirely.**

---

## Layer 1 — category

### Where the data comes from

Three generated tables, all written by `greenfield/gen_data.py`, none hand-edited:

| table | in | derived from |
|---|---|---|
| `ITEM_CATALOG` | `item_ids.py` | `{vanilla item name: ER FullID}` |
| `GOODS_TYPE` | `item_ids.py` | `EquipParamGoods.goodsType` |
| `RUNE_PAYOUT` | `shop_stock_data.py` | `EquipParamGoods.refId_default` → `SpEffectParam.soul` |

Everything below is a pure function of those three. No curated list, no location
data — this is one of the modules `PROVENANCE.md` cares about.

### The FullID high nibble (`NIBBLE_CATEGORY`, `:58`)

| nibble | category |
|---|---|
| `0x0` | `weapons` |
| `0x1` | `armor` |
| `0x2` | `talismans` |
| `0x4` | *goods* — **not a category**, subdivided below |
| `0x8` | `ashes` (ashes of **war**; spirit ashes are goods) |

### `EquipParamGoods.goodsType` (`GOODS_TYPE_CATEGORY`, `:70`)

| type | category | | type | category |
|---|---|---|---|---|
| 0 | `consumables` | | 10 | `crystal_tears` |
| 1 | `key_items` | | 11 | `crafting` (the vessels) |
| 2 | `crafting` | | 12 | `other` |
| 3 | `other` (remembrances) | | 14 | `upgrade_materials` |
| 5 / 16 / 17 / 18 | `spells` | | 15 | `other` |
| 7 / 8 | `spirit_ashes` | | 9 | `other` (Physick flask) |

> **A goods type is an inventory tab, not a semantic class.** Type 1 holds the gate
> keys *and* 96 cookbooks *and* the bell bearings; type 0 holds throwing pots *and*
> Golden Runes. Where the module disagrees with the tab it says so by name.

### The four name carve-outs (`_goods_category`, `:147`)

These are the places the param is wrong for a player's purposes, and each one is a
recorded judgement rather than a filter:

| carve-out | out of | on what | why |
|---|---|---|---|
| `runes` | type 0 | `rune_payout(name) is not None` | Golden/Hero's/Lord's/Numen's Runes are levelling currency, not consumables. Keyed on the **payout column**, not a name match on "Rune" (which also hits Rune Arc and the Great Runes). |
| `cookbooks` | type 1 | name contains `Cookbook` | 96 of type 1's members are recipes. Gated on the type as well, so a future "Cookbook Grease" filed under consumables stays a consumable. |
| `upgrade_bells` | type 1 | `Bell Bearing` + one of `Smithing-Stone Miner's` / `Somberstone Miner's` / `Glovewort Picker's` | these 13 *are* the upgrade economy |
| `merchant_bells` | type 1 | `Bell Bearing`, everything else | the other 35 move a dead merchant's shelf to the hub. Convenience, not power. |

`greenfield/bell_handins.tsv` looks like the oracle for the bell split and **is
not** — it is the Maidens' talk-ESD menu, it covers 23 of the 48 bells, and its names
do not join (`Kale's` vs `Kalé's`). The cross-check that works is
`features/presence_floor`'s hand-picked roster of 8 stone bells, asserted by test.

### `progressive` — the bucket for everything with no FullID

`category_of` returns `PROGRESSIVE_CATEGORY` for **any name not in `ITEM_CATALOG`**.
That is not "the Progressive X items", despite the name. It holds:

- the `Progressive …` ladder items (`features/progressive.py`)
- every `<Region> Lock` and `Ashen Lock` (progression)
- the 390 `Trap: …` spawn traps (filler)
- the 7 `Unlock: …` ability items (useful)
- the 143 `… Set` armor bundles
- the 519 `… x<n>` stacked lot grants
- the `FILLER` sentinel, and `scadu_supply`'s injected fragment

Four AP classes in one category key. This is why `class_of` refuses to answer for it
(see layer 2).

### Great Runes: seven, keyed on the param row

`GREAT_RUNE_GOODS_IDS` (`:198`) is the one definition. Four modules used to carry
their own `name.endswith("Great Rune")` and all four were wrong the same way —
**"Great Rune of the Unborn" puts the words in the other order**, so every consumer
counted six. Keyed on the goods row id it survives any FMG rename, and
`GREAT_RUNES_MISSING` is asserted empty by test, so a data drift is loud instead of
the set silently shrinking again.

A Great Rune's *category* is `key_items`. Its AP class is decided per seed at layer 3.

### Selection surface: categories, umbrellas, `expand`, `names_in`

`CATEGORIES` (17) is what `category_of` answers. `UMBRELLAS` (`:270`) are the
compatibility and convenience keys a yaml may also name. `SELECTABLE` (20) is the
union, and it is what every `OptionSet.valid_keys` in this world is built from.

| umbrella | resolves to | why it exists |
|---|---|---|
| `goods` | the 12 goods-nibble categories | pre-split yamls say it; it must keep meaning exactly the goods nibble. **Derived from the catalog, not typed out** — the first version omitted `runes` and would have silently held 31 items that had always travelled. |
| `key_items` | `key_items` + `cookbooks` + `upgrade_bells` + `merchant_bells` | shipped in `release/EldenRing.yaml`; narrowing it would silently release 96 cookbooks for every yaml already saying `keep_local: [key_items]` |
| `bell_bearings` | `upgrade_bells` + `merchant_bells` | purely additive convenience |
| `everything` | all 17 categories | what the retired `local_item_only` sweep became |

> 🛑 **`key_items` is both a category and an umbrella, and they answer different
> questions on purpose.** `census()["key_items"]` = **85** (the narrowed category);
> `names_in(["key_items"])` = **242** (the whole tab). The consequence, stated rather
> than discovered: *the narrowed 85 have no selector of their own.* There is no
> category spelling of "hold the key items, release the Great Runes" — the umbrella
> is all-or-nothing and the 7 Great Runes ride inside it.

Two helpers, and the difference between them matters:

- `expand(keys)` — resolve a player's selection to concrete category keys. Unknown
  keys are **dropped**, not raised on; `valid_keys` is what rejects a typo, at
  yaml-verify time, with a message naming the valid set.
- `names_in(categories, extra_names=())` — every **catalog** name in those
  categories, plus any `extra_names` if `progressive` is among them. Callers feed this
  to `local_items`, so the return is sorted, to keep a seed's diagnostics diffable.

  🛑 `names_in` is the correct helper for building a name set — **not**
  `category_of(item.name)` over the pool. `category_of` answers `progressive` for
  every feature-minted name, so a pool walk selecting on it would sweep the traps, the
  region Locks and the boss keys into whatever the player asked for.
  `features/keep_out_of_shops.py:39` documents this; going through `names_in` makes it
  unrepresentable.

### Live census (`census()`, `:310`)

Distinct catalog names per category. 2361 names, exactly partitioned:

| category | names | | category | names |
|---|---|---|---|---|
| `armor` | 620 | | `key_items` | 85 |
| `weapons` | 514 | | `other` | 84 |
| `spells` | 201 | | `spirit_ashes` | 79 |
| `consumables` | 161 | | `merchant_bells` | 46 |
| `talismans` | 151 | | `upgrade_materials` | 43 |
| `ashes` | 105 | | `crystal_tears` | 37 |
| `cookbooks` | 96 | | `runes` | 31 |
| `crafting` | 93 | | `upgrade_bells` | 15 |

`progressive` is absent by construction — its members are not in the catalog.

---

## Layer 2 — class (`useful` / `filler`)

`CATEGORY_CLASS` (`:356`) maps category → one of two **strings**, `USEFUL` /
`FILLER`. It mints only those two, deliberately: **progression is per-name and
per-world**, so a category can never answer it. Whether Godrick's Great Rune gates
anything depends on this seed's `goal`; whether the Academy Glintstone Key does
depends on `features/legacy_key_gates`. The same category holds both answers in the
same seed.

| `useful` | `filler` |
|---|---|
| `weapons`, `armor`, `talismans`, `ashes` | `consumables`, `crafting`, `cookbooks`, `runes` |
| `spells`, `spirit_ashes`, `crystal_tears` | `upgrade_materials` |
| `upgrade_bells` | `merchant_bells` |
| | `key_items`, `other` |

Three entries carry reasoning worth knowing:

- **`spells` / `spirit_ashes` / `crystal_tears` → useful** (flipped 2026-08-12). 319
  names, ~3.3% of a default pool's copies. 🛑 *This is the entry that moves seeds* —
  `useful` is the head of AP's `restitempool`, so it is placed before any filler and
  the whole placement shifts.
- **`upgrade_materials` stays filler**, and it is the closest call on the table. A
  Somber [9] is not junk, but it is the economy `features/filler_budget` allocates *by
  the hundred* into the filler tail; promoting the category would move that whole tail
  into the useful tier. That is an economy change wearing a classification change's
  clothes. Argue it separately.
- **`key_items` and `other` are the two the partition cannot answer.** `key_items` is
  a tab holding gate keys *and* cookbooks *and* bell bearings; `other` holds
  remembrances, map fragments and the Physick flask. A single class is wrong for both,
  so they keep the conservative one and the promotions stay per-name in
  `core._class_for`. Do not "fix" these by flipping them wholesale.

`cookbooks` was carved out of `key_items` and inherits its class **unchanged**, so
that split moved no seed.

### `USEFUL_GOODS` — the per-name promotion (`:422`)

```
Golden Seed          +1 flask charge, permanent
Sacred Tear          +1 flask potency, permanent
Scadutree Fragment   the DLC's damage/defence ladder
Revered Spirit Ash   the DLC's spirit-ash ladder
```

`GOODS_TYPE` files all four under **type 14 — the same type as `Smithing Stone [1]`**,
so they land in `upgrade_materials`, which stays filler. They are promoted by name
instead. This is the third name-based carve-out in the module, the same species as
`runes` (by payout) and `cookbooks` (by mark): the param does not separate them, so it
is our judgement about our pool and it should read like one.

🛑 **It lives in `item_categories`, not in `core._class_for`, on purpose.** The
consumers must agree: `filler_foreign` builds its candidate list from `class_of`, and
if the promotion lived in core it would keep calling a Golden Seed filler while core
called it useful — a low `filler_foreign_pct` would then hold back an item the
classification says should travel.

### `class_of` returns `None`, and that is load-bearing

For any name outside `ITEM_CATALOG`, `class_of` returns `None` rather than a class.
`None` means *the caller owns the answer*. The `progressive` bucket holds progression
(Locks, boss keys), useful (ability unlocks, the scadu fragment) and filler (traps,
the sentinel) simultaneously; the features **declare** those in their `ITEMS` and that
declaration must win. Returning a class here would silently overrule them.

---

## Layer 3 — AP `ItemClassification`

This is the only layer AP's fill algorithm sees. It is assembled in `core.py` in four
passes at import, then adjusted per world.

### Build time (module import)

| pass | `core.py` | what it sets |
|---|---|---|
| core names | `:377` | every `<Region> Lock` and `ASHEN_LOCK` → `progression`; `FILLER` → `filler` |
| feature names | `:380` | `registry.collect_item_classes` folds in each feature's `ITEMS`; a duplicate name raises |
| catalog | `:397` | `_classify_catalog(name)` = `_CLASS_BY_KEY[item_categories.class_of(name)]` — so layer 2 **is** the catalog's classification |
| synthetic blocks | `:430`, `:448` | 390 spawn traps → `filler` (issue #114 rule 3: no progression may ride a trap); 7 ability unlocks → `useful` |

`_classify_catalog` indexes `_CLASS_BY_KEY` directly, so a `None` from `class_of`
would raise `KeyError`. That is the assertion, not an oversight — the loop only ever
feeds it catalog names, and a feature-minted name must keep what its `ITEMS` declared.

### Per world (`_class_for`, `core.py:1183`)

The only place `progression` is ever granted to a catalog item, because whether one
gates anything depends on **this seed's** options:

```
progression  if name in required_runes            (goal: great_runes)
             or gf_leyndell_runes                 (features/leyndell_gate)
             or gf_legacy_keys                    (features/legacy_key_gates)
             or gf_natural_keys                   (features/natural_progression)
             or required ability unlocks          (features/ability_lock)
useful       if name in GREAT_RUNES and base was filler   (#640)
base         otherwise
```

The Great Rune rescue exists because Great Runes are goods → `key_items` → filler by
default, and the branch above only saves the ones some gate happens to name. Since all
seven are always in the pool (#764), without it up to seven runes would sit there
labelled junk — eligible for the filler tail, and read as discardable by every
consumer that treats filler as safe to throw away. It raises **only from filler**, so
it never downgrades something a category rule already called useful.

### 🛑 `progressive` is not `progression`

The two words name unrelated things and sit one letter apart in the same file.

- `PROGRESSIVE_CATEGORY` is the layer-1 bucket for a name with no FullID. The
  `Progressive Flask Upgrade` / `Stonesword Key` / smithing bells that give it its
  name are declared **`useful`** by `features/progressive.py`. They gate nothing and
  never have.
- `ItemClassification.progression` is the layer-3 class, which **no category grants**.

Reading the first as the second would promote every feature-minted name — traps
included — into the fill's reachability constraints.

---

## What builds on each layer

| consumer | reads | how |
|---|---|---|
| `features/local_items.KeepLocal` | **category** | `names_in(expand(value), _PROGRESSIVE_NAMES)` → `world.options.local_items.value.update(names)` in `generate_early` |
| `features/local_items.KeepLocalRuneCap` | **`rune_payout`** | adds every catalog name whose payout ≤ cap. Independent of `keep_local`. |
| `features/filler_foreign.FillerForeignPct` | **class**, **AP class**, **category** | candidate set from `class_of(n) == FILLER`; copy counts from the real `ItemClassification.filler` in the pool; budget spent per `category_of` |
| `features/keep_out_of_shops` | **category** | the same `names_in` helper; bars a category from shop slots |
| `features/lot_stacks` | **class** of the base name | *intends* to mirror the base item so a stack is never worth more than what it stacks — see Known discrepancies |
| `core._classify_catalog` | **class** | the catalog half of layer 3 |
| `core` per-slot report (`:2429`) | **AP class** | `important = advancement or useful`, printed as `progression / useful / local filler / foreign filler / foreign useful` |
| AP fill | **AP class** | `progression` gets reachability guarantees; `useful` heads `restitempool` |

### `keep_local` (`features/local_items.py:98`)

An `OptionSet` over `SELECTABLE`. **It only ever adds to `local_items`, never
releases.** It ships non-empty — the only locality option that does — defaulting to
the `goods` umbrella minus `runes`, `key_items`, `spells`, `spirit_ashes`.

🛑 `key_items` is excluded **on evidence, not taste**: the category covers the Great
Runes, both Dectus medallions and every Remembrance, so keeping it home took
`natural_progression`'s cross-world placements from 12 to **zero** in
`tools/gf_multiworld_smoke.py`. That smoke is the gate; re-run it before adding the
line back.

🛑 **Naming one category does almost nothing.** Holding `runes` alone moved exported
filler by zero (202 → 202): whichever large pool stays open expands to fill every
available slot, so filler has to be closed close to *as a class* before the mix moves.
Measured useful:filler across the lattice — shipped 0.53:1, `runes` 0.54:1,
`runes + upgrade_materials` 0.60:1, `goods` minus `consumables` 0.73:1, whole `goods`
2.69:1. There is no category subset landing near the 1:1 target, which is why
`keep_local_rune_cap` carries the fine adjustment instead.

One hard-coded subtype: selecting `upgrade_bells` also localizes `PROG_SMITHING_BELL`
/ `PROG_SOMBER_BELL`, because the progressive bells *replace* the vanilla names in the
pool. `names_in` cannot express that — every feature-minted item shares the broad
`progressive` category — so it is done by name at `local_items.py:268`.

### `keep_local_rune_cap` (`features/local_items.py:159`)

Holds back rune items worth ≤ N runes. Default **12,500** = Numen's Rune, which holds
18 of the 31 rune items. It reads `rune_payout` directly rather than a category, which
is what makes it aimable: the threshold is a quantity the game publishes, not a share
of a pool nobody can picture. Independent of `keep_local` — setting `runes` there
keeps every rune home whatever this says.

### `filler_foreign_pct` (`features/filler_foreign.py:84`)

Percent of this slot's filler **copies** that may travel. **It only ever localizes.**

- `pct >= 100` → returns `[]`, no change.
- `pct <= 0` → every filler name local, no carve-out (the player asked for all of it).
- in between → spend a copy budget **within each category**, never taking a category's
  last name.

Three properties, each of which cost a measurement:

1. **Copies, not names.** A name-uniform draw cannot steer a copy-weighted outcome —
   the candidate set is ~121 names / ~293 copies, the median name carries one copy and
   `Smithing Stone [1]` carries 38. Name-drawn results were non-monotone (0.47 / 0.38 /
   0.63 / 0.59 / 1.75 across pct 100→0); copy-budgeted they are monotone (0.47 / 0.52 /
   0.61 / 0.82 / 1.87) and put the 1:1 target inside the range, around pct 6–12.
2. **Per category, never the last name.** A single pool-wide draw at 90% swept
   `merchant_bells`, `other` and `crafting` to zero free names — reproducing the
   whole-category bar that `keep_local` is the explicit knob for, in a seed where the
   player named no category at all.
3. **It runs in `set_rules`, not `generate_early`.** AP order is `create_items` (115) →
   `set_rules` (118) → `locality_rules` (140). That is the one window where copy counts
   and real classifications both exist *and* `local_items` is still read afterwards.

### How the two compose

Both write into the same AP set, `world.options.local_items.value`, and both only add.
Upstream `Main.py:103` then does `non_local_items.value -= local_items.value`, so **a
name in both lists is silently kept local — `local_items` always wins**, and there is
no "release" form of either option.

`keep_local` bars a category; `filler_foreign_pct` thins what is left. Aiming at a
specific *class* of item means `keep_local`; `filler_foreign_pct` cannot move a useful
item at all, because its candidate set is `class_of(n) == FILLER`.

---

## Commands

```powershell
$env:SKIP_REQUIREMENTS_UPDATE = "1"

# the taxonomy, live -- import from .ap-test, never standalone (see Traps)
python -c "import sys; sys.path.insert(0, '.ap-test'); from worlds.eldenring import item_categories as ic; print(ic.census())"
#   ic.CATEGORIES / ic.SELECTABLE     17 categories, 20 selectable keys
#   ic.category_of('Golden Seed')     -> upgrade_materials
#   ic.class_of('Golden Seed')        -> useful   (the USEFUL_GOODS promotion)
#   ic.expand(['goods'])              -> what an umbrella resolves to
#   len(ic.names_in(['key_items']))   -> 242, the tab, not the 85-name category
#   ic.rune_payout("Numen's Rune")    -> 12500

# the useful/filler split of a real pool, sampled over option sets
python tools/sample_pool_composition.py          # -> wizard/pool-composition.json

# WHAT we export, by AP classification AND by our category, split by destination game
python tools/gf_export_profile.py

# the taxonomy's own tests
python tools/gf_test.py -k item_categories
python tools/gf_test.py -k "local_items or filler_foreign"
```

Every ER world also prints its own layer-3 breakdown at the end of generation
(`core.py:2429`):

```
[greenfield] Jambo_ER: 1365 checks | progression 12 | useful 220 | local filler 904 |
                       foreign filler 128 | foreign useful 101
```

---

## Traps

- **`progressive` ≠ `progression`.** See layer 3. One letter, unrelated meanings.
- **Item CLASS and item LOCALITY are orthogonal axes, and only one is a lever for
  gear.** `filler_foreign_pct` filters on the filler class, so it can *never* move a
  Golden Seed no matter how high it goes. `keep_local` is the lever that reaches those.
- **`keep_local` reaches only catalog names.** Measured over 10 ER world-instances,
  **43% of a world's pool copies** are outside any category's reach: stacked variants
  (`… x3` has no FullID → `progressive`), the 143 `… Set` armor bundles, the
  `Progressive …` ladder items other than the two bells, and the region Locks. The only
  complete lever for those is a hand-written `local_items:` name list.
- **`names_in`, never `category_of` over the pool.** The pool walk sweeps every
  feature-minted name into whatever the player selected.
- **`key_items` has no except-form.** Selecting it takes the 7 Great Runes with it.
- **Loading a generated module standalone via `importlib` gives wrong answers** —
  `item_categories` returns `progressive` for everything when `ITEM_CATALOG` is
  unpopulated, and `class_of` then returns `None` for every name. Import from
  `.ap-test/worlds/eldenring` instead. The fail-soft in `_goods_category` is
  deliberate (a missing `GOODS_TYPE` means `consumables`, not `other`, so a pre-regen
  tree keeps the coarse behaviour instead of silently emptying every goods category a
  player selects) — but it is a fail-soft, not a correct answer.

### Known discrepancies

Two, both live as of 2026-08-30, neither fixed here because both would move seeds or
need a separate argument:

1. **`features/lot_stacks._class_for` always returns `filler`.** It computes
   `CATEGORY_CLASS.get(category_of(base))`, which yields the **string** `"useful"` /
   `"filler"`, then gates on `isinstance(cls, ItemClassification)` — which is never
   true for a string. So the "mirror the base item" contract in its docstring is not
   what runs. Blast radius today is nil: all 42 useful-base stack names that reach the
   pool (~21.8 copies per world) are ammunition — arrows, bolts, greatbolts — for which
   filler is arguably the right answer anyway. It is a latent bug rather than a live
   one: a stacked talisman or weapon entering `LOT_STACK_GRANTS` would be minted filler
   silently.
2. **`item_categories.py:265`'s `key_items` figures are stale.** The comment says
   `census()["key_items"]` is 124 and `names_in(["key_items"])` is 220; on this tree
   they are **85** and **242**. The reasoning it documents is still correct — only the
   numbers drifted, presumably across the 1.17 catalog change.
