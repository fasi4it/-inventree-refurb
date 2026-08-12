"""The form factor resolution algorithm (workflow-spec.md §8.1, §12.1).

Memory type is evaluated before the part-number gate: a unit with an invalid or
unrecognised part number but SODIMM memory is unambiguously TINY (a physical
constraint — tiny chassis cannot accept full-height memory) and must not queue just
because its paperwork is bad.

Deliberately excluded from every decision in this module: CPU (the T-suffix rule is
the current production defect) and Aiken's own reported chassis type (it cannot
express TINY — zero occurrences in 1,329 units). Both are stored elsewhere for
diagnostics, never consulted here.
"""

from .chassis_map import ChassisMap, ChassisMapEntry
from .models import AuditInput, FormFactor, QueueReason, Resolution, Source
from .normalize import (
    extract_form_factor_from_model,
    is_complete,
    normalize_part_number,
    normalize_ram_form_factor,
)

_RELIABLE_MAP_FORM_FACTORS = (FormFactor.SFF, FormFactor.TOWER)


def _is_laptop(product_type: str | None) -> bool:
    return bool(product_type) and product_type.strip().upper() == "LAPTOP"


class FormFactorResolver:
    """Injected with a ChassisMap at construction. resolve() does no file reads, no
    network calls, no clock reads — calling it twice with the same input always
    returns an identical result.
    """

    def __init__(self, chassis_map: ChassisMap) -> None:
        self._chassis_map = chassis_map

    def resolve(self, audit: AuditInput) -> Resolution:
        part_number = normalize_part_number(audit.part_number_raw)

        if _is_laptop(audit.product_type):
            return Resolution(
                form_factor=FormFactor.LAPTOP,
                source=Source.PRODUCT_TYPE,
                queue_reason=None,
                part_number=part_number,
                detail="Product type reported as LAPTOP.",
            )

        if not is_complete(audit):
            return Resolution(
                form_factor=None,
                source=None,
                queue_reason=QueueReason.INCOMPLETE_AUDIT,
                part_number=part_number,
                detail="Audit is missing CPU, RAM total, or storage.",
            )

        mem = normalize_ram_form_factor(audit.ram_form_factor_raw)
        model_ff = extract_form_factor_from_model(audit.model_raw, audit.manufacturer)
        entry: ChassisMapEntry | None = (
            self._chassis_map.get(part_number) if part_number is not None else None
        )

        if mem == "SODIMM":
            resolved_ff, source = FormFactor.TINY, Source.RAM_TYPE
        elif model_ff is not None:
            resolved_ff, source = model_ff, Source.MODEL_NAME
        elif part_number is None:
            return Resolution(
                form_factor=None,
                source=None,
                queue_reason=QueueReason.NO_PART_NUMBER,
                part_number=None,
                detail="No valid part number, and no other signal resolved the unit.",
            )
        elif entry is None:
            return Resolution(
                form_factor=None,
                source=None,
                queue_reason=QueueReason.UNKNOWN_PART_NUMBER,
                part_number=part_number,
                detail=f"Part number {part_number} is not in the chassis map.",
            )
        elif entry.ambiguous or entry.form_factor is None:
            return Resolution(
                form_factor=None,
                source=None,
                queue_reason=QueueReason.AMBIGUOUS_DELL_DIMM,
                part_number=part_number,
                detail=f"Part number {part_number} does not determine form factor on its own.",
            )
        else:
            resolved_ff, source = entry.form_factor, Source.PART_NUMBER

        conflicts = self._cross_check(mem=mem, model_ff=model_ff, entry=entry)

        if conflicts:
            return Resolution(
                form_factor=None,
                source=None,
                queue_reason=QueueReason.SIGNAL_CONFLICT,
                part_number=part_number,
                detail="Reliable signals disagree: " + "; ".join(conflicts),
                conflicts=tuple(conflicts),
            )

        return Resolution(
            form_factor=resolved_ff,
            source=source,
            queue_reason=None,
            part_number=part_number,
            detail=f"Resolved via {source.value}.",
        )

    @staticmethod
    def _cross_check(
        *,
        mem: str | None,
        model_ff: FormFactor | None,
        entry: ChassisMapEntry | None,
    ) -> list[str]:
        conflicts: list[str] = []

        if mem == "SODIMM" and model_ff in _RELIABLE_MAP_FORM_FACTORS:
            conflicts.append(f"RAM type SODIMM disagrees with model name ({model_ff.value})")

        if mem == "DIMM" and model_ff == FormFactor.TINY:
            conflicts.append("RAM type DIMM disagrees with model name (TINY)")

        map_ff = entry.form_factor if entry is not None and not entry.ambiguous else None

        if mem == "SODIMM" and map_ff in _RELIABLE_MAP_FORM_FACTORS:
            conflicts.append(f"RAM type SODIMM disagrees with part number map ({map_ff.value})")

        if model_ff is not None and map_ff is not None and map_ff != model_ff:
            conflicts.append(
                f"Model name ({model_ff.value}) disagrees with part number map ({map_ff.value})"
            )

        return conflicts
