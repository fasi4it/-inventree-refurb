# Workflow Specification — Refurb Inventory System

**Version:** 1.0
**Scope:** Operational process, end to end
**Companion documents:** `refurb-inventory-spec.md` (data model), `formfactor-resolver-spec.md`,
`build-plan.md`

This document defines *what happens, in what order, and what the system does at each point.* It does
not define storage structures — that is the data model spec.

**Change from earlier drafts:** components (RAM, storage, optical drives) are recorded in the system.
They are no longer a spreadsheet outside it. Every stage below reflects that.

---

## 1. Actors and systems

| Actor | Role |
|---|---|
| **Accounts** | Receives supplier files, records purchases, reconciles settlements |
| **Warehouse technician** | Builds units, fits components, runs audits, scans and packs |
| **Supervisor** | Clears review queues, authorises overrides, decides scrap |
| **System** | This application |

| External system | Purpose | Direction |
|---|---|---|
| Sales channels (×6) | Orders in, quantities out, tracking out | Both |
| Aiken | Hardware audit data | In |
| Carrier API (EasyPost/Shippo) | Labels and rates | Both |
| Zoho Books | Accounting | Out |

---

## 2. Object states

### 2.1 Chassis

```
RECEIVED → AWAITING_AUDIT → AVAILABLE → ALLOCATED → SHIPPED → RETURNED
                 ↓              ↑                                  ↓
            REVIEW_QUEUE ───────┘                          AWAITING_AUDIT
                 ↓
               SCRAP
```

Only `AVAILABLE` counts toward saleable stock.

### 2.2 Component stock

Quantity-tracked, not serialised. Three numbers per part:

```
on_hand − reserved = available
```

Availability calculations use `available`. Never `on_hand`.

### 2.3 Order

```
OPEN → RESERVED → PARTIALLY_ALLOCATED → ALLOCATED → SHIPPED → CLOSED
                          ↓
                      CANCELLED
```

---

## 3. Stage 1 — Chassis intake

**Trigger:** A wholesale lot arrives with a supplier file.
**Actor:** Accounts.

### Steps

1. Create an intake lot: supplier, reference, total cost, declared quantity.
2. Upload the supplier file.
3. System parses and extracts **serial numbers only**.
4. One chassis record created per serial, status `RECEIVED`.
5. Import report returned: accepted, rejected, duplicate.

### System effects

- Chassis records exist with **no form factor, no specification, not saleable**.
- Lot cost recorded for later allocation.
- Full source rows retained for reference.
- Purchase bill pushed to Zoho Books.

### Rules

| Rule | Reason |
|---|---|
| Serial is the only required field | Everything else comes from the hardware |
| Form factor is **not** assigned here | Paperwork is not an authority on hardware — see §12.1 |
| Supplier's declared form factor is advisory only | Recorded for cross-checking, never written to the chassis |
| Duplicate serials rejected with existing status shown | Prevents double-counting stock |

### Exceptions

| Case | Handling |
|---|---|
| Serial missing or malformed | Row rejected, listed in report |
| Serial already exists | Rejected as duplicate |
| Received count ≠ declared | Warning; import proceeds |

**Exit:** Chassis in `RECEIVED`, awaiting physical audit.

---

## 4. Stage 2 — Component intake

**Trigger:** Components purchased, or harvested from a scrapped unit.
**Actor:** Accounts (purchase) or warehouse technician (harvest).

### Steps

1. Identify the component part — type, capacity, form factor, interface.
2. Enter quantity received and unit cost.
3. Stock ledger entry written: `PURCHASE` or `HARVEST`.
4. `on_hand` increases.

### Rules

| Rule | Reason |
|---|---|
| RAM form factor (DIMM / SODIMM) is **required**, not optional | A SODIMM stick cannot go into a tower; the system must be able to refuse that build |
| Harvested components enter at zero cost | Consistent with the chosen lot-costing rule (§13.2) |
| Every movement writes a ledger entry | The ledger is the audit trail; quantities are derived from it |

**Exit:** Components available for reservation and consumption.

---

## 5. Stage 3 — Order capture

**Trigger:** A customer buys on any of the six channels.
**Actor:** System, automatic.

### Steps

1. Channel connector polls or receives the order.
2. Sales order created with channel reference.
3. Order lines created against listing SKUs.
4. **Requirements snapshotted** onto each line — form factor, CPU class, RAM, storage, OS, grade.
5. Reservation attempted (§6).

