# -*- coding: utf-8 -*-
"""端子排出图工具（简易版）

双击 `出图工具.cmd`（或运行 python 出图工具.py）后浏览器会自动打开一个很简单的页面：
两个输入框 + 一个按钮，点一下就在桌面生成 DXF 并自动用 CAD 打开。

不需要学习界面，也不需要先生成脚本。想要可视化核对、逐条编辑、导出 SVG 时
再用同目录的 index.html（完整版）。

依赖：ezdxf（缺少时执行 pip install ezdxf）
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FIELD_SPLIT = re.compile(r"[\t,，、]")
RECORD_SPLIT = re.compile(r"[;；\r\n]+")
CJK_START = 0x2E80

DRAWING = {
    "style": "HZ",
    "font": "txt.shx",
    "bigfont": "hztxt.shx",
    "widthFactor": 0.7,
    "color": 7,
    "terminalWidth": 5.0,
    "numberBandHeight": 5.0,
    "blockNameWidth": 10.0,
    "terminalZoneHeight": 10.0,
    "trunkExtend": 18.0,
    "columnGap": 4.0,
    "chevronLength": 5.0,
    "numberColMin": 20.0,
    "destColMin": 60.0,
    "specColMin": 26.0,
    "drawTitle": True,
    "drawFrame": False,
    "layers": {
        "frame": "端子排-框线",
        "text": "端子排-文字",
        "wire": "电缆-接线",
        "label": "电缆-文字",
        "title": "图签-文字",
    },
}

DEFAULTS = {"direction": "DOWN", "firstDistance": 10, "distanceStep": 5, "textHeight": 3, "cablePrefix": "WL"}


# ==================== 输入解析 ====================

def split_fields(text: str) -> list[str]:
    return [part.strip() for part in FIELD_SPLIT.split(text)]


def parse_terminals(text: str):
    """每行（或每个分号）一块端子排：第一项是名称，其余全是端子号。"""
    blocks: list[dict] = []
    errors: list[str] = []
    for unit in [u.strip() for u in RECORD_SPLIT.split(text or "") if u.strip()]:
        parts = [p.rstrip("。.!！") for p in split_fields(unit) if p.strip()]
        if not parts:
            continue
        name, numbers = parts[0], parts[1:]
        if not numbers:
            errors.append("端子排「%s」后面没有端子号" % name)
            continue
        seen = []
        for number in numbers:
            if number in seen:
                errors.append("端子排「%s」的端子号 %s 重复" % (name, number))
            else:
                seen.append(number)
        blocks.append({"name": name, "terminals": seen})
    names = [b["name"] for b in blocks]
    for name in set(names):
        if names.count(name) > 1:
            errors.append("端子排名称「%s」出现了 %d 次" % (name, names.count(name)))
    if not blocks and not errors:
        errors.append("上面的端子排还没填")
    return blocks, errors


def resolve_reference(reference: str, blocks: list[dict]):
    """把 1-2ID4 拆成端子排 1-2ID 和端子号 4；名称前缀重叠时取端子真实存在的那个。"""
    text = (reference or "").strip()
    if not text:
        return None, "缺少端子号"
    candidates = sorted({b["name"] for b in blocks}, key=len, reverse=True)
    candidates = [n for n in candidates if text.upper().startswith(n.upper())]
    if not candidates:
        return None, "「%s」对不上任何端子排" % text
    last = ""
    for name in candidates:
        wanted = re.sub(r"^[-_\s]+", "", text[len(name):])
        if not wanted:
            last = "「%s」只有端子排名称，缺端子号" % text
            continue
        for block in blocks:
            if block["name"] != name:
                continue
            for number in block["terminals"]:
                if number.upper() == wanted.upper():
                    return {"block": name, "terminal": number}, ""
        last = "%s 没有 %s 号端子" % (name, wanted)
    return None, last


def parse_wiring(text: str, blocks: list[dict], from_cabinet: str, prefix: str):
    """一条记录「端子号、原理号[、去向柜]」；没写去向柜的并入后面第一条写了去向柜的记录。"""
    records = [r.strip() for r in RECORD_SPLIT.split(text or "") if r.strip()]
    rows: list[dict] = []
    errors: list[str] = []
    for index, record in enumerate(records, start=1):
        fields = split_fields(record)
        while fields and not fields[-1]:
            fields.pop()
        reference = fields[0] if fields else ""
        principle = fields[1] if len(fields) > 1 else ""
        destination = fields[2] if len(fields) > 2 else ""
        if len(fields) > 3:
            errors.append("第 %d 条「%s」超过 3 项，一条只能写 端子号、原理号、去向柜" % (index, record))
            continue
        resolved, error = resolve_reference(reference, blocks)
        if error:
            errors.append("第 %d 条「%s」：%s" % (index, record, error))
            continue
        rows.append({"index": index, "block": resolved["block"], "terminal": resolved["terminal"],
                     "principle": principle, "destination": destination})
    seen: dict[tuple, int] = {}
    repeated: list[str] = []
    for row in rows:
        key = (row["block"], row["terminal"])
        if key in seen:
            # 一个端子接两根线是真实存在的（短接、串接），只提醒不拦。
            repeated.append("第 %d 条和第 %d 条都接在 %s-%s 上，确认不是重复输入" % (row["index"], seen[key], key[0], key[1]))
        else:
            seen[key] = row["index"]
    cables: list[dict] = []
    bucket: list[dict] = []
    for row in rows:
        bucket.append(row)
        if row["destination"]:
            cables.append({"rows": bucket, "destination": row["destination"], "closed": True})
            bucket = []
    if bucket:
        cables.append({"rows": bucket, "destination": "", "closed": False})
    connections: list[dict] = []
    warnings: list[str] = list(repeated)
    for order, cable in enumerate(cables, start=1):
        cable["number"] = "%s-%02d" % (prefix, order)
        if not cable["closed"]:
            warnings.append("最后 %d 条记录没有写去向柜，先单独算成一根电缆 %s" % (len(cable["rows"]), cable["number"]))
        for row in cable["rows"]:
            connections.append({
                "terminalBlock": row["block"], "terminal": row["terminal"], "principle": row["principle"],
                "fromCabinet": from_cabinet, "toCabinet": cable["destination"],
                "cableNumber": cable["number"], "cableSpec": "",
            })
    if not connections and not errors:
        errors.append("上面的接线还没填")
    return connections, cables, errors, warnings


# ==================== 绘图（与 python-template.js 的固定代码一致） ====================

def natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(text))]


def text_width(value, height: float, factor: float) -> float:
    total = 0.0
    for char in str(value):
        total += 1.0 if ord(char) >= CJK_START else 0.55
    return total * height * factor


def build_columns(params, drawing):
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
    doc.header["$INSUNITS"] = 4
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

    def text(value, x, y, layer, align=None, rotation=0.0, height=None):
        content = str(value or "")
        if not content:
            return
        entity = msp.add_text(content, dxfattribs={
            "style": style_name, "height": height or text_h, "width": factor,
            "color": color, "layer": layer, "rotation": rotation,
        })
        entity.set_placement((x, y), align=align or TextEntityAlignment.MIDDLE_CENTER)

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
        text(layout["name"], start_x + drawing["blockNameWidth"] / 2.0, block_y + block_h / 2.0,
             layers["text"], rotation=90.0, height=cell_text_h)
        for terminal in layout["terminals"]:
            center = positions[(layout["name"], terminal)]["center"]
            text(terminal, center, number_center, layers["text"], rotation=90.0, height=cell_text_h)

    principles = {}
    for connection in params["connections"]:
        key = (connection.get("terminalBlock"), str(connection.get("terminal")))
        if key in positions and connection.get("principle") and key not in principles:
            principles[key] = connection["principle"]
    for key, value in principles.items():
        text(value, positions[key]["center"], principle_center, layers["text"], rotation=90.0, height=cell_text_h)

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
        label = str(params.get("projectName") or "")
        text(label, 0.0, title_y, layers["title"], align=TextEntityAlignment.MIDDLE_LEFT, height=text_h * 1.5)
        note = "%d 块端子排 / %d 个端子 / %d 根电缆 / %s" % (
            len(layouts), len(positions), len(cables), "向上接线" if up else "向下接线")
        text(note, right_x, title_y, layers["title"], align=TextEntityAlignment.MIDDLE_RIGHT)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(output)
    return {"blocks": len(layouts), "terminals": len(positions), "cables": len(cables),
            "points": sum(len(c["points"]) for c in cables), "skipped": skipped,
            "size": (round(right_x, 1), round(title_y + text_h - bottom_y, 1))}


def verify(output: Path, drawing) -> str:
    """回读校验：样式、实体数量、每个文字的宽度因子。返回一句话结论。"""
    import ezdxf
    doc = ezdxf.readfile(output)
    msp = doc.modelspace()
    texts = list(msp.query("TEXT"))
    lines = list(msp.query("LINE"))
    bad = [t for t in texts if abs(float(t.dxf.get("width", 1.0)) - float(drawing["widthFactor"])) > 1e-9]
    ok = drawing["style"] in doc.styles and not bad and texts and lines
    return "已校验：%d 条线、%d 个文字，样式 %s%s" % (
        len(lines), len(texts), drawing["style"], "" if ok else "（校验异常，请检查）")


def desktop_dir() -> Path:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            candidate = Path(winreg.QueryValueEx(key, "Desktop")[0])
            if candidate.is_dir():
                return candidate
    except Exception:
        pass
    home = Path.home() / "Desktop"
    return home if home.is_dir() else Path(__file__).resolve().parent


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", (value or "").strip()) or "端子排"


def generate(payload: dict) -> dict:
    blocks, block_errors = parse_terminals(payload.get("terminals", ""))
    cabinet = (payload.get("cabinet") or "").strip()
    prefix = (payload.get("prefix") or DEFAULTS["cablePrefix"]).strip() or DEFAULTS["cablePrefix"]
    connections, cables, wire_errors, warnings = parse_wiring(payload.get("wiring", ""), blocks, cabinet, prefix)
    errors = block_errors + wire_errors
    if errors:
        return {"ok": False, "errors": errors}
    params = {
        "projectName": cabinet or "端子排接线图",
        "direction": payload.get("direction") or DEFAULTS["direction"],
        "firstDistance": DEFAULTS["firstDistance"],
        "distanceStep": DEFAULTS["distanceStep"],
        "textHeight": DEFAULTS["textHeight"],
        "terminalBlocks": blocks,
        "connections": connections,
    }
    target = desktop_dir() / (safe_name(cabinet or "端子排") + "-端子排接线图.dxf")
    try:
        result = build_dxf(params, DRAWING, target)
    except (OSError, PermissionError):
        target = target.with_name("%s-%s.dxf" % (target.stem, datetime.now().strftime("%H%M%S")))
        result = build_dxf(params, DRAWING, target)
    global LAST_OUTPUT
    LAST_OUTPUT = target
    return {
        "ok": True,
        "path": str(target),
        "folder": str(target.parent),
        "verify": verify(target, DRAWING),
        "warnings": warnings + result["skipped"],
        "size": "%s × %s mm" % result["size"],
        "stats": {"blocks": result["blocks"], "terminals": result["terminals"],
                  "cables": result["cables"], "points": result["points"]},
        "cables": [{"number": c["number"], "destination": c["destination"] or "未填写",
                    "points": ["%s-%s" % (r["block"], r["terminal"]) for r in c["rows"]]} for c in cables],
    }


LAST_OUTPUT: Path | None = None

EXAMPLE_TERMINALS = "ZD、1、11\n1-2ID、1、2、3、4\nJD、1、4\n1ID、1、2、3、6\n1-2UD、1、2、3、4、6"
EXAMPLE_WIRING = "\n".join([
    "ZD1、+KM1",
    "ZD11、-KM1、直流馈线柜",
    "1-2ID4、1(2)B-N4121",
    "1-2ID1、1(2)B-A4121",
    "1-2ID2、1(2)B-B4121",
    "1-2ID3、1(2)B-C4121、35kV 1(2)#主变进线柜",
    "JD1、L",
    "JD4、N、相邻屏柜",
    "1ID1、1(2)B-A4111",
    "1ID2、1(2)B-B4111",
    "1ID3、1(2)B-C4111",
    "1ID6、1(2)B-N4111、35kV 1(2)#主变进线柜",
    "1-2UD1、A610",
    "1-2UD2、B610",
    "1-2UD3、C610",
    "1-2UD4、N600",
    "1-2UD6、L610、35kV PT柜",
])
EXAMPLE_CABINET = "35kV 1#主变保护柜"

# ==================== 页面 ====================

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>端子排出图</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 34px 20px 60px; background: #f4f6f5; color: #1f2a2e;
         font-family: "Microsoft YaHei UI", "Microsoft YaHei", system-ui, sans-serif; }
  .wrap { max-width: 860px; margin: 0 auto; }
  h1 { margin: 0 0 6px; font-size: 25px; letter-spacing: .5px; }
  .sub { margin: 0 0 26px; color: #6b7a7e; font-size: 14px; }
  .step { margin-bottom: 20px; padding: 18px 20px; border: 1px solid #dde3e2; border-radius: 8px;
          background: #fff; box-shadow: 0 1px 2px rgba(20,40,45,.04); }
  .step h2 { display: flex; align-items: center; gap: 9px; margin: 0 0 4px; font-size: 16px; }
  .num { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%;
         background: #007f70; color: #fff; font-size: 13px; }
  .tip { margin: 0 0 11px 33px; color: #74848a; font-size: 13px; line-height: 1.7; }
  .tip b { color: #1f6f63; font-weight: 600; }
  textarea { width: 100%; padding: 12px 13px; border: 1px solid #ccd5d5; border-radius: 6px; outline: 0;
             background: #fcfdfd; color: #1c2a2e; font-family: Consolas, "Microsoft YaHei UI", monospace;
             font-size: 14px; line-height: 1.85; resize: vertical; }
  textarea:focus { border-color: #007f70; box-shadow: 0 0 0 3px rgba(0,127,112,.12); background: #fff; }
  .go { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 4px; }
  .go label { color: #55666b; font-size: 14px; }
  .go input[type=text] { width: 240px; height: 44px; padding: 0 12px; border: 1px solid #ccd5d5;
                         border-radius: 6px; outline: 0; font-size: 15px; font-family: inherit; }
  button.main { height: 52px; padding: 0 40px; border: 0; border-radius: 6px; background: #007f70;
                color: #fff; font-size: 18px; font-family: inherit; letter-spacing: 2px; cursor: pointer; }
  button.main:hover { background: #00695d; }
  button.main:disabled { background: #9db3ae; cursor: default; }
  .link { border: 0; background: none; color: #007f70; font-size: 13px; font-family: inherit;
          cursor: pointer; text-decoration: underline; padding: 0; }
  .result { margin-top: 22px; padding: 18px 20px; border-radius: 8px; font-size: 14px; line-height: 1.8; }
  .result.ok { border: 1px solid #b9dcd3; background: #eef8f4; }
  .result.bad { border: 1px solid #e6c3bb; background: #fdf1ee; }
  .result h3 { margin: 0 0 8px; font-size: 17px; }
  .path { display: block; margin: 6px 0 12px; padding: 9px 11px; border-radius: 5px; background: #fff;
          border: 1px solid #d7e2de; font-family: Consolas, monospace; font-size: 13px; word-break: break-all; }
  .cables { margin: 10px 0 0; padding: 0; list-style: none; }
  .cables li { padding: 6px 0; border-top: 1px dashed #cfdcd8; font-family: Consolas, "Microsoft YaHei UI", monospace; }
  .cables b { color: #10574c; }
  .errs { margin: 6px 0 0; padding-left: 20px; }
  .errs li { padding: 2px 0; }
  .open { height: 40px; padding: 0 22px; border: 1px solid #007f70; border-radius: 6px; background: #fff;
          color: #007f70; font-size: 15px; font-family: inherit; cursor: pointer; }
  .warn { margin-top: 10px; color: #8a6a1f; font-size: 13px; }
  .foot { margin-top: 30px; color: #8b989b; font-size: 12px; line-height: 1.9; }
</style>
</head>
<body>
<div class="wrap">
  <h1>端子排出图</h1>
  <p class="sub">填下面两个框，点一下「生成图纸」，桌面上就有 DXF，直接用 CAD 打开。<button class="link" id="demo" type="button">填入示例看看</button></p>

  <div class="step">
    <h2><span class="num">1</span>有哪些端子排</h2>
    <p class="tip">一块端子排写一行：<b>先写端子排名称，后面挨着写端子号</b>，中间用顿号或逗号隔开。<code>N</code>、<code>PE</code>、<code>1A</code> 这种端子号照写。</p>
    <textarea id="terminals" rows="6" placeholder="ZD、1、11&#10;1-2ID、1、2、3、4&#10;JD、1、4"></textarea>
  </div>

  <div class="step">
    <h2><span class="num">2</span>怎么接线</h2>
    <p class="tip">一条接线写一行：<b>端子号、原理号</b>。一根电缆的<b>最后一条</b>再加上<b>去向柜</b>；前面没写去向柜的，自动算成同一根电缆。</p>
    <textarea id="wiring" rows="11" placeholder="ZD1、+KM1&#10;ZD11、-KM1、直流馈线柜&#10;1-2ID4、1(2)B-N4121&#10;1-2ID1、1(2)B-A4121、35kV 1(2)#主变进线柜"></textarea>
  </div>

  <div class="step">
    <h2><span class="num">3</span>出图</h2>
    <p class="tip">柜名会写在图纸标题和电缆的起点柜上，留空也能出图。</p>
    <div class="go">
      <label>柜名<br><input id="cabinet" type="text" placeholder="35kV 1#主变保护柜"></label>
      <button class="main" id="build" type="button">生成图纸</button>
    </div>
  </div>

  <div id="result"></div>
  <p class="foot">图纸按 1 个图形单位 = 1mm、文字样式 HZ、宽度因子 0.7、色号 7 生成，框线／文字／接线分图层，全部是可编辑的 LINE 和 TEXT。<br>关掉启动时那个黑色命令行窗口就等于关掉这个工具。需要逐条编辑、看预览或改绘图参数时用同目录的 index.html。</p>
</div>
<script>
const DEMO = __DEMO__;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

$("demo").onclick = () => {
  $("terminals").value = DEMO.terminals;
  $("wiring").value = DEMO.wiring;
  $("cabinet").value = DEMO.cabinet;
};

async function build() {
  const button = $("build");
  button.disabled = true;
  button.textContent = "正在出图…";
  $("result").className = "";
  $("result").innerHTML = "";
  try {
    const response = await fetch("/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ terminals: $("terminals").value, wiring: $("wiring").value, cabinet: $("cabinet").value }),
    });
    render(await response.json());
  } catch (error) {
    render({ ok: false, errors: ["工具没连上：" + error.message + "。确认那个黑色命令行窗口还开着。"] });
  } finally {
    button.disabled = false;
    button.textContent = "生成图纸";
  }
}

function render(data) {
  const box = $("result");
  if (!data.ok) {
    box.className = "result bad";
    box.innerHTML = "<h3>还差一点，下面几处要改</h3><ul class=\\"errs\\">" +
      data.errors.map((e) => "<li>" + esc(e) + "</li>").join("") + "</ul>";
    return;
  }
  box.className = "result ok";
  const stats = data.stats;
  box.innerHTML = "<h3>图纸好了</h3>" +
    "<span class=\\"path\\">" + esc(data.path) + "</span>" +
    "<button class=\\"open\\" id=\\"openBtn\\" type=\\"button\\">用 CAD 打开</button>" +
    "<div style=\\"margin-top:12px\\">" + stats.blocks + " 块端子排 · " + stats.terminals + " 个端子 · " +
    stats.cables + " 根电缆 · " + stats.points + " 个接线点 · 图幅 " + esc(data.size) + "</div>" +
    "<ul class=\\"cables\\">" + data.cables.map((c) =>
      "<li><b>" + esc(c.number) + "</b> → " + esc(c.destination) + "：" + esc(c.points.join(" ")) + "</li>").join("") + "</ul>" +
    (data.warnings.length ? "<div class=\\"warn\\">" + data.warnings.map(esc).join("<br>") + "</div>" : "") +
    "<div class=\\"warn\\" style=\\"color:#6b7a7e\\">" + esc(data.verify) + "</div>";
  $("openBtn").onclick = async () => { await fetch("/open"); };
}

$("build").onclick = build;
["terminals", "wiring", "cabinet"].forEach((id) => $(id).addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") build();
}));
</script>
</body>
</html>
"""


