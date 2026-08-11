"use strict";

/*
 * 「一键出 DXF」Python 脚本模板。
 * 整个模板是固定代码，导出时只把 __PARAMS__ 换成当前项目的参数区字面量
 * （生成的 JSON 只含字符串、数字、数组和对象，正好也是合法的 Python 字面量）。
 * 用 String.raw 保留 Python 里的反斜杠，模板内不要出现反引号或 ${。
 */
window.PYTHON_DXF_TEMPLATE = String.raw`# -*- coding: utf-8 -*-
"""端子排接线图 DXF 生成脚本

由「端子排接线规划器」工作流自动导出。整份脚本只有上方「参数区」随输入变化，
下方绘图代码固定不动。改完参数区重新运行即可。

用法：
    python 本文件.py                  # 在脚本同目录生成同名 .dxf
    python 本文件.py 输出路径.dxf     # 指定输出文件
    python 本文件.py --open           # 生成后用系统默认程序打开

依赖：ezdxf（缺少时执行 pip install ezdxf）
绘图约定：1 个图形单位 = 1mm，文字样式 HZ，宽度因子 0.7，色号 7（白底打印可见）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ==================== 参数区：随每次输入变化 ====================

PARAMS = __PARAMS__

# ==================== 以下为固定代码，一般不需要改 ====================

DRAWING = {
    "style": "HZ",              # 文字样式名
    "font": "txt.shx",
    "bigfont": "hztxt.shx",
    "widthFactor": 0.7,         # 宽度因子，同时写入样式和每个 TEXT 实体
    "color": 7,                 # 色号 7＝随背景黑白，白底打印可见
    "terminalWidth": 5.0,       # 端子格宽，固定 5
    "numberBandHeight": 5.0,    # 端子号栏高度，固定 5
    "blockNameWidth": 10.0,     # 端子排名称格宽
    "terminalZoneHeight": 10.0, # 端子号栏上下两个区的高度
    "trunkExtend": 18.0,        # 引线汇集后向右延伸长度
    "columnGap": 4.0,           # 列间距
    "chevronLength": 5.0,       # 去向箭头长度
    "numberColMin": 20.0,       # 电缆号列最小宽度
    "destColMin": 60.0,         # 去向列最小宽度
    "specColMin": 26.0,         # 规格列最小宽度
    "drawTitle": True,          # 是否画左上角标题文字
    "drawFrame": False,         # 是否画外框
    "layers": {
        "frame": "端子排-框线",
        "text": "端子排-文字",
        "wire": "电缆-接线",
        "label": "电缆-文字",
        "title": "图签-文字",
    },
}

CJK_START = 0x2E80


def natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(text))]


def text_width(value, height: float, factor: float) -> float:
    total = 0.0
    for char in str(value):
        total += 1.0 if ord(char) >= CJK_START else 0.55
    return total * height * factor
def build_columns(params, drawing):
    """端子排横向排布：返回端子坐标表、每块端子排的框线参数和总宽度。"""
    name_w = drawing["blockNameWidth"]
    term_w = drawing["terminalWidth"]
    positions = {}
    layouts = []
    cursor = 0.0
    order = 0
    for block in params["terminalBlocks"]:
        terminals = [str(t) for t in block["terminals"]]
        start_x = cursor
        first_x = start_x + name_w
        for index, terminal in enumerate(terminals):
            x = first_x + index * term_w
            positions[(block["name"], terminal)] = {"x": x, "center": x + term_w / 2.0, "order": order}
            order += 1
        width = name_w + max(1, len(terminals)) * term_w
        layouts.append({"name": block["name"], "terminals": terminals, "startX": start_x, "firstX": first_x, "width": width})
        cursor = start_x + width
    return positions, layouts, cursor


def build_cables(params, positions):
    """按电缆号分组，再按最左接线端子排序；返回电缆列表和被跳过的记录。"""
    groups = {}
    skipped = []
    for connection in params["connections"]:
        number = str(connection.get("cableNumber") or "").strip()
        key = (connection.get("terminalBlock"), str(connection.get("terminal")))
        if not number:
            skipped.append("%s-%s 缺少电缆号" % key)
            continue
        if key not in positions:
            skipped.append("%s-%s 端子不存在" % key)
            continue
        groups.setdefault(number, []).append(connection)
    cables = []
    for number, points in groups.items():
        points = sorted(points, key=lambda p: positions[(p["terminalBlock"], str(p["terminal"]))]["center"])
        leftmost = min(positions[(p["terminalBlock"], str(p["terminal"]))]["order"] for p in points)
        cables.append({
            "number": number,
            "points": points,
            "leftmost": leftmost,
            "destination": next((p.get("toCabinet") for p in points if p.get("toCabinet")), ""),
            "spec": next((p.get("cableSpec") for p in points if p.get("cableSpec")), ""),
        })
    cables.sort(key=lambda cable: (cable["leftmost"], natural_key(cable["number"])))
    return cables, skipped
def build_dxf(params, drawing, output: Path):
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    text_h = float(params.get("textHeight") or 3)
    factor = float(drawing["widthFactor"])
    color = int(drawing["color"])
    layers = drawing["layers"]
    term_w = drawing["terminalWidth"]
    zone_h = drawing["terminalZoneHeight"]
    band_h = drawing["numberBandHeight"]
    block_h = zone_h * 2 + band_h
    up = str(params.get("direction", "DOWN")).upper() == "UP"

    positions, layouts, total_w = build_columns(params, drawing)
    cables, skipped = build_cables(params, positions)
    # 端子格宽固定 5，旋转 90 度的文字高度就是它的横向占位，超过格宽会压线，这里自动收敛。
    cell_text_h = min(text_h, term_w - 1.5)
    if cell_text_h < text_h:
        skipped.append("端子排内文字高度由 %s 收敛到 %s，避免超出 %s 宽的端子格" % (text_h, cell_text_h, term_w))

    step = max(float(params.get("distanceStep") or 5), text_h * 1.6)
    first = float(params.get("firstDistance") or 10)
    span = first + max(0, len(cables) - 1) * step

    block_y = 0.0 if up else span
    band_y0 = block_y + zone_h
    band_y1 = band_y0 + band_h
    number_center = band_y0 + band_h / 2.0
    principle_center = (band_y1 + zone_h / 2.0) if up else (block_y + zone_h / 2.0)
    pin_y = (block_y + block_h) if up else block_y

    def lane_y(index: int) -> float:
        offset = first + index * step
        return pin_y + offset if up else pin_y - offset

    gap = drawing["columnGap"]
    bus_x = total_w + drawing["trunkExtend"]
    number_x = bus_x + gap
    number_w = max(drawing["numberColMin"], max([text_width(c["number"], text_h, factor) for c in cables] or [0]) + gap)
    chevron_x = number_x + number_w + gap
    chevron_tip = chevron_x + drawing["chevronLength"]
    dest_x = chevron_tip + gap * 0.75
    dest_w = max(drawing["destColMin"], max([text_width("至 " + str(c["destination"]), text_h, factor) for c in cables] or [0]) + gap * 1.5)
    spec_w = max(drawing["specColMin"], max([text_width(c["spec"] or "未填写", text_h, factor) for c in cables] or [0]) + gap * 1.5)
    right_x = dest_x + dest_w + spec_w
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # 毫米
    style_name = drawing["style"]
    style = doc.styles.new(style_name) if style_name not in doc.styles else doc.styles.get(style_name)
    style.dxf.font = drawing["font"]
    style.dxf.bigfont = drawing["bigfont"]
    style.dxf.width = factor
    for layer_name in layers.values():
        if layer_name not in doc.layers:
            doc.layers.new(layer_name, dxfattribs={"color": color})
    msp = doc.modelspace()

    def line(p1, p2, layer):
        msp.add_line(p1, p2, dxfattribs={"layer": layer, "color": color})

    def text(value, x, y, layer, align=TextEntityAlignment.MIDDLE_CENTER, rotation=0.0, height=None):
        content = str(value or "")
        if not content:
            return
        entity = msp.add_text(content, dxfattribs={
            "style": style_name, "height": height or text_h, "width": factor,
            "color": color, "layer": layer, "rotation": rotation,
        })
        entity.set_placement((x, y), align=align)

    # 端子排本体：外框、名称格、端子号栏上下两条横线、端子分隔线
    for layout in layouts:
        start_x = layout["startX"]
        first_x = layout["firstX"]
        end_x = start_x + layout["width"]
        line((start_x, block_y), (end_x, block_y), layers["frame"])
        line((end_x, block_y), (end_x, block_y + block_h), layers["frame"])
        line((end_x, block_y + block_h), (start_x, block_y + block_h), layers["frame"])
        line((start_x, block_y + block_h), (start_x, block_y), layers["frame"])
        line((first_x, block_y), (first_x, block_y + block_h), layers["frame"])
        line((first_x, band_y0), (end_x, band_y0), layers["frame"])
        line((first_x, band_y1), (end_x, band_y1), layers["frame"])
        for index in range(1, len(layout["terminals"])):
            x = first_x + index * term_w
            line((x, block_y), (x, block_y + block_h), layers["frame"])
        text(layout["name"], start_x + drawing["blockNameWidth"] / 2.0, block_y + block_h / 2.0, layers["text"], rotation=90.0, height=cell_text_h)
        for terminal in layout["terminals"]:
            center = positions[(layout["name"], terminal)]["center"]
            text(terminal, center, number_center, layers["text"], rotation=90.0, height=cell_text_h)

    # 原理号：同一端子有多条接线时取第一条
    principles = {}
    for connection in params["connections"]:
        key = (connection.get("terminalBlock"), str(connection.get("terminal")))
        if key in positions and connection.get("principle") and key not in principles:
            principles[key] = connection["principle"]
    for key, value in principles.items():
        text(value, positions[key]["center"], principle_center, layers["text"], rotation=90.0, height=cell_text_h)
    # 电缆：每层一根，层号就是最左接线端子的先后顺序
    arrow = text_h / 2.0
    for index, cable in enumerate(cables):
        y = lane_y(index)
        xs = [positions[(p["terminalBlock"], str(p["terminal"]))]["center"] for p in cable["points"]]
        for x in xs:
            line((x, pin_y), (x, y), layers["wire"])
        line((min(xs), y), (bus_x, y), layers["wire"])
        text(cable["number"], number_x, y, layers["label"], align=TextEntityAlignment.MIDDLE_LEFT)
        line((chevron_x, y - arrow), (chevron_tip, y), layers["wire"])
        line((chevron_x, y + arrow), (chevron_tip, y), layers["wire"])
        line((chevron_tip, y), (right_x, y), layers["wire"])
        text("至 " + str(cable["destination"] or "未填写"), dest_x, y + 1.0, layers["label"], align=TextEntityAlignment.BOTTOM_LEFT)
        text(cable["spec"] or "未填写", right_x, y + 1.0, layers["label"], align=TextEntityAlignment.BOTTOM_RIGHT)

    top_y = max(block_y + block_h, lane_y(len(cables) - 1) if (up and cables) else 0.0)
    bottom_y = min(block_y, lane_y(len(cables) - 1) if (not up and cables) else block_y)
    title_y = top_y + text_h * 3.0
    if drawing["drawTitle"]:
        title = str(params.get("projectName") or "")
        view = str(params.get("viewName") or "")
        label = " · ".join([part for part in (title, view) if part])
        text(label, 0.0, title_y, layers["title"], align=TextEntityAlignment.MIDDLE_LEFT, height=text_h * 1.5)
        note = "%d 块端子排 / %d 个端子 / %d 根电缆 / %s" % (
            len(layouts), len(positions), len(cables), "向上接线" if up else "向下接线")
        text(note, right_x, title_y, layers["title"], align=TextEntityAlignment.MIDDLE_RIGHT)
    if drawing["drawFrame"]:
        margin = text_h * 2.0
        x0, y0 = -margin, bottom_y - margin
        x1, y1 = right_x + margin, title_y + text_h * 2.0
        for p1, p2 in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            line(p1, p2, layers["frame"])

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {
        "cables": len(cables),
        "points": sum(len(c["points"]) for c in cables),
        "terminals": len(positions),
        "blocks": len(layouts),
        "skipped": skipped,
        "size": (round(right_x, 1), round(title_y + text_h - bottom_y, 1)),
    }
def verify(output: Path, drawing) -> bool:
    """回读校验：样式、实体数量和每个文字的宽度因子。"""
    import ezdxf
    doc = ezdxf.readfile(output)
    msp = doc.modelspace()
    texts = list(msp.query("TEXT"))
    lines = list(msp.query("LINE"))
    bad = [(entity.dxf.handle, entity.dxf.get("width", 1.0)) for entity in texts
           if abs(float(entity.dxf.get("width", 1.0)) - float(drawing["widthFactor"])) > 1e-9]
    ok = drawing["style"] in doc.styles and not bad and texts and lines
    print("校验：样式 %s=%s，LINE %d，TEXT %d，宽度因子异常 %d" % (
        drawing["style"], drawing["style"] in doc.styles, len(lines), len(texts), len(bad)))
    return bool(ok)


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    open_after = "--open" in argv
    script = Path(__file__).resolve()
    default_name = "-".join([part for part in (
        str(PARAMS.get("projectName") or "端子排"), str(PARAMS.get("viewName") or "")) if part])
    for bad_char in '\\/:*?"<>|':
        default_name = default_name.replace(bad_char, "_")
    output = Path(args[0]).resolve() if args else script.with_name(default_name + ".dxf")
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        print("缺少 ezdxf，请先执行：pip install ezdxf")
        return 2
    result = build_dxf(PARAMS, DRAWING, output)
    print("已生成：%s" % output)
    print("图形范围：%s × %s mm（1 个图形单位 = 1mm）" % result["size"])
    print("统计：%d 块端子排 / %d 个端子 / %d 根电缆 / %d 个接线点" % (
        result["blocks"], result["terminals"], result["cables"], result["points"]))
    for item in result["skipped"]:
        print("提示：%s" % item)
    if not verify(output, DRAWING):
        print("校验未通过，请检查上面的输出。")
        return 1
    if open_after:
        import os
        os.startfile(str(output))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
`;
