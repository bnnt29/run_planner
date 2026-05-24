"""Data-driven end-to-end validation tests for flow-plan JSON files.

Each test case in tests/validation_cases consists of two files:

- <name>.plan.json
  Input snapshot that is passed to compute_sat_validation.
- <name>.expected.json
  Expected validation outcome for paths and checkpoint stations.

Expected file format:

{
  "paths": {
    "1": {"state": "VALID"},
    "2": {"state": "INVALID", "reason_contains": ["bedingungen"]}
  },
  "stations": {
        "end": {
            "levels": [0],
            "witness_paths": [
                {
                    "from_root": "start",
                    "station_path": ["start", "end"],
                    "edge_path": [1]
                }
            ]
        },
    "dead_end": {"levels": []}
  }
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import run_planner.sat_validation as sat_validation_module
from run_planner.items import CONNECTION_STATE


CASE_DIR = Path(__file__).parent / "validation_cases"


def _collect_case_names() -> list[str]:
    if not CASE_DIR.exists():
        return []
    names = []
    for plan_file in sorted(CASE_DIR.glob("*.plan.json")):
        names.append(plan_file.name.removesuffix(".plan.json"))
    return names


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_plan_data(plan_data: dict) -> dict:
    normalized = dict(plan_data)

    for field in ("flow_conn_conditions", "connection_kinds"):
        raw = normalized.get(field, {})
        if isinstance(raw, dict):
            normalized[field] = {int(key): value for key, value in raw.items()}

    return normalized


def _assert_expected_paths(result: dict, expected: dict):
    best_states = result.get("best_states", {})

    for conn_key_str, conn_expected in expected.get("paths", {}).items():
        conn_key = int(conn_key_str)
        assert conn_key in best_states, f"Pfad {conn_key} fehlt im Validierungsergebnis"

        state, reasons = best_states[conn_key]
        assert isinstance(state, CONNECTION_STATE), f"Pfad {conn_key} hat keinen CONNECTION_STATE"

        expected_state = conn_expected.get("state")
        assert expected_state in CONNECTION_STATE.__members__, (
            f"Unbekannter erwarteter Zustand '{expected_state}' für Pfad {conn_key}"
        )
        assert state.name == expected_state, (
            f"Pfad {conn_key}: erwartet {expected_state}, erhalten {state.name}"
        )

        reason_contains = conn_expected.get("reason_contains", [])
        reason_text = " ".join(reasons).lower()
        for token in reason_contains:
            assert token.lower() in reason_text, (
                f"Pfad {conn_key}: erwarteter Reason-Text '{token}' nicht gefunden"
            )


def _assert_expected_stations(result: dict, expected: dict):
    checkpoint_levels = result.get("checkpoint_levels", {})
    checkpoint_paths = result.get("checkpoint_paths", {})

    for station_id, station_expected in expected.get("stations", {}).items():
        expected_levels = station_expected.get("levels", [])
        actual_levels = checkpoint_levels.get(station_id, [])
        assert actual_levels == expected_levels, (
            f"Station {station_id}: erwartete Levels {expected_levels}, erhalten {actual_levels}"
        )

        if "witness_paths" in station_expected:
            expected_paths = station_expected.get("witness_paths", [])
            actual_paths = checkpoint_paths.get(station_id, [])
            assert actual_paths == expected_paths, (
                f"Station {station_id}: erwartete witness_paths {expected_paths}, erhalten {actual_paths}"
            )


@pytest.mark.parametrize("case_name", _collect_case_names())
def test_validation_plan_case(case_name: str, monkeypatch):
    plan_path = CASE_DIR / f"{case_name}.plan.json"
    expected_path = CASE_DIR / f"{case_name}.expected.json"
    assert expected_path.exists(), f"Erwartungsdatei fehlt: {expected_path.name}"

    plan_data = _normalize_plan_data(_load_json(plan_path))
    expected_data = _load_json(expected_path)

    required_fields = {
        "station_data",
        "root_ids",
        "flow_conn_keys",
        "target_conn_keys",
        "checkpoint_ids",
        "target_checkpoint_ids",
        "flow_succs",
        "flow_conn_conditions",
    }
    if not required_fields.issubset(plan_data.keys()):
        pytest.skip(
            "Legacy-Export ohne Validierungs-Snapshot erkannt. Bitte Testfall neu über 'Als Testfall exportieren' erzeugen."
        )

    # Deterministisch und schnell: keine externe NuSMV-Ausführung in diesen Testfällen.
    monkeypatch.setattr(sat_validation_module, "_find_nusmv_binary", lambda: None)

    result = sat_validation_module.compute_sat_validation(plan_data)

    _assert_expected_paths(result, expected_data)
    _assert_expected_stations(result, expected_data)