### Rules

| Rule | Reason |
|---|---|
| Requirements are frozen at order time | A listing may be edited later; the customer bought what was advertised then |
| Channel order ID must be unique per channel | Prevents duplicate ingestion on retry |
| An order is never rejected for lack of stock | The channel already took the customer's money |

**Exit:** Order `OPEN`, reservation attempted.

---

## 6. Stage 4 — Reservation

**Trigger:** Order line created.
**Actor:** System, automatic.

This stage exists because **the unit does not exist when the order arrives.** Reservation holds
*capacity* — a qualifying chassis and the components needed — until a physical machine is built.

### Steps

1. Inside one database transaction:
   - Count `AVAILABLE` chassis matching the required form factor and CPU class.
   - Check each required component has sufficient `available` quantity.
2. If satisfiable: create the reservation, increment component `reserved`, set order `RESERVED`.
3. If not satisfiable: accept the order, flag `AT_RISK`, raise a supervisor alert.

### Rules

| Rule | Reason |
|---|---|
| The check and the reservation are one transaction | Two channels selling the last unit simultaneously must not both succeed |
| Reservations expire | Otherwise a cancelled-but-unclosed order holds stock forever |
| `AT_RISK` orders alert immediately | The customer has paid; someone must decide within hours, not days |

### Exceptions

| Case | Handling |
|---|---|
| No qualifying chassis | `AT_RISK` — source, substitute upward, or cancel |
| Components short | `AT_RISK` — purchase or substitute |
| Reservation expires unbuilt | Released, order returns to `OPEN`, supervisor notified |

**Exit:** Reservation held, ready to build.

---

## 7. Stage 5 — Build

**Trigger:** An open reservation with no allocated serial.
**Actor:** Warehouse technician.

### Steps

1. Technician selects a reservation; system proposes a chassis — `AVAILABLE`, correct form factor,
   **cheapest qualifying**.
2. System lists the components required and their locations.
3. Technician fits components and records what was fitted.
4. Ledger entries written, reason `BUILD_CONSUME`. `on_hand` and `reserved` both decrease.
5. Unit configuration recorded against the chassis.

### Rules

| Rule | Reason |
|---|---|
| Cheapest qualifying chassis wins | Prevents burning margin on over-specified stock |
| Component consumption is recorded at fit time, not at ship time | Stock must reflect reality continuously |
| Incompatible builds are refused | See below |

### Compatibility refusals

A build is blocked where:

- RAM form factor does not match the chassis (SODIMM into a TOWER)
- RAM total exceeds the chassis model's maximum
- Module count exceeds available slots
- Storage interface is unsupported by the chassis

**Exit:** Unit physically built, awaiting audit.

---

## 8. Stage 6 — Audit

**Trigger:** Unit built, or unit returned, or recheck requested.
**Actor:** Warehouse technician, via Aiken.

The audit is the **only** authority on what a machine is.

### Steps

1. Connect the unit to Aiken. Aiken reads serial, part number, CPU, memory, storage.
2. System ingests the record and stores the **complete raw payload**, unmodified.
3. Normalisation applied — CPU strings, storage strings, part numbers.
4. **Form factor resolution runs** (see `formfactor-resolver-spec.md`).
5. Audit reconciled against what the technician recorded as fitted.
6. On success, chassis becomes `AVAILABLE` with a known specification.

### Form factor resolution, in brief

```
memory is SODIMM              → TINY
model name states it          → as stated
part number is unambiguous    → from the lookup table
otherwise                     → REVIEW QUEUE, never a guess
```

### Rules

| Rule | Reason |
|---|---|
| The audit overrides the technician's record | Hardware is the authority; discrepancies are logged, not silently accepted |
| Raw payload stored in full, forever | Allows re-derivation when a rule is later found wrong |
| Aiken's own `Chassis` field is stored but **never used** | It cannot express TINY — zero occurrences in 1,329 units |
| CPU T-suffix must never influence form factor | This is the current production defect |
| Incomplete audits do not enter stock | Observed: a unit with a listing title typed into the model field and no specs at all |

### Exceptions

