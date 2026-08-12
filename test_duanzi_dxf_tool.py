import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf

from duanzi_dxf_tool import (DRAWING, build_cables, build_dxf, parse_strips, parse_terminals, parse_wiring,
                             resolve_reference)


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

    def test_single_letter_13d_is_recognized_as_coordinate_block_name(self):
        text = "20453.52,-4715.01 13D\n20453.52,-4720.01 1\n20453.52,-4725.01 2\n20453.52,-4730.01 3"
        strips = parse_strips(text)
        self.assertEqual(1, len(strips))
        self.assertEqual("13D", strips[0]["name"])
        self.assertEqual(3, strips[0]["terminals"])

    def test_numbered_bs_coordinate_block_keeps_terminals_1_to_20(self):
        lines = ["24665.54,7716.15 1-21BS"]
        lines.extend("24665.54,%.2f %d" % (7716.15 - number * 5, number) for number in range(1, 21))
        strips = parse_strips("\n".join(lines))
        self.assertEqual(1, len(strips))
        self.assertEqual("1-21BS", strips[0]["name"])
        self.assertEqual(20, strips[0]["terminals"])

    def test_numbered_ykd_coordinate_block_is_also_recognized(self):
        text = "24665.54,7716.15 1-21YKD\n24665.54,7711.15 1\n24665.54,7706.15 2"
        strips = parse_strips(text)
        self.assertEqual("1-21YKD", strips[0]["name"])
        self.assertEqual(2, strips[0]["terminals"])

    def test_empty_input_has_no_strips(self):
        self.assertEqual([], parse_strips(""))


class WiringParsingTests(unittest.TestCase):
    def test_principle_jd_901_is_not_split_as_jd_terminal(self):
        blocks, errors = parse_terminals("1-21YXD、15、16\nJD、1、2")
        self.assertEqual([], errors)
        connections, cables, errors, warnings = parse_wiring(
            "1-21YXD15、JD-901\n1-21YXD16、JD-903、电流接地选线及电能量采集柜",
            blocks, "本柜", "WL"
        )
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual(["JD-901", "JD-903"], [item["principle"] for item in connections])
        self.assertEqual(["15", "16"], [item["terminal"] for item in connections])
        self.assertEqual("电流接地选线及电能量采集柜", cables[0]["destination"])

    def test_valid_reference_still_splits_continuous_wiring_text(self):
        blocks, _ = parse_terminals("ZD、1、11")
        connections, _, errors, _ = parse_wiring(
            "ZD1、+KM1、ZD11、-KM1、直流馈线柜", blocks, "本柜", "WL"
        )
        self.assertEqual([], errors)
        self.assertEqual(["1", "11"], [item["terminal"] for item in connections])


class ColonReferenceTests(unittest.TestCase):
    """接线引用里半角/全角冒号在名称与编号交界处可有可无：ZD:2、ZD：2、ZD2 等价。"""

    BLOCKS, BLOCK_ERRORS = parse_terminals(
        "ZD、1、2、6、11\nJD、1、4\n1UD、1、3、6、8、11、13\n1ID、1、2"
    )

    CASES = [
        # 端子排, 端子号, 全部等价写法
        ("ZD", "2", "ZD2", "ZD:2", "ZD：2"),
        ("ZD", "6", "ZD6", "ZD:6", "ZD：6"),
        ("JD", "1", "JD1", "JD:1", "JD：1"),
        ("JD", "4", "JD4", "JD:4", "JD：4"),
        ("1UD", "1", "1UD1", "1UD:1", "1UD：1"),
        ("1UD", "3", "1UD3", "1UD:3", "1UD：3"),
        ("1UD", "6", "1UD6", "1UD:6", "1UD：6"),
        ("1UD", "8", "1UD8", "1UD:8", "1UD：8"),
        ("1UD", "11", "1UD11", "1UD:11", "1UD：11"),
        ("1UD", "13", "1UD13", "1UD:13", "1UD：13"),
        ("1ID", "1", "1ID1", "1ID:1", "1ID：1"),
        ("1ID", "2", "1ID2", "1ID:2", "1ID：2"),
    ]

    def setUp(self):
        self.assertEqual([], self.BLOCK_ERRORS)

    def test_colon_and_plain_forms_resolve_to_same_terminal(self):
        for block, terminal, plain, colon, colon_full in self.CASES:
            expected = {"block": block, "terminal": terminal}
            for ref in (plain, colon, colon_full):
                resolved, error = resolve_reference(ref, self.BLOCKS)
                self.assertEqual(expected, resolved, "%s 应解析成 %s" % (ref, expected))
                self.assertEqual("", error, "%s 不应报错" % ref)

    def test_bare_block_name_still_missing_terminal(self):
        resolved, error = resolve_reference("ZD:", self.BLOCKS)
        self.assertIsNone(resolved)
        self.assertIn("缺端子号", error)

    def test_colon_forms_parse_in_wiring_end_to_end(self):
        connections, cables, errors, warnings = parse_wiring(
            "ZD:2、+KM1\n1UD：11、A411\n1ID2、B411、直流馈线柜", self.BLOCKS, "本柜", "WL"
        )
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual([("ZD", "2"), ("1UD", "11"), ("1ID", "2")],
                         [(item["terminalBlock"], item["terminal"]) for item in connections])
        self.assertEqual(["+KM1", "A411", "B411"], [item["principle"] for item in connections])
        self.assertEqual("直流馈线柜", cables[0]["destination"])

    def test_colon_form_splits_continuous_wiring_text(self):
        connections, _, errors, _ = parse_wiring(
            "ZD1、+KM1、ZD:6、-KM1、直流馈线柜", self.BLOCKS, "本柜", "WL"
        )
        self.assertEqual([], errors)
        self.assertEqual([("ZD", "1"), ("ZD", "6")],
                         [(item["terminalBlock"], item["terminal"]) for item in connections])

    def test_jd_901_principle_still_protected_with_colon_present(self):
        # JD 只有 1、4 号端子；JD:901 不该被当成 JD 的 901 号端子，而该是原理号。
        connections, _, errors, _ = parse_wiring(
            "JD1、JD:901、JD4、JD-903、相邻屏柜", self.BLOCKS, "本柜", "WL"
        )
        self.assertEqual([], errors)
        self.assertEqual([("JD", "1"), ("JD", "4")],
                         [(item["terminalBlock"], item["terminal"]) for item in connections])
        self.assertEqual(["JD:901", "JD-903"], [item["principle"] for item in connections])


