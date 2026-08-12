"""Structural invariants — source-level checks that keep two documented production
defects (CPU T-suffix deciding form factor; Aiken's unreliable Chassis field deciding
form factor) from silently creeping back into the resolver.
"""

import inspect

from formfactor import resolver as resolver_module
from formfactor.models import AuditInput
from formfactor.resolver import FormFactorResolver


def test_resolver_never_references_cpu_normalization():
    source = inspect.getsource(resolver_module)
    assert "normalize_cpu" not in source


def test_resolver_never_reads_chassis_field_raw():
    source = inspect.getsource(resolver_module)
    assert "chassis_field_raw" not in source


def test_resolve_is_pure(synthetic_chassis_map):
    resolver = FormFactorResolver(synthetic_chassis_map)
    audit = AuditInput(
        serial="PURE2",
        manufacturer="LENOVO",
        part_number_raw="11cv-s0j",
        ram_form_factor_raw="DIMM",
        cpu_raw="i5-8500",
        ram_total_gb=8,
        storage_raw="256GB SSD",
    )
    assert resolver.resolve(audit) == resolver.resolve(audit)


def test_invariant_holds_across_every_decision_path(seeded_chassis_map):
    resolver = FormFactorResolver(seeded_chassis_map)
    cases = [
        AuditInput(serial="A", product_type="LAPTOP"),
        AuditInput(serial="B", cpu_raw=None, ram_total_gb=None, storage_raw=None),
        AuditInput(
            serial="C",
            ram_form_factor_raw="SODIMM",
            cpu_raw="i5",
            ram_total_gb=8,
            storage_raw="256GB",
        ),
        AuditInput(
            serial="D",
            manufacturer="DELL",
            part_number_raw="0930",
            cpu_raw="i5",
            ram_total_gb=8,
            storage_raw="256GB",
        ),
        AuditInput(
            serial="E",
            part_number_raw="ZZ-UNKNOWN",
            cpu_raw="i5",
            ram_total_gb=8,
            storage_raw="256GB",
        ),
        AuditInput(serial="F", cpu_raw="i5", ram_total_gb=8, storage_raw="256GB"),
    ]
    for audit in cases:
        res = resolver.resolve(audit)
        assert (res.form_factor is None) != (res.queue_reason is None), audit
