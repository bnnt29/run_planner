import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import pdf_helper


class _FakeStation:
    def __init__(self, name="Station", color="#2563EB", rules=None, conditions=0, effects=0):
        self.name = name
        self.color = color
        self.rules = rules or [SimpleNamespace(conditions=[1] * conditions, effects=[1] * effects)]
        self.conditions = [1] * conditions
        self.effects = [1] * effects


class _FakeConnection:
    def __init__(self, src_parent, dst_parent, kind="flow", cond_count=0):
        self._kind = kind
        self.conditions = [1] * cond_count
        self.src_port = SimpleNamespace(parentItem=lambda: src_parent)
        self.dst_port = SimpleNamespace(parentItem=lambda: dst_parent)


class _FakeScene:
    def __init__(self, stations=None, connections=None):
        self._stations = list(stations or [])
        self._connections = list(connections or [])
        self.render = Mock()

    def items(self):
        return list(self._stations)

    def itemsBoundingRect(self):
        from PyQt5.QtCore import QRectF

        return QRectF(0, 0, 100, 80)

    def sceneRect(self):
        from PyQt5.QtCore import QRectF

        return QRectF(0, 0, 100, 80)

    def _connection_kind(self, conn):
        return conn._kind


class _FakePrinter:
    DevicePixel = 0

    def pageRect(self, _mode=None):
        from PyQt5.QtCore import QRectF

        return QRectF(0, 0, 600, 400)


def test_paint_pdf_editor_page_renders_scene(monkeypatch):
    scene = _FakeScene([_FakeStation("A")])
    window = SimpleNamespace(scene=scene)
    painter = Mock()
    printer = _FakePrinter()

    pdf_helper.paint_pdf_editor_page(window, painter, printer)

    assert scene.render.called is True
    assert painter.translate.called is True
    assert painter.scale.called is True