| Case | Queue reason |
|---|---|
| Missing CPU, RAM or storage | `INCOMPLETE_AUDIT` |
| Part number absent or invalid, nothing else resolved it | `NO_PART_NUMBER` |
| Valid code not in the lookup table | `UNKNOWN_PART_NUMBER` |
| Dell DIMM unit — SFF vs Tower indeterminable | `AMBIGUOUS_DELL_DIMM` |
| Two reliable signals disagree | `SIGNAL_CONFLICT` |
| Audit disagrees with recorded fit | Discrepancy logged, supervisor review |

**Exit:** Chassis `AVAILABLE`, or in a review queue.

---

## 9. Stage 7 — Allocation

**Trigger:** Technician scans a built unit.
**Actor:** Warehouse technician.

**This stage is inverted from the current process.** Today the scan *validates* against a
pre-assigned SKU and rejects on mismatch. Here the scan *resolves* — it asks which open orders this
machine can fill.

### Steps

1. Scan the serial.
2. System finds every open order line the unit satisfies (§9.1).
3. Candidates scored; tightest fit ranked first (§9.2).
4. Technician confirms; allocation created.
5. Chassis → `ALLOCATED`; reservation consumed.

### 9.1 Match rules

| Attribute | Rule |
|---|---|
| Form factor | Exact |
| CPU | Equivalence class, not numeric comparison |
| RAM | `≥` or `=`, per the listing's match mode |
| Storage size | `≥` or `=`, per match mode |
| Storage type | Exact unless requirement is ANY |
| OS | Exact |
| Grade | Unit grade at least the required grade |

### 9.2 Scoring

Any-valid-match ships a 32GB unit against a 16GB order. Candidates are scored on over-specification
and age; **lowest over-spec wins**, with older stock preferred as a tiebreak.

### Scan outcomes

| Case | Behaviour |
|---|---|
| One match | Allocate, confirm |
| Several | Ranked list, technician selects |
| None | **Show which attribute failed**, against the nearest orders |
| Unit not `AVAILABLE` | Show current status and reason |

The "show why" requirement is not cosmetic. Opaque rejection is what drives staff to manual
workarounds today.

### Override

A supervisor may force an allocation. Requires a reason, records the actor, flags the shipment.
Override rate is monitored — a rising rate means the rules are wrong and should be fixed rather than
bypassed.

**Exit:** Serial bound to an order line.

---

## 10. Stage 8 — Fulfilment

**Trigger:** Allocation confirmed.
**Actor:** Warehouse technician, then system.

### Steps

1. Shipment record created.
2. Weight and dimensions derived from the chassis model.
3. Label purchased via the carrier API.
4. Unit packed and dispatched.
5. Tracking number pushed to the channel.
6. Chassis → `SHIPPED`.
7. Invoice raised and pushed to Zoho Books.

### Rules

| Rule | Reason |
|---|---|
| Weight comes from the chassis model, not a default | **Form factor drives shipping cost** — a tower is several times an SFF's weight |
| Tracking pushed within the channel's SLA | Late tracking damages account health |
| Books receives daily summaries, not per-serial detail | Books cares about money, not machines |

**Exit:** Unit shipped, revenue recorded.

---

## 11. Stage 9 — Returns

**Trigger:** Customer requests a return. RMA raised.

Three paths.

### 11.1 Refund

1. RMA type `REFUND`. Unit received. Chassis → `RETURNED`.
2. **Mandatory re-audit.** Compare against the audit taken at shipping.
3. Outcome:
   - **Identical** → regrade if needed, back to `AVAILABLE`
   - **Different** → components changed or removed; log discrepancy, adjust component stock, update
     configuration, regrade
   - **Damaged** → `SCRAP`, harvest usable components (§4)
4. Refund recorded, pushed to Books.

> **The re-audit is mandatory.** Today this varies. A unit returning without re-audit carries the
> specification it had when it left — which may be false. It then fails at the next scan, or worse,
> ships to another customer with the wrong hardware. This is a distinct error source from the form
> factor defect and produces similar symptoms.

### 11.2 Replacement

1. RMA type `REPLACEMENT`.
2. New reservation created against the **original order line**.
3. A second unit is built or allocated. **Second allocation on the same line.**
4. Original allocation marked `REPLACED`.
5. Returning unit follows the refund path from step 2.
6. Cost of both units attributed to the original order.

One order line therefore carries multiple allocations. This must be expressible; the current system
cannot represent it cleanly.

### 11.3 No-return replacement

Customer keeps the machine; a component is shipped.

