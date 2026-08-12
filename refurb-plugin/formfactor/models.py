"""Dataclasses and enums for the form factor resolver (workflow-spec.md §6.1, §8.1)."""

from dataclasses import dataclass, field
from enum import StrEnum


class FormFactor(StrEnum):
    TINY = "TINY"
    USFF = "USFF"
    SFF = "SFF"
    TOWER = "TOWER"
    LAPTOP = "LAPTOP"


class Source(StrEnum):
    RAM_TYPE = "RAM_TYPE"
    MODEL_NAME = "MODEL_NAME"
    PART_NUMBER = "PART_NUMBER"
    PRODUCT_TYPE = "PRODUCT_TYPE"


class QueueReason(StrEnum):
    INCOMPLETE_AUDIT = "INCOMPLETE_AUDIT"
    NO_PART_NUMBER = "NO_PART_NUMBER"
    UNKNOWN_PART_NUMBER = "UNKNOWN_PART_NUMBER"
    AMBIGUOUS_DELL_DIMM = "AMBIGUOUS_DELL_DIMM"
    SIGNAL_CONFLICT = "SIGNAL_CONFLICT"


@dataclass(frozen=True)
class AuditInput:
    serial: str
    manufacturer: str | None = None
    model_raw: str | None = None
    part_number_raw: str | None = None
    product_type: str | None = None
    ram_form_factor_raw: str | None = None
    cpu_raw: str | None = None
    ram_total_gb: int | None = None
    storage_raw: str | None = None
    optical_raw: str | None = None
    chassis_field_raw: str | None = None


@dataclass(frozen=True)
class Resolution:
    form_factor: FormFactor | None
    source: Source | None
    queue_reason: QueueReason | None
    part_number: str | None
    detail: str
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (self.form_factor is None) == (self.queue_reason is None):
            raise ValueError(
                "Resolution invariant violated: exactly one of form_factor/queue_reason "
                "must be set. The resolver must never guess and must never leave a unit "
                "in an undetermined-but-not-queued state (workflow-spec.md §14)."
            )
