"""Normalisation rules feeding the resolver (workflow-spec.md §6.1 decision sequence)."""

import re

from .models import AuditInput, FormFactor

_MODEL_NAME_MARKERS = (
    "OPTIPLEX",
    "THINKCENTRE",
    "ELITEDESK",
    "PRODESK",
    "LATITUDE",
    "INSPIRON",
    "THINKPAD",
)

_LENOVO_SUFFIX_FORM_FACTOR = {
    "Q": FormFactor.TINY,
    "S": FormFactor.SFF,
    "T": FormFactor.TOWER,
}
_LENOVO_MTQST_RE = re.compile(r"\bM\d{2}([QST])\b")

_HP_MODEL_MARKERS = (
    ("DESKTOP MINI", FormFactor.TINY),
    ("MT", FormFactor.TOWER),
    ("SFF", FormFactor.SFF),
)

_DELL_MODEL_MARKERS = (("MICRO", FormFactor.TINY),)

_CPU_PREFIX_RE = re.compile(r"^(INTEL|AMD)\s+")
_CPU_CLOCK_SUFFIX_RE = re.compile(r"\s+\d+(\.\d+)?\s*GHZ$")


def normalize_part_number(raw: str | None) -> str | None:
    """Strip/uppercase a part number; reject strings that are model text, not a code.

    Real case: a technician types "OptiPlex 9020M" (a model name) into the part
    number field. That must not be treated as a valid code.
    """
    if not raw:
        return None
    value = raw.strip().upper()
    if not value:
        return None
    if any(marker in value for marker in _MODEL_NAME_MARKERS):
        return None
    return value


def normalize_ram_form_factor(raw: str | None) -> str | None:
    """SODIMM must be checked before DIMM — "SODIMM" contains "DIMM" as a substring,
    and that ordering bug is the entire reason this component exists.
    """
    if not raw:
        return None
    value = raw.strip().upper()
    if "SODIMM" in value:
        return "SODIMM"
    if "DIMM" in value:
        return "DIMM"
    return None


def extract_form_factor_from_model(
    model_raw: str | None, manufacturer: str | None
) -> FormFactor | None:
    """Model name states its own form factor (decision-sequence step 4).

    Never raises on known-garbage values ("LENOVO PRODUCT", "OPTIPLEX 7060") — returns
    None so the caller falls through to the next signal. Lenovo's M##c (compact) suffix
    is deliberately left unmapped: it is real, but not q/s/t, so guessing at it would
    violate the never-guess principle.
    """
    if not model_raw:
        return None
    value = model_raw.strip().upper()
    if not value:
        return None
    mfr = (manufacturer or "").strip().upper()

    if mfr in ("LENOVO", ""):
        match = _LENOVO_MTQST_RE.search(value)
        if match:
            return _LENOVO_SUFFIX_FORM_FACTOR.get(match.group(1))

    if mfr in ("HP", ""):
        for marker, ff in _HP_MODEL_MARKERS:
            if marker in value:
                return ff

    if mfr in ("DELL", ""):
        for marker, ff in _DELL_MODEL_MARKERS:
            if marker in value:
                return ff

    return None


def normalize_cpu(raw: str | None) -> str | None:
    """Strip vendor prefix and trailing clock speed. Exists for reuse elsewhere only —
    the resolver must never call this. CPU must never influence form factor; the
    T-suffix rule is the current production defect this system replaces.
    """
    if not raw:
        return None
    value = raw.strip().upper()
    value = _CPU_PREFIX_RE.sub("", value)
    value = _CPU_CLOCK_SUFFIX_RE.sub("", value)
    return value.strip().title()


def is_complete(audit: AuditInput) -> bool:
    """A unit is rejected to REVIEW_QUEUE if CPU, RAM total, or storage is missing.

    Guards the observed case of a hand-typed marketplace listing title landing in the
    model field with every actual specification field empty.
    """
    return bool(audit.cpu_raw) and audit.ram_total_gb is not None and bool(audit.storage_raw)
