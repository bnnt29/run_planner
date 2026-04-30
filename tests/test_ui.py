import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner import ui


class _FakeAttr:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name


class _FakeDropdown:
    def __init__(self):
        self.entries = []
        self.current_index = 0

    def clear(self):
        self.entries.clear()

    def addItem(self, text, data):
        self.entries.append((text, data))

    def findData(self, data):
        for idx, (_, value) in enumerate(self.entries):
            if value is data:
                return idx
        return -1

    def setCurrentIndex(self, index):
        self.current_index = index

    def count(self):
        return len(self.entries)

    def itemText(self, index):
        return self.entries[index][0]

    def currentData(self):
        return self.entries[self.current_index][1]


def test_fill_attribute_dropdown_deduplicates_and_selects_existing(monkeypatch):
    monkeypatch.setattr(ui, "AttributeItem", _FakeAttr)

    dropdown = _FakeDropdown()
    attr_a = _FakeAttr("a1", "Alpha")
    attr_b = _FakeAttr("a2", "Beta")

    ui.fill_attribute_dropdown(dropdown, attr_b, [attr_a, attr_b, attr_b])

    assert dropdown.count() == 2
    assert dropdown.currentData() is attr_b
    assert dropdown.itemText(0) == "Alpha"
    assert dropdown.itemText(1) == "Beta"


def test_fill_attribute_dropdown_adds_selected_when_missing(monkeypatch):
    monkeypatch.setattr(ui, "AttributeItem", _FakeAttr)

    dropdown = _FakeDropdown()
    attr_a = _FakeAttr("a1", "Alpha")
    selected = _FakeAttr("a9", "Selected")

    ui.fill_attribute_dropdown(dropdown, selected, [attr_a])

    assert dropdown.count() == 2
    assert dropdown.currentData() is selected
