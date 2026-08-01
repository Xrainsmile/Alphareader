"""事件聚合链压平（_walk_to_root）单元测试。

链式聚合 A←B←C 需解析到最终根 A（星型拓扑），
否则前端分组/事件合成/hot-topics 全部漏数据。
"""

from app.services.pipeline import _walk_to_root


class TestWalkToRoot:
    def test_direct_child(self):
        """B→A（A 是根）：根就是 A。"""
        links = {"B": "A", "A": None}
        assert _walk_to_root("B", links) == "A"

    def test_chain_of_three(self):
        """C→B→A：C 的根是 A。"""
        links = {"C": "B", "B": "A", "A": None}
        assert _walk_to_root("C", links) == "A"

    def test_root_itself(self):
        links = {"A": None}
        assert _walk_to_root("A", links) == "A"

    def test_unknown_id_returned_as_is(self):
        """父 id 不在 links 里（查询失败降级）时原样返回。"""
        assert _walk_to_root("X", {}) == "X"

    def test_cycle_protection(self):
        """异常成环（A→B→A）时不死循环，返回环内节点。"""
        links = {"A": "B", "B": "A"}
        result = _walk_to_root("A", links)
        assert result in {"A", "B"}

    def test_long_chain(self):
        links = {f"N{i}": f"N{i+1}" for i in range(8)}
        links["N8"] = None
        assert _walk_to_root("N0", links) == "N8"