class QdComReferenceTests(unittest.TestCase):
    BLOCKS, BLOCK_ERRORS = parse_terminals("QD-COM、1、2、3、4、5、6、7、8")

    def setUp(self):
        self.assertEqual([], self.BLOCK_ERRORS)
        self.assertEqual("QD-COM", self.BLOCKS[0]["name"])

    def test_qd_com_is_recognized_as_a_block_name(self):
        blocks, errors = parse_terminals("ZD、1、QD-COM、1、2")
        self.assertEqual([], errors)
        self.assertEqual(["ZD", "QD-COM"], [block["name"] for block in blocks])

    def test_qd_colon_com_1_to_8_resolve_to_qd_com(self):
        for number in range(1, 9):
            expected = {"block": "QD-COM", "terminal": str(number)}
            for reference in ("QD:COM%d" % number, "QD：COM%d" % number, "QD-COM%d" % number):
                with self.subTest(reference=reference):
                    resolved, error = resolve_reference(reference, self.BLOCKS)
                    self.assertEqual(expected, resolved)
                    self.assertEqual("", error)

    def test_qd_colon_com_forms_parse_end_to_end(self):
        wiring = "、".join("QD:COM%d、P%d" % (number, number) for number in range(1, 8))
        wiring += "、QD:COM8、P8、去向柜"
        connections, cables, errors, warnings = parse_wiring(wiring, self.BLOCKS, "本柜", "WL")
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual([str(number) for number in range(1, 9)],
                         [item["terminal"] for item in connections])
        self.assertEqual("去向柜", cables[0]["destination"])


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

    def test_bian_annotation_geometry_and_text_positions(self):
        params = {
            "projectName": "测试柜",
            "direction": "DOWN",
            "firstDistance": 10,
            "distanceStep": 5,
            "textHeight": 3,
            "terminalBlocks": [{"name": "1QD", "terminals": ["1"]}],
            "connections": [{
                "terminalBlock": "1QD", "terminal": "1", "cableNumber": "UPS-12",
                "toCabinet": "直流馈线柜", "cableSpec": "",
            }],
        }
        with TemporaryDirectory() as folder:
            output = Path(folder) / "bian.dxf"
            build_dxf(params, DRAWING, output)
            doc = ezdxf.readfile(output)
            msp = doc.modelspace()
            triangle = next(iter(msp.query('LWPOLYLINE[layer=="电缆-接线"]')))
            points = [(round(p[0], 6), round(p[1], 6)) for p in triangle.get_points("xy")]
            tip_x, cable_y = points[0]
            horizontal = [
                item for item in msp.query('LINE[layer=="电缆-接线"]')
                if abs(item.dxf.start.y - item.dxf.end.y) < 1e-9
            ]
            line_right = max(max(item.dxf.start.x, item.dxf.end.x) for item in horizontal)
            labels = {item.dxf.text: item for item in msp.query('TEXT[layer=="电缆-文字"]')}

        self.assertTrue(triangle.closed)
        self.assertAlmostEqual(5.0, points[1][1] - points[2][1])
        self.assertAlmostEqual(40.0, line_right - tip_x)
        self.assertAlmostEqual(tip_x - 20.0, labels["UPS-12"].dxf.insert.x)
        self.assertAlmostEqual(tip_x + 1.5, labels["至直流馈线柜"].dxf.insert.x)
        self.assertAlmostEqual(tip_x + 32.0, labels["未填写"].dxf.insert.x)
        self.assertAlmostEqual(cable_y + 0.5, labels["UPS-12"].dxf.insert.y)


if __name__ == "__main__":
    unittest.main()
