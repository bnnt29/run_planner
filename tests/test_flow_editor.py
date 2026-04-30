import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import flow_editor


def test_sanitize_snap_qt_env_removes_snap_runtime_keys(monkeypatch):
    monkeypatch.setenv("X_VSCODE_SNAP_ORIG", "1")
    for key in (
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GIO_MODULE_DIR",
        "GSETTINGS_SCHEMA_DIR",
        "LOCPATH",
        "GTK_IM_MODULE_FILE",
    ):
        monkeypatch.setenv(key, f"value-for-{key}")

    flow_editor._sanitize_snap_qt_env()

    for key in (
        "GTK_PATH",
        "GTK_EXE_PREFIX",
        "GIO_MODULE_DIR",
        "GSETTINGS_SCHEMA_DIR",
        "LOCPATH",
        "GTK_IM_MODULE_FILE",
    ):
        assert key not in os.environ
