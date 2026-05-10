import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import pdf_helper
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QColor


class _SimplePrinter:
    DevicePixel = 0

    def pageRect(self, _mode=None):
        return QRectF(0, 0, 600, 400)
    def setResolution(self, *_):
        pass
    def setOutputFormat(self, *_):
        pass
    def setOutputFileName(self, *_):
        pass
    def setPageSize(self, *_):
        pass
    def setOrientation(self, *_):
        pass
    def setFullPage(self, *_):
        pass
    def newPage(self, *a, **k):
        pass


class _FakePainter:
    def __init__(self):
        self._active = True
        self._mocks = {}

    def isActive(self):
        return self._active

    def end(self):
        self._active = False

    def __getattr__(self, name):
        m = self._mocks.get(name)
        if m is None:
            m = Mock()
            self._mocks[name] = m
        return m


def test_export_pdf_cancel(monkeypatch, tmp_path):
    window = SimpleNamespace()
    window._choose_file = lambda **k: None
    window.statusBar = lambda: Mock()

    # should simply return without error
    pdf_helper.export_pdf(window)


def test_export_pdf_success(monkeypatch, tmp_path):
    chosen = str(tmp_path / "myplan")
    status = Mock()
    window = SimpleNamespace()
    window._choose_file = lambda **k: chosen
    window.statusBar = lambda: status
    # patch printer and painter used inside export_pdf
    class FakeQPrinter(_SimplePrinter):
        PdfFormat = 1
        A4 = 1
        Landscape = 1

    monkeypatch.setattr(pdf_helper, "QPrinter", FakeQPrinter)

    class FakePainter(_FakePainter):
        def __init__(self, printer):
            super().__init__()

    monkeypatch.setattr(pdf_helper, "QPainter", FakePainter)

    # provide a minimal scene so paint_pdf_* helpers can run
    scene = SimpleNamespace()
    scene.itemsBoundingRect = lambda: QRectF(0, 0, 100, 80)
    scene.sceneRect = lambda: QRectF(0, 0, 100, 80)
    scene.items = lambda: []
    scene._connections = []
    scene._connection_kind = lambda conn: getattr(conn, '_kind', None)
    scene.render = Mock()
    window.scene = scene

    pdf_helper.export_pdf(window)

    # exported filename should end with .pdf
    status.showMessage.assert_called()
    assert ".pdf" in status.showMessage.call_args[0][0]


def test_paint_pdf_flow_page_no_stations():
    scene = SimpleNamespace()
    scene.items = lambda: []
    scene._connections = []
    scene._connection_kind = lambda conn: getattr(conn, '_kind', None)
    scene.itemsBoundingRect = lambda: QRectF(0, 0, 100, 80)
    scene.sceneRect = lambda: QRectF(0, 0, 100, 80)

    window = SimpleNamespace(scene=scene)
    painter = Mock()
    printer = _SimplePrinter()

    pdf_helper.paint_pdf_flow_page(window, painter, printer)

    assert painter.drawText.called


def test_paint_pdf_flow_page_with_stations(monkeypatch):
    class FakeStation:
        def __init__(self, name="A", color="#2563EB", rules=None, conditions=0, effects=0):
            self.name = name
            self.color = color
            self.rules = rules or []
            self.conditions = [1] * conditions
            self.effects = [1] * effects

    class FakeConn:
        def __init__(self, src, dst, cond_count=1):
            self._kind = "flow"
            self.conditions = [1] * cond_count
            self.src_port = SimpleNamespace(parentItem=lambda: src)
            self.dst_port = SimpleNamespace(parentItem=lambda: dst)

        def pen(self):
            return SimpleNamespace(color=lambda: QColor("#123456"))

    # make pdf_helper treat our FakeStation as StationItem
    monkeypatch.setattr(pdf_helper, "_ui_types", lambda: (FakeStation, None))

    # Replace a few Qt classes that can trigger C++ code in headless tests
    class FakePath:
        def __init__(self, *a, **k):
            pass
        def addRoundedRect(self, *a, **k):
            pass
        def cubicTo(self, *a, **k):
            pass
        def pointAtPercent(self, p):
            return SimpleNamespace(x=lambda: 100 * p, y=lambda: 100 * p)
        def lineTo(self, *a, **k):
            pass

    monkeypatch.setattr(pdf_helper, "QPainterPath", FakePath)
    monkeypatch.setattr(pdf_helper, "QLinearGradient", lambda a, b: SimpleNamespace(setColorAt=lambda *a, **k: None))
    monkeypatch.setattr(pdf_helper, "QFontMetrics", lambda f: SimpleNamespace(boundingRect=lambda t: SimpleNamespace(width=lambda : max(10, len(t) * 4))))
    monkeypatch.setattr(pdf_helper, "QPolygonF", lambda lst: lst)
    monkeypatch.setattr(pdf_helper, "QColor", lambda *args, **kwargs: SimpleNamespace(lighter=lambda v: SimpleNamespace(), darker=lambda v: SimpleNamespace(), isValid=lambda: True, name=lambda: str(args[0] if args else None)))
    # simple pen/brush fakes so QPen/QBrush calls don't reach C++
    class FakeQPen:
        def __init__(self, color=None, width=None):
            self._color = color
            self._width = width
        def color(self):
            return self._color
        def setCapStyle(self, *a, **k):
            pass
        def setJoinStyle(self, *a, **k):
            pass

    class FakeQBrush:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(pdf_helper, "QPen", FakeQPen)
    monkeypatch.setattr(pdf_helper, "QBrush", FakeQBrush)

    s1 = FakeStation("S1")
    s2 = FakeStation("S2")
    conn = FakeConn(s1, s2, cond_count=2)

    scene = SimpleNamespace()
    scene.items = lambda: [s1, s2]
    scene._connections = [conn]
    scene._connection_kind = lambda conn: getattr(conn, '_kind', None)
    scene.itemsBoundingRect = lambda: QRectF(0, 0, 100, 80)
    scene.sceneRect = lambda: QRectF(0, 0, 100, 80)
    scene.render = Mock()

    window = SimpleNamespace(scene=scene)
    painter = Mock()
    printer = _SimplePrinter()

    pdf_helper.paint_pdf_flow_page(window, painter, printer)

    assert painter.drawPath.called
    assert painter.drawPolygon.called
    assert painter.drawText.called


