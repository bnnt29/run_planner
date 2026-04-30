import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from run_planner.items import CONDITION_OP, EFFECT_OP, Condition, Effect, StationItem, StationRule


class DummyAttr:
    def __init__(self, node_id: str, name: str):
        self.node_id = node_id
        self.name = name

def test_station_item_deserializers_ignore_missing_nodes():
    attr = DummyAttr("a1", "Attr A")
    cond_data = {"attribute": "a1", "compare_attribute": "a2", "operator": CONDITION_OP.EXISTS.value}
    eff_data = {"attribute": "a1", "action": EFFECT_OP.SET.value, "value": 7}

    cond = StationItem._deserialize_condition(cond_data, {"a1": attr})
    eff = StationItem._deserialize_effect(eff_data, {"a1": attr})

    assert cond is not None
    assert cond.attribute is attr
    assert StationItem._deserialize_condition({"attribute": "missing"}, {"a1": attr}) is None
    assert eff is not None
    assert eff.attribute is attr
    assert StationItem._deserialize_effect({"attribute": "missing"}, {"a1": attr}) is None
