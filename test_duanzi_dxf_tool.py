import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf

from duanzi_dxf_tool import DRAWING, build_cables, build_dxf, parse_strips


def horizontal_wire_ys(doc, layer):
    """收集某层上所有横向（y1==y2）线条的 y 坐标。"""
    ys = set()
    for line in doc.modelspace().query("LINE"):
        if line.dxf.layer == layer and abs(line.dxf.start.y - line.dxf.end.y) < 1e-9:
            ys.add(round(line.dxf.start.y, 3))
    return ys


class TerminalLeadDistributionTests(unittest.TestCase):
    def build(self, cable_count):
        positions = {
            ("1-2UD", "4"): {"center": 12.5, "order": 0, "rowKey": "row"},
        }
        connections = [
            {
                "terminalBlock": "1-2UD",
                "terminal": "4",
                "cableNumber": "WL-%02d" % (index + 1),
                "toCabinet": "35kV PT柜",
            }
            for index in range(cable_count)
        ]
        cables, skipped = build_cables({"connections": connections}, positions)
        self.assertEqual([], skipped)
        return cables

    def test_single_lead_stays_centered(self):
        cables = self.build(1)
        self.assertEqual([12.5], [cable["points"][0]["leadX"] for cable in cables])

    def test_two_leads_are_centered_one_millimeter_apart(self):
        cables = self.build(2)
        self.assertEqual([12.0, 13.0], [cable["points"][0]["leadX"] for cable in cables])

    def test_three_leads_are_centered_and_ordered_near_to_far(self):
        cables = self.build(3)
        self.assertEqual([11.5, 12.5, 13.5], [cable["points"][0]["leadX"] for cable in cables])
        self.assertEqual(["WL-01", "WL-02", "WL-03"], [cable["number"] for cable in cables])

    def test_dxf_contains_two_distinct_vertical_leads_for_reused_terminal(self):
        params = {
            "projectName": "测试柜",
            "direction": "DOWN",
            "firstDistance": 10,
            "distanceStep": 5,
            "textHeight": 3,
            "terminalBlocks": [{"name": "1-2UD", "terminals": ["4"]}],
            "connections": [
                {"terminalBlock": "1-2UD", "terminal": "4", "cableNumber": "WL-01", "toCabinet": "35kV PT柜"},
                {"terminalBlock": "1-2UD", "terminal": "4", "cableNumber": "WL-02", "toCabinet": "35kV PT柜"},
            ],
        }
        with TemporaryDirectory() as folder:
            output = Path(folder) / "reused-terminal.dxf"
            build_dxf(params, DRAWING, output)
            doc = ezdxf.readfile(output)
            vertical_wire_xs = sorted({
                round(line.dxf.start.x, 6)
                for line in doc.modelspace().query("LINE")
                if line.dxf.layer == "电缆-接线" and abs(line.dxf.start.x - line.dxf.end.x) < 1e-9
            })
        self.assertEqual([12.0, 13.0], vertical_wire_xs)


class StripsDiscoveryTests(unittest.TestCase):
    def test_ordinary_format_is_one_default_strip(self):
        strips = parse_strips("ZD、1、11\nJD、1、4")
        self.assertEqual(1, len(strips))
        self.assertEqual("默认行", strips[0]["key"])
        self.assertEqual("ZD、JD", strips[0]["name"])
        self.assertEqual(4, strips[0]["terminals"])

    def test_coordinate_format_groups_by_x(self):
        text = "20453.52,-4715.01 1QD\n20453.52,-4720.01 1\n20572.02,-4716.29 CD\n20572.02,-4721.29 26"
        strips = parse_strips(text)
        self.assertEqual(["1QD", "CD"], [s["name"] for s in strips])
        self.assertEqual([1, 1], [s["terminals"] for s in strips])

    def test_empty_input_has_no_strips(self):
        self.assertEqual([], parse_strips(""))


class DirectionTests(unittest.TestCase):
    BLOCKS = [
        {"name": "1QD", "terminals": ["1"], "physicalGroup": "列1"},
        {"name": "CD", "terminals": ["26"], "physicalGroup": "列2"},
    ]
    WIRING = [
        {"terminalBlock": "1QD", "terminal": "1", "cableNumber": "WL-01", "toCabinet": "A柜"},
        {"terminalBlock": "CD", "terminal": "26", "cableNumber": "WL-02", "toCabinet": "B柜"},
    ]

    def build(self, directions=None):
        params = {
            "projectName": "测试柜",
            "direction": "DOWN",
            "firstDistance": 10,
            "distanceStep": 5,
            "textHeight": 3,
            "terminalBlocks": list(self.BLOCKS),
            "connections": list(self.WIRING),
        }
        if directions is not None:
            params["directions"] = directions
        with TemporaryDirectory() as folder:
            output = Path(folder) / "direction.dxf"
            result = build_dxf(params, DRAWING, output)
            return result, ezdxf.readfile(output)

    def test_default_direction_is_down_for_every_row(self):
        result, _ = self.build()
        self.assertEqual({"列1": False, "列2": False}, {r["key"]: r["up"] for r in result["rows"]})

    def test_mixed_directions_keep_rows_separated(self):
        result, _ = self.build(directions={"列1": "UP", "列2": "DOWN"})
        rows = {r["key"]: r for r in result["rows"]}
        self.assertTrue(rows["列1"]["up"])
        self.assertFalse(rows["列2"]["up"])

        def occupied(r):
            if r["up"]:
                return (r["blockY"], r["blockY"] + 75 + r["span"])   # 端子排在上，电缆区在其上方
            return (r["blockY"] - r["span"], r["blockY"] + 75)       # 电缆区在端子排下方

        a, b = occupied(rows["列1"]), occupied(rows["列2"])
        lower, higher = (a, b) if max(a) <= min(b) else (b, a)
        self.assertLessEqual(max(lower), min(higher), "两块端子排（含各自电缆区）不能重叠")

    def test_cable_lies_on_the_chosen_side_of_its_block(self):
        result, doc = self.build(directions={"列1": "UP", "列2": "DOWN"})
        rows = {r["key"]: r for r in result["rows"]}
        cable_ys = horizontal_wire_ys(doc, "电缆-接线")
        up, down = rows["列1"], rows["列2"]
        # 首根电缆 offset = firstDistance = 10 = span（单根时）
        self.assertIn(round(up["pinY"] + up["span"], 3), cable_ys, "向上块电缆应在 pin 线上方")
        self.assertIn(round(down["pinY"] - down["span"], 3), cable_ys, "向下块电缆应在 pin 线下方")
        self.assertGreater(round(up["pinY"] + up["span"], 3), round(up["blockY"] + 75, 3),
                           "向上电缆要高于该块顶部")
        self.assertLess(round(down["pinY"] - down["span"], 3), round(down["blockY"], 3),
                        "向下电缆要低于该块底部")


if __name__ == "__main__":
    unittest.main()