def test_paint_pdf_clean_flow_page_no_stations():
    scene = SimpleNamespace()
    scene.items = lambda: []
    scene._connections = []
    scene._connection_kind = lambda conn: getattr(conn, '_kind', None)
    scene.itemsBoundingRect = lambda: QRectF(0, 0, 100, 80)
    scene.sceneRect = lambda: QRectF(0, 0, 100, 80)

    window = SimpleNamespace(scene=scene)
    painter = Mock()
    printer = _SimplePrinter()

    pdf_helper.paint_pdf_clean_flow_page(window, painter, printer)

    assert painter.drawText.called


def test_paint_pdf_clean_flow_page_with_states(monkeypatch):
    class FakeStation:
        def __init__(self, name):
            self.name = name
            self.color = "#2563EB"
            self.conditions = []
            self.effects = []

    # small enum-like namespace for connection states
    FakeCONNECTION_STATE = SimpleNamespace(
        VALID=1,
        INVALID=2,
        CONDITIONAL_INVALID=3,
        CONDITIONAL_VALID=4,
    )

    class FakeConn:
        def __init__(self, src, dst, state):
            self._kind = "flow"
            self.src_port = SimpleNamespace(parentItem=lambda: src)
            self.dst_port = SimpleNamespace(parentItem=lambda: dst)
            self._state = state

    monkeypatch.setattr(pdf_helper, "_ui_types", lambda: (FakeStation, FakeCONNECTION_STATE))

    # prevent Qt C++ calls that can crash in headless test environments
    class FakePath:
        def __init__(self, *a, **k):
            pass
        def addRoundedRect(self, *a, **k):
            pass
        def lineTo(self, *a, **k):
            pass

    monkeypatch.setattr(pdf_helper, "QPainterPath", FakePath)
    monkeypatch.setattr(pdf_helper, "QPolygonF", lambda lst: lst)
    monkeypatch.setattr(pdf_helper, "QColor", lambda *args, **kwargs: SimpleNamespace(lighter=lambda v: SimpleNamespace(), darker=lambda v: SimpleNamespace(), isValid=lambda: True, name=lambda: str(args[0] if args else None)))
    class FakeQPen:
        def __init__(self, color=None, width=None):
            self._color = color
            self._width = width
        def color(self):
            return self._color
        def setCapStyle(self, *a, **k):
            pass
        def setJoinStyle(self, *a, **k):
            pass

    class FakeQBrush:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(pdf_helper, "QPen", FakeQPen)
    monkeypatch.setattr(pdf_helper, "QBrush", FakeQBrush)

    s1 = FakeStation("A")
    s2 = FakeStation("B")
    c1 = FakeConn(s1, s2, FakeCONNECTION_STATE.VALID)

    scene = SimpleNamespace()
    scene.items = lambda: [s1, s2]
    scene._connections = [c1]
    scene._connection_kind = lambda conn: getattr(conn, '_kind', None)
    scene.itemsBoundingRect = lambda: QRectF(0, 0, 100, 80)
    scene.sceneRect = lambda: QRectF(0, 0, 100, 80)

    window = SimpleNamespace(scene=scene)
    painter = Mock()
    printer = _SimplePrinter()

    pdf_helper.paint_pdf_clean_flow_page(window, painter, printer)

    assert painter.drawPath.called
    assert painter.drawPolygon.called
