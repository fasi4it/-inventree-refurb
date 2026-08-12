"""Load and query the chassis part-number lookup table (workflow-spec.md §8.1 step 5).

CSV columns: part_number, manufacturer, model_name, form_factor, ambiguous, verified_by,
notes. A row that is not ambiguous but carries no form_factor is a meaningless
combination and is rejected at load time — the same never-guess principle that governs
the resolver also governs what is allowed to enter its reference data.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import FormFactor

_TRUE_VALUES = ("TRUE", "1", "YES")


@dataclass(frozen=True)
class ChassisMapEntry:
    part_number: str
    manufacturer: str
    model_name: str
    form_factor: FormFactor | None
    ambiguous: bool
    verified_by: str
    notes: str


class ChassisMap:
    def __init__(self, entries: dict[str, ChassisMapEntry]) -> None:
        self._entries = entries

    def get(self, part_number: str) -> ChassisMapEntry | None:
        return self._entries.get(part_number)

    def __len__(self) -> int:
        return len(self._entries)


def load_chassis_map(path: str | Path) -> ChassisMap:
    entries: dict[str, ChassisMapEntry] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            part_number = row["part_number"].strip().upper()
            if not part_number:
                continue
            if part_number in entries:
                raise ValueError(f"Duplicate part_number in chassis map: {part_number}")

            ambiguous = row.get("ambiguous", "").strip().upper() in _TRUE_VALUES
            raw_ff = row.get("form_factor", "").strip().upper()
            form_factor = FormFactor(raw_ff) if raw_ff else None

            if not ambiguous and form_factor is None:
                raise ValueError(
                    f"Chassis map row for {part_number} is not ambiguous but has no "
                    "form_factor — meaningless combination (workflow-spec.md §8.1)."
                )

            entries[part_number] = ChassisMapEntry(
                part_number=part_number,
                manufacturer=row.get("manufacturer", "").strip(),
                model_name=row.get("model_name", "").strip(),
                form_factor=form_factor,
                ambiguous=ambiguous,
                verified_by=row.get("verified_by", "").strip(),
                notes=row.get("notes", "").strip(),
            )
    return ChassisMap(entries)
