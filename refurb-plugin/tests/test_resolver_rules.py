import pytest

from formfactor.models import AuditInput, FormFactor, QueueReason, Source
from formfactor.resolver import FormFactorResolver


def _assert_invariant(resolution):
    assert (resolution.form_factor is None) != (resolution.queue_reason is None)


@pytest.fixture
def resolver(synthetic_chassis_map):
    return FormFactorResolver(synthetic_chassis_map)


class TestLaptopShortCircuit:
    def test_laptop_short_circuits_before_completeness_check(self, resolver):
        audit = AuditInput(serial="L1", product_type="LAPTOP")
        res = resolver.resolve(audit)
        assert res.form_factor == FormFactor.LAPTOP
        assert res.source == Source.PRODUCT_TYPE
        _assert_invariant(res)


class TestIncompleteAudit:
    def test_missing_storage_queues(self, resolver):
        audit = AuditInput(serial="S1", cpu_raw="i5-8500", ram_total_gb=8, storage_raw=None)
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.INCOMPLETE_AUDIT
        _assert_invariant(res)


class TestSodimmPrecedence:
    def test_sodimm_decides_before_model_name_is_even_consulted(self, resolver):
        # Model name says TOWER, but SODIMM memory physically cannot fit a tower —
        # the two signals conflict and must queue, not silently pick one.
        audit = AuditInput(
            serial="S2",
            manufacturer="LENOVO",
            model_raw="ThinkCentre M80t",
            ram_form_factor_raw="SODIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.SIGNAL_CONFLICT
        _assert_invariant(res)

    def test_sodimm_decides_before_part_number_is_even_consulted(self, resolver):
        # Invalid part number, but SODIMM memory alone is enough to resolve TINY —
        # must not queue just because the paperwork is bad.
        audit = AuditInput(
            serial="S3",
            part_number_raw="not-a-real-code",
            ram_form_factor_raw="SODIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.form_factor == FormFactor.TINY
        assert res.source == Source.RAM_TYPE
        _assert_invariant(res)


class TestPartNumberOutcomes:
    def test_no_part_number_queues(self, resolver):
        audit = AuditInput(serial="P1", cpu_raw="i5-8500", ram_total_gb=8, storage_raw="256GB SSD")
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.NO_PART_NUMBER
        _assert_invariant(res)

    def test_part_number_field_holding_model_text_queues_as_no_part_number(self, resolver):
        audit = AuditInput(
            serial="P2",
            part_number_raw="OptiPlex 9020M",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.NO_PART_NUMBER
        _assert_invariant(res)

    def test_unknown_part_number_queues(self, resolver):
        audit = AuditInput(
            serial="P3",
            part_number_raw="ZZ-NOT-IN-TABLE",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.UNKNOWN_PART_NUMBER
        _assert_invariant(res)

    def test_ambiguous_dell_part_number_queues(self, seeded_chassis_map):
        # 0930 is one of the two spec-verified ambiguous Dell codes.
        resolver = FormFactorResolver(seeded_chassis_map)
        audit = AuditInput(
            serial="P4",
            manufacturer="DELL",
            part_number_raw="0930",
            ram_form_factor_raw="DIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.AMBIGUOUS_DELL_DIMM
        _assert_invariant(res)

    def test_known_part_number_resolves(self, resolver):
        audit = AuditInput(
            serial="P5",
            manufacturer="LENOVO",
            part_number_raw="11cv-s0j",
            ram_form_factor_raw="DIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.form_factor == FormFactor.SFF
        assert res.source == Source.PART_NUMBER
        _assert_invariant(res)


class TestSignalConflict:
    def test_model_name_vs_part_number_map_disagreement_queues(self, resolver):
        # Model name says TINY (Lenovo M80q); the part number map says SFF.
        audit = AuditInput(
            serial="C1",
            manufacturer="LENOVO",
            model_raw="ThinkCentre M80q",
            part_number_raw="11cv-s0j",
            ram_form_factor_raw="DIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.SIGNAL_CONFLICT
        _assert_invariant(res)

    def test_dimm_vs_model_name_tiny_disagreement_queues(self, resolver):
        audit = AuditInput(
            serial="C2",
            manufacturer="LENOVO",
            model_raw="ThinkCentre M80q",
            ram_form_factor_raw="DIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        res = resolver.resolve(audit)
        assert res.queue_reason == QueueReason.SIGNAL_CONFLICT
        _assert_invariant(res)


class TestChassisFieldNeverInfluencesDecision:
    def test_chassis_field_disagreement_does_not_queue_or_change_outcome(self, resolver):
        # Aiken's own Chassis field is stored elsewhere but must never influence the
        # decision — it cannot express TINY (zero occurrences in 1,329 units).
        audit = AuditInput(
            serial="X1",
            ram_form_factor_raw="SODIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
            chassis_field_raw="Desktop",
        )
        res = resolver.resolve(audit)
        assert res.form_factor == FormFactor.TINY
        _assert_invariant(res)


class TestPurity:
    def test_resolve_is_pure(self, resolver):
        audit = AuditInput(
            serial="PURE1",
            manufacturer="LENOVO",
            part_number_raw="11cv-s0j",
            ram_form_factor_raw="DIMM",
            cpu_raw="i5-8500",
            ram_total_gb=8,
            storage_raw="256GB SSD",
        )
        assert resolver.resolve(audit) == resolver.resolve(audit)
