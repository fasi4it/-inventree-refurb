from pathlib import Path

import pytest

from formfactor import ChassisMap, ChassisMapEntry, FormFactor, load_chassis_map

_DATA_DIR = Path(__file__).resolve().parents[1] / "formfactor" / "data"


@pytest.fixture
def seeded_chassis_map() -> ChassisMap:
    """The real, shipped seed data: only the two spec-verified ambiguous Dell codes."""
    return load_chassis_map(_DATA_DIR / "chassis_map.csv")


@pytest.fixture
def synthetic_chassis_map() -> ChassisMap:
    """A small, clearly-synthetic map for exercising resolver branches the two-row
    verified seed doesn't reach. Never shipped as production truth.
    """
    entries = {
        "11CV-S0J": ChassisMapEntry(
            part_number="11CV-S0J",
            manufacturer="LENOVO",
            model_name="ThinkCentre M80s (synthetic)",
            form_factor=FormFactor.SFF,
            ambiguous=False,
            verified_by="test-fixture",
            notes="Synthetic — for resolver tests only.",
        ),
    }
    return ChassisMap(entries)