1. RMA type `NO_RETURN_REPLACEMENT`.
2. Component issued from stock, ledger reason `NRR_SHIPMENT`, linked to the order.
3. **Unit configuration updated** to reflect the new field state.
4. Chassis flagged `field_modified`, with a note.
5. Component cost attributed to the original order.

> Step 3 is the one usually missed. Without it your record of that machine is permanently wrong, and
> if it ever returns the re-audit shows a discrepancy that is actually your own shipment.
> `field_modified` also protects the customer — a returning unit differing from its shipping audit is
> not necessarily tampering.

---

## 12. Cross-cutting behaviour

### 12.1 The single authority rule

Form factor and specification are determined **once**, from hardware, at audit.

Not from the supplier file. Not from the purchase order. Not from the listing. Not from a previously
assigned SKU.

Deciding it twice — once from paperwork at intake, once from hardware at audit — is one of the two
root causes of the current failures. This workflow decides it once.

### 12.2 Availability

Published quantity for a listing is computed, never stored:

```
buildable = min(
    qualifying AVAILABLE chassis,
    min over each required component of floor(available / needed)
)

published = max(0, buildable − open reservations − channel buffer)
```

| Rule | Reason |
|---|---|
| Computed on demand, cached briefly | A stored counter drifts on every event |
| Buffer per channel | Amazon penalises cancellations far more than eBay |
| Pushed on change, not on a timer | A timer guarantees a stale window |
| Never published where requirements are unresolved | Unsellable is safer than oversold |

**This calculation is only possible because components are in the system.** It is the main thing
that change unlocks.

### 12.3 Review queues

Every "stop" path terminates in a queue. Queues are core functionality, not error handling.

| Queue | Resolution |
|---|---|
| Ambiguous form factor (Dell DIMM) | Manufacturer lookup link + three buttons |
| Unknown part number | Classify once; permanent thereafter |
| Incomplete audit | Re-audit |
| Signal conflict | Physical inspection |
| Build discrepancy | Investigate |
| Return discrepancy | Adjust stock, regrade |
| At-risk order | Source, substitute or cancel |

**Every resolution writes back to reference data**, so the same question is never asked twice. This
is what makes queues shrink instead of becoming permanent labour.

### 12.4 Recording

Every state change records actor and timestamp. Required for tracing errors and for warranty claims.

---

## 13. Costing

### 13.1 Unit cost

```
unit_cost = chassis_cost_basis + Σ(component cost consumed)
```

Labour is not included in v1.

### 13.2 Lot allocation

**Rule: even spread across usable chassis.**

```
cost_per_chassis = lot_total / count(chassis where status ≠ SCRAP)
```

Harvested components enter at zero cost. Deliberately simple. **Apply consistently** — changing the
rule later makes historical margins incomparable.

### 13.3 Return costs

Refund, replacement and no-return replacement costs all attribute to the **original order**. Without
this, true margin on problem orders is invisible.

---

## 14. Exception summary

Every path where the system stops rather than proceeds.

| Stage | Condition | Outcome |
|---|---|---|
| Intake | Bad or duplicate serial | Row rejected |
| Order | Cannot reserve | Order accepted, flagged `AT_RISK` |
| Build | Incompatible component | Build refused |
| Audit | Incomplete record | Review queue |
| Audit | Form factor unresolvable | Review queue |
| Audit | Signals conflict | Review queue |
| Audit | Fit disagrees with audit | Discrepancy logged |
| Allocation | No matching order | Reason shown, no allocation |
| Return | Post-return audit differs | Discrepancy, stock adjusted |

**In no case does the system guess or apply a default.** Guessing is the root cause of the current
failures.

---

## 15. Open items

| # | Item | Affects |
|---|---|---|
| O1 | `RAM1Type` availability in `Units_Reports` | Stage 6 — fallback exists |
| O2 | Dell SFF vs Tower automation | Stage 6 — may remove one queue |
| O3 | `AT_RISK` escalation policy | Stage 4 — cancel, source, or substitute upward? |
| O4 | Component substitution rules | Stage 7 — may a 512GB drive fill a 256GB build when short? |
| O5 | Grade assignment criteria | Stages 6 and 11 |
| O6 | Multi-unit order handling at volume | Stages 4 and 7 |

---

## 16. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-08-11 | Initial workflow spec; components recorded in-system throughout |
