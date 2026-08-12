from formfactor.models import AuditInput, FormFactor
from formfactor.normalize import (
    extract_form_factor_from_model,
    is_complete,
    normalize_cpu,
    normalize_part_number,
    normalize_ram_form_factor,
)


class TestNormalizePartNumber:
    def test_strips_and_uppercases(self):
        assert normalize_part_number("  11cv-s0j  ") == "11CV-S0J"

    def test_empty_is_none(self):
        assert normalize_part_number("") is None
        assert normalize_part_number(None) is None

    def test_model_text_rejected_not_a_code(self):
        # Observed real case: "OptiPlex 9020M" typed into the part number field.
        assert normalize_part_number("OptiPlex 9020M") is None

    def test_all_model_name_markers_rejected(self):
        for value in (
            "OptiPlex 7060",
            "ThinkCentre M80s",
            "EliteDesk 800",
            "ProDesk 600",
            "Latitude 5420",
            "Inspiron 3880",
            "ThinkPad T480",
        ):
            assert normalize_part_number(value) is None, value


class TestNormalizeRamFormFactor:
    def test_sodimm_detected(self):
        assert normalize_ram_form_factor("SODIMM") == "SODIMM"

    def test_dimm_detected(self):
        assert normalize_ram_form_factor("DIMM") == "DIMM"

    def test_sodimm_checked_before_dimm(self):
        # "SODIMM" contains "DIMM" as a substring — checking DIMM first would
        # misclassify every SODIMM unit. This ordering bug is why this module exists.
        assert normalize_ram_form_factor("SODIMM") != "DIMM"

    def test_unknown_is_none(self):
        assert normalize_ram_form_factor("LPDDR4X-nonsense") is None
        assert normalize_ram_form_factor(None) is None


class TestExtractFormFactorFromModel:
    def test_lenovo_q_is_tiny(self):
        assert extract_form_factor_from_model("ThinkCentre M80q", "LENOVO") == FormFactor.TINY

    def test_lenovo_s_is_sff(self):
        assert extract_form_factor_from_model("ThinkCentre M80s", "LENOVO") == FormFactor.SFF

    def test_lenovo_t_is_tower(self):
        assert extract_form_factor_from_model("ThinkCentre M80t", "LENOVO") == FormFactor.TOWER

    def test_lenovo_c_suffix_deliberately_unmapped(self):
        # M##c (compact) is a real Lenovo suffix but isn't q/s/t — guessing at it
        # would violate the never-guess principle, so it falls through to None.
        assert extract_form_factor_from_model("ThinkCentre M70c", "LENOVO") is None

    def test_hp_desktop_mini_is_tiny(self):
        assert (
            extract_form_factor_from_model("HP ProDesk 400 Desktop Mini", "HP")
            == FormFactor.TINY
        )

    def test_hp_mt_is_tower(self):
        assert extract_form_factor_from_model("HP EliteDesk 800 MT", "HP") == FormFactor.TOWER

    def test_hp_sff_is_sff(self):
        assert extract_form_factor_from_model("HP EliteDesk 800 SFF", "HP") == FormFactor.SFF

    def test_dell_micro_is_tiny(self):
        assert (
            extract_form_factor_from_model("OptiPlex 7060 Micro", "DELL") == FormFactor.TINY
        )

    def test_dell_without_micro_is_none(self):
        # Dell SFF and Tower share model name, memory type and every audited field —
        # this is the spec's documented ambiguous case (§8.1 step 6, "the Dell case").
        assert extract_form_factor_from_model("OptiPlex 7060", "DELL") is None

    def test_known_garbage_never_raises(self):
        for value in ("LENOVO PRODUCT", "HP PRODUCT", "OPTIPLEX 7060", "THINKCENTRE M70C"):
            extract_form_factor_from_model(value, None)  # must not raise

    def test_empty_model_is_none(self):
        assert extract_form_factor_from_model("", "DELL") is None
        assert extract_form_factor_from_model(None, "DELL") is None


class TestNormalizeCpu:
    def test_strips_intel_prefix_and_clock_speed(self):
        assert normalize_cpu("INTEL CORE I7-8700 3.20 GHZ") == "Core I7-8700"

    def test_strips_amd_prefix(self):
        assert normalize_cpu("AMD RYZEN 5 PRO 3400G") == "Ryzen 5 Pro 3400G"

    def test_empty_is_none(self):
        assert normalize_cpu(None) is None
        assert normalize_cpu("") is None


class TestIsComplete:
    def test_complete_audit(self):
        audit = AuditInput(
            serial="X1", cpu_raw="i5-8500", ram_total_gb=8, storage_raw="256GB SSD"
        )
        assert is_complete(audit) is True

    def test_missing_cpu(self):
        audit = AuditInput(
            serial="X1", cpu_raw=None, ram_total_gb=8, storage_raw="256GB SSD"
        )
        assert is_complete(audit) is False

    def test_missing_ram(self):
        audit = AuditInput(
            serial="X1", cpu_raw="i5-8500", ram_total_gb=None, storage_raw="256GB SSD"
        )
        assert is_complete(audit) is False

    def test_missing_storage(self):
        audit = AuditInput(
            serial="X1", cpu_raw="i5-8500", ram_total_gb=8, storage_raw=None
        )
        assert is_complete(audit) is False

    def test_hand_typed_listing_title_with_no_specs_is_incomplete(self):
        # Observed real case: a marketplace listing title typed into the model field,
        # with every actual specification field empty.
        audit = AuditInput(
            serial="X1",
            model_raw="HP EliteDesk 705 G4 | AMD RYZEN 5 PRO | RAM 16 | STORAGE 256 |",
            cpu_raw=None,
            ram_total_gb=None,
            storage_raw=None,
        )
        assert is_complete(audit) is False
