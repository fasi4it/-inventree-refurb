# Implementation Plan — Refurb Workflow v1

## Context

`.claude/specs/workflow-spec.md` (v1.0) defines a build-to-order refurbished-computer operation end
to end: nine stages from chassis intake through fulfilment and returns, across six sales channels.
The business currently runs on a system whose central defect is that **form factor is decided twice**
— once from paperwork at intake, once from hardware at audit — and whose fallback rule ("processor
ends in T → Tiny, else trust the supplier's Chassis field") is only coincidentally correct. That
produces daily SKU mismatches, barcode-scan rejections, and manual corrective work.

This repository today is *only* an InvenTree Docker deployment (`inventree-refurb/`). There is no
application code. This plan builds the refurb system as a custom InvenTree plugin.

**Intended outcome:** form factor and specification are determined once, from hardware, at audit;
availability is computed from real component stock rather than guessed; and the scan at allocation
*resolves* which orders a machine can fill instead of validating against a pre-assigned SKU. Where
the system cannot determine something it stops and queues it for a human — it never guesses.

### Decisions taken (confirmed with the user)

1. **Full scope** — all nine stages, including the six channel connectors, the carrier API and Zoho
   Books sync. Delivered in phases, each independently useful.
2. **Hybrid data model** — InvenTree natives where they genuinely fit; plugin-owned Django models for
   the concepts with no native equivalent. Notably the Aiken audit is *not* forced into
   `StockItemTestResult`.
3. **Build fresh from the spec** — no dependency on any earlier work.

### A note on the two missing companion documents

`workflow-spec.md` lines 5–6 reference `refurb-inventory-spec.md` (the data model) and
`formfactor-resolver-spec.md`. Neither exists on disk. Per decision 3 this plan does not restore
them — instead §2 below **defines the data model**, since the workflow spec states plainly that it
does not. Treat §2 as the new authority; if the originals resurface, reconcile rather than merge
blindly.

---

## 1. Foundation — repo layout and the dev loop

### 1.1 Where plugin source lives

`inventree-refurb/inventree-data/` is bind-mounted to `/home/inventree/data` in the server and worker
containers, so `inventree-data/plugins/` *is* InvenTree's plugin directory. But `.gitignore` ignores
that path, and `CLAUDE.md` documents everything under `inventree-data/` as generated runtime data.
Putting source there would be untracked and misfiled.

**Solution:** plugin source lives in a new tracked top-level `refurb-plugin/`, sibling to
`inventree-refurb/`, and reaches the container through a new
`inventree-refurb/docker-compose.override.yml` — which Docker Compose merges automatically, so
`docker-compose.yml` stays untouched as `CLAUDE.md` requires:

```yaml
services:
  inventree-server:
    volumes:
      - ../refurb-plugin:/home/inventree/data/plugins/refurb
  inventree-worker:
    volumes:
      - ../refurb-plugin:/home/inventree/data/plugins/refurb
```

Fallback if the nested bind mount misbehaves on Windows: a `.gitignore` exception
(`!inventree-refurb/inventree-data/plugins/refurb/`). Prefer the override file.

> **Verified (P0):** the override mount works as designed. Two things had to be discovered
> empirically and aren't in the docs:
> 1. `INVENTREE_PLUGINS_ENABLED=True` (`.env`) only enables plugin *discovery*. `AppMixin`
>    apps additionally require the global setting `ENABLE_PLUGINS_APP=True`, set once via
>    `common.settings.set_global_setting('ENABLE_PLUGINS_APP', True, None)` in a Django
>    shell (or the admin UI) — separate from the individual plugin's own `active` flag.
>    Without it, the plugin loads and shows `active=True` in `PluginConfig`, but never
>    reaches `settings.INSTALLED_APPS` and `makemigrations` reports "No installed app".
> 2. Models **must** live in a flat `models.py`, not a `models/` package with submodules.
>    `AppMixin._reregister_contrib_apps` reloads a plugin's app via
>    `importlib.reload(app_config.models_module)`, which only re-executes that one module.
>    With a package, the parent `__init__.py`'s `from .chassis import ChassisModel` re-runs
>    but the `chassis` submodule itself is never reloaded, and on activation this reliably
>    fails with `ImportError: cannot import name 'ChassisModel'`. A flat `models.py` has
>    nothing to go stale — confirmed working end to end (FKs to `part.Part` and
>    `stock.StockItem`, `makemigrations`/`migrate`, real constraints in Postgres).

### 1.2 One plugin, not several

`AppMixin` registers a plugin as a Django app. Multiple plugins each owning models with foreign keys
between them creates app-loading and migration-ordering pain for no benefit. Build **one plugin,
`refurb`**, modularised internally by stage. The six channel connectors are subclasses of a shared
base inside it, not separate plugins — they share the same models.

```
refurb-plugin/
    __init__.py              RefurbPlugin(AppMixin, UrlsMixin, UserInterfaceMixin,
                                          ScheduleMixin, EventMixin, SettingsMixin)
    models.py                plugin-owned Django models (§2.2) — flat file, not a package;
                              see the P0 finding under §1.1 on why AppMixin's reload breaks
                              with submodules
    migrations/
    formfactor/              PURE stdlib module — no Django, no network (§3)
    intake/                  Stage 1 supplier-file parsing
    audit/                   Stage 6 Aiken ingest + normalisation + reconciliation
    components/              Stage 2 ledger
    build/                   Stage 5 proposal + compatibility refusals
    availability/            §12.2 computed availability + cache invalidation
    reservation/             Stage 4 capacity reservation
    matching/                Stage 7 match rules + scoring + failure explanation
    fulfilment/              Stage 8 carrier adapter
    returns/                 Stage 9 three RMA paths
    channels/                base.py + amazon/bestbuy/temu/walmart/ebay/shopify
    books/                   Zoho Books daily summaries
    queues/                  review queue framework
    api/                     DRF serialisers + viewsets served under /plugin/refurb/
    templates/ static/       UI (§5)
    tests/
```

Scaffold with [inventree/plugin-creator](https://github.com/inventree/plugin-creator) rather than by
hand — it produces the correct Vite/static layout.

### 1.3 Pin the InvenTree version — do this first

`.env` has `INVENTREE_TAG=stable`, which is unpinned. InvenTree is at 1.4.x (1.2.0 Feb 2026, 1.3.0
Apr 2026). Writing plugin migrations and model FKs against a tag that can move on any `docker compose
pull` is the single cheapest way to lose a day. Pin `INVENTREE_TAG` to the exact current version in
`.env` before writing any model code.

### 1.4 Dev loop

Edit under `refurb-plugin/` → `docker compose restart inventree-server inventree-worker` → reload.
Plugin migrations run via `docker compose exec inventree-server invoke migrate`. Note the stack is
currently **down** and Docker Desktop is not running; both must be started before any of this.

---

## 2. Data model

### 2.1 What InvenTree natives carry

| Concept | Native object | Notes |
|---|---|---|
| Chassis model (catalogue) | `Part` (assembly, trackable) | Identity + BOM only; typed refurb attributes go in the side table |
| Chassis (physical machine) | `StockItem` with serial | Serial is identity — never reassigned |
| Component part | `Part` | |
| Component stock | `StockItem`, quantity-tracked | `on_hand` |
| Component ledger | `StockItemTracking` | Native append-only movement record |
| Build | `BuildOrder` with serialised output | BOM consumption |
| Sales order / line | `SalesOrder` / `SalesOrderLineItem` | |
| Shipment | `SalesOrderShipment` | Carrier/label data in a side table |
| RMA | `ReturnOrder` | |

### 2.2 Plugin-owned models

Everything below has no native equivalent, or the native fit is strained enough to fight later.

| Model | Purpose | Key fields |
|---|---|---|
| `ChassisModel` | 1:1 side table on chassis-model `Part`; the part-number lookup that replaces the T-suffix rule | `part_number` (PK-ish, indexed), `manufacturer`, `model_name`, `form_factor` (nullable), `ambiguous`, `ram_slots`, `max_ram_gb`, `supports_optical`, `weight`, `dims`, `verified_at/by` |
| `ChassisState` | 1:1 side table on the serialised `StockItem`; the refurb lifecycle | `status` (§2.3), `form_factor`, `form_factor_source`, `grade`, `cost_basis`, `has_os`, `os_licence`, `field_modified`, `location` |
| `IntakeLot` | Stage 1 | `supplier`, `reference`, `total_cost`, `declared_form_factor` (**advisory only**), `unit_count_declared/received`, `raw_rows` (JSON) |
| `Audit` | **Append-only.** One Aiken reading | `stock_item` FK, `audit_type`, `audited_at`, `raw_payload` (JSON, complete + unmodified), normalised fields, `chassis_field_raw` (stored, never used), `is_complete` |
| `Resolution` | Output of one resolver run over one `Audit` | `audit` FK, `form_factor`, `source`, `queue_reason`, `detail`, `conflicts`, `resolver_version`, `actor` |
| `CpuModel` | CPU equivalence — never numeric comparison | `code`, `raw_variants`, `family`, `generation`, `is_low_power` (**informational only**), `equivalence_class` |
| `ComponentAttrs` | Side table on component `Part` | `type`, `capacity_gb`, `form_factor` (**DIMM/SODIMM, required for RAM**), `speed`, `interface` |
| `ListingSKU` | Channel-facing product; owns requirements, not stock | `sku`, `channel`, requirement fields, `ram_match_mode`, `storage_match_mode`, `channel_buffer`, `active` |
| `ChannelOrderRef` | Idempotent ingest | `channel` + `channel_order_id` **unique together**, FK `SalesOrder` |
| `OrderLineSnapshot` | Requirements frozen at order time | `line` FK, `snapshot` (JSON) |
| `CapacityReservation` | Holds capacity, not a serial | `line` FK, requirement fields, `reserved_components` (JSON), `expires_at`, `state` |
| `Allocation` | Serial ↔ order line binding | `line` FK, `stock_item` FK, `status` (ALLOCATED/SHIPPED/CANCELLED/RETURNED/**REPLACED**), `match_score`, `override_reason`, `allocated_by/at` |
| `ReviewQueueItem` | Every "stop" path lands here | `queue`, `subject` (generic FK), `reason`, `opened_at`, `resolved_at/by`, `writeback_ref` |
| `ShipmentDetail` | Side table on `SalesOrderShipment` | carrier, service, label, tracking, weight/dims used, cost |
| `BooksSync` | Idempotency for Zoho pushes | `kind`, `period`, `pushed_at`, `external_ref` |

**Every plugin model must implement a `check_user_permission` classmethod.** Without it InvenTree's
permission system denies all access by default — this is a silent, confusing failure mode.

Indexes that matter: `ChassisState(status, form_factor)` for the availability count;
`ChassisState(status)` partial on `AVAILABLE`; `Allocation(line, status)`;
`CapacityReservation(state, expires_at)` for the expiry sweep; `ChassisModel(part_number)` unique.

### 2.3 Chassis lifecycle

`RECEIVED → AWAITING_AUDIT → AVAILABLE → ALLOCATED → SHIPPED → RETURNED`, with `AWAITING_AUDIT →
REVIEW_QUEUE → AVAILABLE` and `→ SCRAP`. Returned units re-enter at `AWAITING_AUDIT`. **Only
`AVAILABLE` counts toward saleable stock** — `REVIEW_QUEUE` is deliberately excluded, or the queue
becomes decorative.

### 2.4 Where this fights InvenTree — stated honestly

- **Computed availability vs stored stock counts.** InvenTree maintains its own quantities. Ours are
  computed per §12.2 and will not agree. That is expected and correct; do not build a reconciliation.
- **Capacity reservation has no native analogue.** InvenTree allocates *concrete* stock; we reserve
  *capacity* for a machine that does not exist yet. Fully plugin-owned.
- **Multiple allocations on one order line** (required for replacements) is why `Allocation` is
  plugin-owned rather than `SalesOrderAllocation`. Mirror into the native object at shipment time so
  InvenTree's own reporting stays sensible.
- **The chassis lifecycle is richer than `StockItem.status`**, so it lives in `ChassisState`. The
  consequence: InvenTree's stock views will not show refurb status. UI panels (§5) compensate.
- **Redis has persistence disabled** in this deployment. It is a cache only — reservations and
  queues are durable Postgres rows, never Redis state.

---

## 3. The form factor resolver

The root-cause fix, and the piece everything else depends on. Build it **first** and build it
**pure**: `refurb-plugin/formfactor/` imports only the standard library — no Django, no network, no
clock, no file reads. The part-number lookup is injected at construction.

```
resolve(AuditInput) -> Resolution     # frozen dataclasses in / out
```

Decision order — memory type is evaluated **before** the part-number gate, because a unit with an
invalid part number but SODIMM memory is unambiguously TINY and must not queue:

1. `product_type == LAPTOP` → `(LAPTOP, PRODUCT_TYPE)`
2. audit incomplete (missing CPU, RAM total, or storage) → `INCOMPLETE_AUDIT`
3. RAM form factor is `SODIMM` → `(TINY, RAM_TYPE)` — a physical constraint: tiny chassis cannot
   accept full-height memory
4. model name states it (Lenovo `M##q/s/t`, HP "Desktop Mini"/"MT"/"SFF", Dell "Micro") →
   `(ff, MODEL_NAME)`
5. part number absent → `NO_PART_NUMBER`; not in the table → `UNKNOWN_PART_NUMBER`; present but
   `ambiguous` → `AMBIGUOUS_DELL_DIMM`; else `(ff, PART_NUMBER)`
6. cross-check every signal that produced an opinion; any disagreement → `SIGNAL_CONFLICT`

### Enforcing "never guess" structurally

- Output invariant `(form_factor is None) XOR (queue_reason is None)`, held by construction — one
  return path per outcome, no partial states, no `else: return default`.
- **Structural tests** assert the resolver source never references CPU normalisation and never reads
  `chassis_field_raw` for a decision. Both are documented failure causes: Aiken's `Chassis` field
  cannot express TINY (zero occurrences in 1,329 units), and the CPU T-suffix rule is the current
  production defect. A test that reads the module source is the only thing that stops these creeping
  back in.
- `normalize_ram_form_factor` must check `SODIMM` **before** `DIMM` — `"SODIMM".contains("DIMM")` is
  true, and that substring-ordering bug is the entire reason this component exists.
- Dell desktop codes seed with `ambiguous = true, form_factor = null`. Seed **only verified rows**;
  unknown codes must queue, never default.

Called from audit ingest (§4) as a pure function over the stored raw payload — which means when a
rule is later found wrong, every historical audit can be re-resolved into a new `Resolution` row
without touching the append-only `Audit`.

---

## 4. Concurrency — the two places that must be right

### Stage 4, reservation

Two channels selling the last unit simultaneously must not both succeed. The contended resource is a
*count*, not a row, and you cannot `SELECT FOR UPDATE` a count. Use a Postgres transaction-scoped
advisory lock keyed on the requirement signature, inside one `transaction.atomic()`:

```python
with transaction.atomic():
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [pool_key])
    # re-count AVAILABLE chassis matching form factor + CPU class
    # SELECT FOR UPDATE the component StockItem rows involved
    # create CapacityReservation, or flag the order AT_RISK
```

READ COMMITTED is sufficient given the advisory lock — avoid SERIALIZABLE and its retry handling.
Unsatisfiable never rejects the order (the channel already took the customer's money); it accepts,
flags `AT_RISK`, and alerts a supervisor immediately. A `ScheduleMixin` task sweeps expired
reservations back to `OPEN`.

### Stage 7, scan-time allocation

Here the contended resource *is* a row — one physical machine. `select_for_update()` on the
`ChassisState` for that serial, re-verify `status == AVAILABLE` inside the lock, then create the
`Allocation` and consume the reservation in the same transaction.

### Cache invalidation

Availability cached in Redis for 30–60s per listing SKU, invalidated via `EventMixin` on any chassis
state change, ledger write, reservation create/expire/consume, or listing edit. Push to channels
**on change, never on a timer** — a timer guarantees a stale window.

---

## 5. UI surfaces

Verified against the InvenTree docs: `UserInterfaceMixin` injects React panels into **existing**
pages, plus dashboard items and navigation elements — it does not create arbitrary new routes.
Review queues, the scan screen and the build screen all need full screens. So:

- **Full screens** — `UrlsMixin` serving Django views under `/plugin/refurb/...`, backed by the
  plugin's DRF API. Server-rendered templates for v1; the scan screen is the one worth upgrading to
  React later if the interaction warrants it.
- **Panels** — `UserInterfaceMixin` on the `StockItem` detail page: audit history, current form
  factor resolution (with its source and any conflicts), fitted components. This is what compensates
  for the refurb lifecycle living outside `StockItem.status`.

**Verify first:** whether InvenTree 1.4's UI mixin now supports custom navigation routes. If it does,
prefer React for the queue screens and skip the server-rendered stage.

Queue screens are core functionality, not error handling: one screen per queue, batch-workable, age
visible, one-click resolution where possible, and **every resolution writes back to reference data**
so the same question is never asked twice. That write-back is what makes queues shrink instead of
becoming permanent labour.

The scan screen's "show why" requirement is not cosmetic — on no match it must name the attribute
that failed against the nearest orders. Opaque rejection is what drives staff to manual workarounds
today.

---

## 6. Delivery phases

Each phase leaves the business better off than before it.

| # | Phase | Delivers | Depends on |
|---|---|---|---|
| **P0** | Foundation: `refurb-plugin/`, compose override, **pin `INVENTREE_TAG`**, AppMixin skeleton, one trivial model migrated end to end, pytest harness | A plugin that loads and migrates | — |
| **P1** | Form factor resolver (pure) + `ChassisModel` lookup + seed data | The root-cause fix, fully tested with zero infrastructure | P0 |
| **P2** | Stage 1 intake + Stage 6 Aiken ingest/normalisation + `Resolution` + review queues | Trustworthy unit records; chassis reach `AVAILABLE` | P1 |
| **P3** | Stage 2 component stock + ledger, Stage 5 build + compatibility refusals | Component visibility — makes availability *possible* | P2 |
| **P4** | `ListingSKU`, computed availability (§12.2), Stage 4 capacity reservation | Oversell protection | **P3 — not negotiable** |
| **P5** | Manual order entry + Stage 7 scan-to-allocate, scoring, "show why", override | Manual SKU moves eliminated | P4 |
| **P6** | Stage 3 — six channel connectors + quantity push | Automatic order capture | P5 |
| **P7** | Stage 8 — carrier API, shipment, tracking push | Fulfilment end to end | P6 |
| **P8** | Zoho Books — purchase bills per lot, daily invoice/COGS summaries | Accounting closed | P7 |
| **P9** | Stage 9 — refund / replacement / NRR | Full lifecycle | P7 |

**P3 before P4 is not negotiable.** Availability cannot be computed without component stock;
building channel sync on guessed availability recreates the oversell risk in a new system.

Costing rides along: `unit_cost = chassis_cost_basis + Σ(components consumed)`, lot cost spread
evenly across non-scrap chassis, harvested components at zero cost, no labour in v1. Deliberately
simple — **apply it consistently**, because changing the rule later makes historical margins
incomparable.

---

## 7. Testing

| Layer | Tooling | Covers |
|---|---|---|
| Pure Python, no DB | `pytest` | Resolver, normalisation, match rules, scoring, availability arithmetic, compatibility refusals. **The bulk of the logic — keep it here.** |
| Structural | `pytest` reading module source | Resolver never consults CPU suffix or `chassis_field_raw`; invariant holds on every constructed case |
| Django + Postgres | `pytest-django` | Models, state machines, ledger correctness, queue write-back |
| Concurrency | `pytest.mark.django_db(transaction=True)` + threads | Two simultaneous reservations for the last unit — one succeeds, one goes `AT_RISK`. Requires real connections, not `TestCase` |
| Stack-up integration | `docker compose` running | Plugin loads, migrations apply, panels render, API responds |
| External (6 channels, carrier, Books) | Adapter interface + recorded fixtures | Never test against live marketplaces. A `--live` marker, gated on credentials, for manual verification only |

Add `pytest`, `pytest-django` and `openpyxl` to a dev requirements file — the existing `.venv`
(Python 3.14.5) has only the `inventree` REST client and `requests`.

---

## 8. Riskiest parts — verify before building on them

1. ~~`INVENTREE_TAG=stable` is unpinned.~~ **Done.** Pinned to `1.4.3` in `.env`.
2. ~~AppMixin migrations.~~ **Verified in P0.** `ChassisModel`/`ChassisState` (FKs to `part.Part`
   and `stock.StockItem`) migrate cleanly and the FK/check/unique constraints exist in Postgres as
   designed — but only after two undocumented steps; see the P0 finding under §1.1
   (`ENABLE_PLUGINS_APP` global setting, and models must be a flat `models.py`, not a package).
3. **`check_user_permission`.** Missing it means every plugin model 403s with no obvious cause.
   Implemented on the shared `RefurbModel` base — verified via `ChassisModel.check_user_permission`.
4. **The Aiken RAM form factor field.** The entire resolver depends on knowing DIMM vs SODIMM. It is
   unconfirmed whether the Aiken export carries it (spec §15, O1). Fallback: read
   `Win32_PhysicalMemory.FormFactor` at audit time (8 = DIMM, 12 = SODIMM). **Resolve this before
   P2** — it changes the ingest design.
5. **Seed data for `ChassisModel`.** Needs real, verified part numbers. Per the never-guess
   principle, seed only what is confirmed and let the rest queue.
6. ~~Docker Desktop is not running.~~ **Done.** Also found and fixed unrelated corruption in
   `%USERPROFILE%\.docker\daemon.json` (fully zeroed — an unclean shutdown, unrelated to this
   project) that was silently blocking the engine from starting at all; backed up and reset to `{}`.

### Open items from spec §15 to close before their phase

| Item | Blocks |
|---|---|
| O1 `RAM1Type` availability | P2 |
| O3 `AT_RISK` escalation policy — cancel, source, or substitute upward? | P4 |
| O4 Component substitution rules — may a 512GB drive fill a 256GB build? | P3/P5 |
| O5 Grade assignment criteria | P2, P9 |
| O2 Dell SFF vs Tower automation | P2 (may remove one queue) |
| O6 Multi-unit order handling at volume | P4/P5 |

---

## 9. Verification

Each phase ends green before the next begins.

- **P0:** `docker compose up -d`; plugin appears in the InvenTree plugin list and is enabled;
  `invoke migrate` applies the plugin's migration; the trivial model is readable through the API.
- **P1:** `pytest refurb-plugin/tests/` passes with the stack **down** — the resolver is pure, so it
  needs nothing running. Hand-check a Dell DIMM case (queues, never guesses) and a SODIMM case with a
  garbage part number (resolves TINY anyway).
- **P2:** import a supplier file → chassis appear at `RECEIVED` with **no form factor**; ingest an
  Aiken payload → `Audit` stores the raw payload verbatim, chassis reaches `AVAILABLE` or lands in a
  queue with a named reason. Confirm the supplier's declared form factor was never written to the
  chassis.
- **P3:** fit components against a build → ledger entries written, `on_hand` and `reserved` both
  decrease. Attempt a SODIMM-into-TOWER build → **refused**.
- **P4:** the concurrency test above. Then confirm published quantity =
  `max(0, buildable − reservations − buffer)` and that a listing with unresolved requirements
  publishes nothing.
- **P5:** scan a built unit → ranked candidate orders, tightest fit first. Scan a unit that matches
  nothing → the failing attribute is named. Scan a 32GB unit with both a 16GB and a 32GB order open →
  the 32GB order ranks first.
- **P6–P9:** recorded-fixture tests green; then one end-to-end run per channel against a sandbox
  account before any live credential is used.