# ==================== 本地小服务 ====================

def page_html() -> bytes:
    demo = json.dumps({"terminals": EXAMPLE_TERMINALS, "wiring": EXAMPLE_WIRING, "cabinet": EXAMPLE_CABINET},
                      ensure_ascii=False)
    return PAGE.replace("__DEMO__", demo).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "DuanziDXF/1.0"

    def log_message(self, *args):  # 不往命令行刷访问日志
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, page_html(), "text/html; charset=utf-8")
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path == "/open":
            # 只允许打开刚生成的那份图纸，不接受任意路径
            if LAST_OUTPUT and LAST_OUTPUT.exists():
                try:
                    import os
                    os.startfile(str(LAST_OUTPUT))
                    self._json({"ok": True})
                except Exception as error:
                    self._json({"ok": False, "errors": [str(error)]})
            else:
                self._json({"ok": False, "errors": ["还没有生成图纸"]})
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/build":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception as error:
            self._json({"ok": False, "errors": ["请求读不出来：%s" % error]})
            return
        try:
            result = generate(payload)
        except Exception as error:
            result = {"ok": False, "errors": ["出图失败：%s：%s" % (type(error).__name__, error)]}
        if result.get("ok"):
            print("已出图：%s" % result["path"])
        else:
            for item in result.get("errors", []):
                print("输入有问题：%s" % item)
        self._json(result)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        print("缺少 ezdxf，请先在命令行执行：pip install ezdxf")
        input("按回车关闭…")
        return 2
    port = free_port()
    url = "http://127.0.0.1:%d/" % port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("端子排出图工具已启动：%s" % url)
    print("浏览器没自动打开就把上面这行地址粘到浏览器里。")
    print("图纸会存到桌面。用完直接关掉这个窗口就行。")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已关闭。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
