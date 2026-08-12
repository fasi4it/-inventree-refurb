# InvenTree Build Roadmap — UI vs Code

For: PC Refresh World refurb BTO system
Stack already running: Docker Compose (Postgres 17, Redis 7, gunicorn, django-q, Caddy), project dir `inventree-refurb`, data bind-mounted at `inventree-data/`

---

## 1. The mental model

InvenTree is a finished Django application. You are **not** writing a Django app. You are configuring a running one, and extending it in three places only.

| Layer | What it is | Where it lives | When you use it |
|---|---|---|---|
| **A. UI / Settings** | Data and configuration | Browser | Categories, parts, parameters, BOMs, stock, users, report templates |
| **B. External scripts** | Your own Python, talking to InvenTree over the REST API | Your venv, outside the container | Bulk imports, Aiken ingest, channel sync, one-time migrations |
| **C. Plugins** | Python that runs *inside* InvenTree | `inventree-data/plugins/` | When InvenTree must react to its own events, validate its own data, or scan barcodes |
| **D. Core source** | InvenTree's own models and views | *(inside the image)* | **Never.** Touch this and you own every upgrade forever. |

### Decision rule

Ask yourself one question: *"Is this thing data, or is it behaviour?"*

- **Data or setup** → UI. Always. Even 500 parts — you import them, you don't code them.
- **Behaviour that runs outside, on your schedule** → external script (Layer B).
- **Behaviour that must fire when something happens inside InvenTree** → plugin (Layer C).

Start everything as an external script. Promote it to a plugin only when you genuinely need InvenTree to trigger it. This is the single most useful rule in this document — it will save you weeks.

---

## 2. Where each kind of code goes

### Layer B — external scripts (most of your code)

```
inventree-refurb/
├── docker-compose.yml
├── inventree-data/
└── scripts/                  ← you create this
    ├── config.py             ← API URL + token
    ├── import_supplier_file.py
    ├── aiken_ingest.py
    └── lib/
        └── mapping.py        ← chassis_map lookup logic
```

Plain Python. Uses the `inventree` client already in your venv:

```python
from inventree.api import InvenTreeAPI
from inventree.part import Part

api = InvenTreeAPI("http://localhost", token=TOKEN)
parts = Part.list(api, category=5)
```

No Django here. No models, no migrations, no `settings.py`. You never import InvenTree's models — you talk to it over HTTP like any other API. This is why it survives upgrades.

### Layer C — plugins (small amount of your code)

A plugin is a Python package with a class inheriting `InvenTreePlugin` plus the mixins you need. Scaffold it with the official **Plugin Creator** tool rather than writing the boilerplate by hand.

```
inventree-data/plugins/
└── refurb_plugin/
    ├── __init__.py
    ├── core.py               ← the plugin class
    └── static/               ← only if you add UI
```

The mixins that matter for your business:

| Mixin | What it gives you | Your use case |
|---|---|---|
| `SettingsMixin` | Config values in the InvenTree settings UI | API keys, toggles |
| `EventMixin` | Run code when something happens in InvenTree | Build completed → push stock to channels |
| `ScheduleMixin` | Run code on a timer inside InvenTree | Nightly Aiken pull |
| `ValidationMixin` | Validate serials, batch codes, part names | Reject a serial that doesn't match a known format |
| `BarcodeMixin` | Custom barcode scan handling | Warehouse scanning built units against picklists |
| `APICallMixin` | Helper for calling external APIs | Zoho, EasyPost |
| `UserInterfaceMixin` | Custom panels/dashboard items in the React UI | Later, if ever |

Two gotchas: plugins are **disabled by default** and must be enabled by a staff user in settings; and `UserInterfaceMixin` needs `ENABLE_PLUGINS_INTERFACE` switched on and requires JavaScript/React, not just Python. Don't start there.

For storing your own data on an InvenTree object (a channel order ID, an Aiken audit reference), use the `metadata` JSON field that every InvenTree model already has. Do not add database columns.

---

## 3. Phase by phase

### Phase 0 — Data model — **UI only** *(current step)*
Parameter templates, categories, 4 parts, 1 BOM, stock, one test build order.
**Done when:** a build order consumes RAM + SSD + chassis and produces a serialised finished unit.

### Phase 1 — Bulk load real parts — **Code (Layer B)**
`scripts/import_supplier_file.py`. Reads the supplier Excel, looks up form factor in `chassis_map`, creates parts and stock via the API. No match → writes to a review CSV, never guesses.
**Why code:** 1,345 rows. Also forces you to learn the API objects you'll use everywhere else.

### Phase 2 — Statuses, report and label templates — **UI only**
Custom stock states (needs testing / ready to sell / RMA), then label and report templates. Templates are HTML edited in the browser — no deployment, no code.

### Phase 3 — Aiken ingest — **Code (Layer B first)**
`scripts/aiken_ingest.py`: read the Aiken export, match on serial, write CPU/RAM/SSD onto the stock item, log the audit. Run it by hand until it's reliable.
**Promote to a plugin** (`ScheduleMixin`) only once it runs clean and you want it automatic.
**This is where the Dell form-factor problem gets solved** — Aiken reads the machine itself, so it beats guessing from a part number.

### Phase 4 — Serial validation + barcode scanning — **Plugin (Layer C)**
`ValidationMixin` and `BarcodeMixin`. Must be a plugin: this behaviour has to fire inside InvenTree the moment a warehouse worker scans, and no external script can intercept that.

### Phase 5 — Availability engine — **Code (Layer B)** ⚠️ highest risk
Your own service that answers: *given current component stock, how many of each channel listing can we actually promise?* Reads stock via the API, applies your build rules, writes per-channel quantities.
Keep this outside InvenTree. It's your business logic, it will change constantly, and it must never be trapped inside someone else's upgrade cycle.

### Phase 6 — Channel sync (6 marketplaces) — **Code (Layer B) + small plugin**
Script pulls orders in and creates sales orders; script pushes availability out. A thin `EventMixin` plugin fires "stock changed → mark channels dirty" so pushes are triggered rather than polled.

### Phase 7 — Shipping + accounting — **Code (Layer B)**
EasyPost/Shippo for labels, Zoho Books stays for accounting. Buy, don't build.

---

## 4. Your next three sessions

1. **Session 1 (now):** Phase 0 in the UI. Zero code.
2. **Session 2:** API token + `scripts/config.py`, then read your Phase 0 parts back out in Python. Ten lines. This is the bridge from clicking to coding.
3. **Session 3:** Phase 1 importer, one supplier file, dry-run mode first.

---

## 5. Rules to keep

- Never edit InvenTree core source, and never add a Django migration to it.
- Never store business data in a new database table. Use part parameters, custom states, or `metadata`.
- Every import script needs a dry-run mode before it writes anything.
- Anything unmatched goes to a review queue. Nothing is ever guessed. This is the exact failure that broke the Zoho setup.
- Form factor is stored data, never derived from CPU name or model text.