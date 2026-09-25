# -*- coding: utf-8 -*-
"""端子排出图 Windows 桌面界面。

快捷键：F5 检查输入，Ctrl+Enter 生成 DXF。输入内容和设置在生成成功、关闭窗口时保存到
%APPDATA%\\端子排出图工具\\state.json，下次打开自动恢复。
"""
import gc
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from duanzi_dxf_tool import (EXAMPLE_CABINET, EXAMPLE_TERMINALS, EXAMPLE_WIRING, describe_blocks, desktop_dir,
                             duplicate_terminal_warnings, generate, parse_terminals, parse_wiring,
                             strips_from_blocks)

STATE_FILE = Path(os.environ.get("APPDATA") or Path.home()) / "端子排出图工具" / "state.json"
STATE_VERSION = 2
UI_FONT = "Microsoft YaHei UI"
CODE_FONT = ("Consolas", 11)
MUTED = "#607078"
ERROR = "#a33a2a"
WARN = "#8a5a00"
OK = "#2f7d4a"
UP = "#1f5fa8"
BORDER = "#b9c1c7"
ARROWS = {"向下": "↓ 向下", "向上": "↑ 向上"}
MAX_IMPORT_BYTES = 5 * 1024 * 1024
GUIDE = """使用步骤：
1. 在①粘贴端子排。普通格式一行一块，如「ZD、1、2、3」；坐标格式每行「横坐标,纵坐标 文字」，名称行以“端子名”结尾。
2. 在②粘贴接线。一行一条「端子号、原理号、去向柜」，同一根电缆只在最后一条写去向柜；也可以留空只画端子排。
3. 在右侧确认每块端子排的电缆方向（单击“方向”格切换），按 Ctrl+Enter 生成 DXF。

点“填入示例”可以看一份完整示例；也可以用“导入文本…”直接读 txt/csv 文件。"""


def resource_path(name):
    """打包后资源在 sys._MEIPASS，源码运行时在脚本同目录。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def enable_high_dpi():
    # 不声明 DPI 感知时，Windows 在 125%/150% 缩放下会把整个窗口位图拉伸，文字发虚。
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def read_text_file(path):
    """读入 CAD/Excel 导出的文本：先认 BOM，再试 UTF-8，最后按国标码。"""
    data = Path(path).read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")


class LineNumbers(tk.Canvas):
    """输入框左侧行号，方便对照报错里的「第 N 行」。"""

    def __init__(self, master, target, font):
        self.number_font = tkfont.Font(root=master, font=font)
        super().__init__(master, width=self.number_font.measure("000") + 12, highlightthickness=0,
                         background="#f1f3f4")
        self.target = target
        self._pending = False

    def schedule(self, *_):
        # 合并同一轮的多次触发，等 Text 排版完再画，dlineinfo 才准。
        if not self._pending:
            self._pending = True
            self.after_idle(self.redraw)

    def redraw(self):
        self._pending = False
        last = int(self.target.index("end-1c").split(".")[0])
        width = self.number_font.measure("0" * max(3, len(str(last)))) + 12
        if int(self["width"]) != width:
            self.configure(width=width)
        self.delete("all")
        line = int(self.target.index("@0,0").split(".")[0])
        while line <= last:
            info = self.target.dlineinfo("%d.0" % line)
            if info is None:
                break
            self.create_text(width - 6, info[1], anchor="ne", text=str(line), font=self.number_font, fill=MUTED)
            line += 1


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("端子排出图工具")
        try:
            self.iconbitmap(default=str(resource_path("图标.ico")))
        except tk.TclError:
            pass
        # 声明 DPI 感知后 Tk 按真实 DPI 放大字号，像素尺寸要按同一比例放大。
        self.ui_scale = self.winfo_fpixels("1i") / 96.0
        self.strip_dirs = {}
        self.strip_idents = {}
        self.direction_memory = {}
        self.last_output = None
        self.last_wiring_output = None
        self.busy = False
        self._live_job = None
        self._poll_job = None
        self._setup_style()
        self._build_ui()
        self._place_window()
        restored = self._load_state()
        self.refresh_directions()
        if restored:
            self.status.set("已恢复上次的输入")
            self.write("已恢复上次的输入和设置。按 F5 检查，Ctrl+Enter 生成。")
        else:
            self.write(GUIDE)
        self.bind_all("<F5>", lambda _e: self.inspect())
        self.bind_all("<Control-Return>", self._shortcut_build)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def px(self, value):
        return int(value * self.ui_scale)

    def _setup_style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
            try:
                tkfont.nametofont(name).configure(family=UI_FONT, size=10)
            except tk.TclError:
                pass
        linespace = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        style.configure("Treeview", rowheight=int(linespace * 1.5))
        style.configure("Title.TLabel", font=(UI_FONT, 16, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Accent.TButton", font=(UI_FONT, 10, "bold"))

    def _place_window(self):
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = self.px(1120), self.px(780)
        self.minsize(min(self.px(860), screen_w), min(self.px(600), screen_h - 80))
        if width > screen_w or height > screen_h - 60:
            self.state("zoomed")
        else:
            self.geometry("%dx%d+%d+%d" % (width, height, (screen_w - width) // 2, max(0, (screen_h - height) // 3)))

    # ---------- 界面 ----------
    def _build_ui(self):
        self._menu = tk.Menu(self, tearoff=False)
        status_bar = ttk.Frame(self, padding=(14, 3))
        status_bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        ttk.Label(status_bar, text="F5 检查　Ctrl+Enter 生成　右键复制粘贴", style="Muted.TLabel").pack(side="right")

        root = ttk.Frame(self, padding=(14, 10, 14, 4))
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="端子排出图工具", style="Title.TLabel").pack(anchor="w")

        # 左右分栏：左边两段输入，右边设置、方向和诊断。
        panes = ttk.Panedwindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(panes)
        right = ttk.Frame(panes, padding=(12, 0, 0, 0))
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        inputs = ttk.Panedwindow(left, orient="vertical")
        inputs.pack(fill="both", expand=True)
        top = ttk.Frame(inputs)
        bottom = ttk.Frame(inputs, padding=(0, 8, 0, 0))
        inputs.add(top, weight=3)
        inputs.add(bottom, weight=2)
        self.terminals = self._input_section(top, "① 端子排（坐标格式的名称行以“端子名”结尾）", 12, live=True)
        self.wiring = self._input_section(bottom, "② 接线（一行一条：端子号、原理号、去向柜）", 10)

        settings = ttk.LabelFrame(right, text="出图设置", padding=8)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="柜名").grid(row=0, column=0, sticky="w")
        self.cabinet = ttk.Entry(settings)
        self.cabinet.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=2)
        self.cabinet.bind("<Button-3>", self._edit_menu)
        ttk.Label(settings, text="默认方向").grid(row=1, column=0, sticky="w")
        self.direction = ttk.Combobox(settings, values=list(ARROWS), state="readonly", width=8)
        self.direction.current(0)
        self.direction.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)
        self.direction.bind("<<ComboboxSelected>>", self._on_default_direction)
        ttk.Label(settings, text="改动后应用到全部块", style="Muted.TLabel").grid(row=1, column=1, columnspan=2,
                                                                                sticky="e")
        ttk.Label(settings, text="输出目录").grid(row=2, column=0, sticky="w")
        self.output_dir = tk.StringVar(value=str(desktop_dir()))
        folder_entry = ttk.Entry(settings, textvariable=self.output_dir)
        folder_entry.grid(row=2, column=1, sticky="ew", padx=(6, 4), pady=2)
        folder_entry.bind("<Button-3>", self._edit_menu)
        ttk.Button(settings, text="浏览…", width=6, command=self.choose_dir).grid(row=2, column=2)
        self.auto_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings, text="生成后自动打开完整图", variable=self.auto_open).grid(
            row=3, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(2, 0))

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(8, 0))
        self.build_button = ttk.Button(actions, text="生成 DXF", width=8, style="Accent.TButton", command=self.build)
        self.build_button.pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="检查输入", width=8, command=self.inspect).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(actions, text="填入示例", width=8, command=self.demo).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="清空", width=6, command=self.clear).pack(side="left", fill="x", expand=True, padx=(4, 0))
        opens = ttk.Frame(right)
        opens.pack(fill="x", pady=(4, 0))
        self.open_button = ttk.Button(opens, text="打开完整图", width=8, command=self.open_output, state="disabled")
        self.open_button.pack(side="left", fill="x", expand=True)
        self.wiring_button = ttk.Button(opens, text="打开仅接线图", width=8, state="disabled",
                                        command=lambda: self.open_output(wiring=True))
        self.wiring_button.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(opens, text="打开文件夹", width=8, command=self.open_folder).pack(side="left", fill="x", expand=True)

        self._build_strip_table(right)

        ttk.Label(right, text="诊断 / 生成结果").pack(anchor="w", pady=(10, 2))
        frame = tk.Frame(right, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER, bd=0)
        frame.pack(fill="both", expand=True)
        self.result = tk.Text(frame, height=8, state="disabled", wrap="word", relief="flat", borderwidth=0,
                              highlightthickness=0, padx=8, pady=6, font=(UI_FONT, 10))
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.result.yview)
        self.result.configure(yscrollcommand=ys.set)
        self.result.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.result.tag_configure("error", foreground=ERROR)
        self.result.tag_configure("warn", foreground=WARN)
        self.result.tag_configure("ok", foreground=OK)
        self.result.bind("<Button-3>", self._edit_menu)

    def _build_strip_table(self, parent):
        box = ttk.LabelFrame(parent, text="各块端子排的电缆方向", padding=6)
        box.pack(fill="x", pady=(10, 0))
        holder = ttk.Frame(box)
        holder.pack(fill="x")
        table = ttk.Treeview(holder, columns=("name", "count", "dir"), show="headings", height=5,
                             selectmode="extended")
        for column, title, width, anchor, stretch in (("name", "端子排", 170, "w", True),
                                                      ("count", "端子数", 64, "center", False),
                                                      ("dir", "方向", 76, "center", False)):
            table.heading(column, text=title, anchor=anchor)
            table.column(column, width=self.px(width), minwidth=self.px(40), anchor=anchor, stretch=stretch)
        table.tag_configure("up", foreground=UP)
        ys = ttk.Scrollbar(holder, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=ys.set)
        table.pack(side="left", fill="x", expand=True)
        ys.pack(side="right", fill="y")
        table.bind("<Button-1>", self._on_table_click)
        table.bind("<space>", self._toggle_selected)
        self.strip_table = table
        tools = ttk.Frame(box)
        tools.pack(fill="x", pady=(4, 0))
        self.strip_hint = tk.StringVar()
        ttk.Label(tools, textvariable=self.strip_hint, style="Muted.TLabel").pack(side="left")
        ttk.Button(tools, text="选中向下", width=8, command=lambda: self._set_selected("向下")).pack(side="right")
        ttk.Button(tools, text="选中向上", width=8, command=lambda: self._set_selected("向上")).pack(side="right", padx=4)

    def _input_section(self, parent, title, height, live=False):
        head = ttk.Frame(parent)
        head.pack(fill="x")
        ttk.Label(head, text=title).pack(side="left")
        frame, box = self._text_box(parent, height, live)
        ttk.Button(head, text="导入文本…", command=lambda: self.import_file(box)).pack(side="right")
        frame.pack(fill="both", expand=True, pady=(4, 0))
        return box

    def _text_box(self, parent, height, live):
        frame = tk.Frame(parent, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER, bd=0)
        box = tk.Text(frame, wrap="none", undo=True, font=CODE_FONT, height=height, relief="flat", borderwidth=0,
                      highlightthickness=0, padx=6, pady=4)
        gutter = LineNumbers(frame, box, CODE_FONT)
        ys = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=box.xview)

        def on_yscroll(first, last):
            ys.set(first, last)
            gutter.schedule()

        def on_modified(_event):
            # 复位修改标志才会收到下一次 <<Modified>>；复位本身也会触发一次，直接跳过。
            if not box.edit_modified():
                return
            box.edit_modified(False)
            gutter.schedule()
            if live:
                self._schedule_live_refresh()

        box.configure(yscrollcommand=on_yscroll, xscrollcommand=xs.set)
        gutter.grid(row=0, column=0, sticky="ns")
        box.grid(row=0, column=1, sticky="nsew")
        ys.grid(row=0, column=2, sticky="ns")
        xs.grid(row=1, column=0, columnspan=2, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        box.bind("<<Modified>>", on_modified)
        box.bind("<Configure>", gutter.schedule)
        # 必须绑在输入框自身并返回 break：只用 bind_all 时 Text 的 <Return> 先插入换行，会把光标所在行拆成两行。
        box.bind("<Control-Return>", self._shortcut_build)
        box.bind("<Button-3>", self._edit_menu)
        gutter.bind("<MouseWheel>", lambda event: box.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        return frame, box

    def _edit_menu(self, event):
        widget = event.widget
        editable = str(widget.cget("state")) != "disabled"
        menu = self._menu
        menu.delete(0, "end")
        if editable:
            widget.focus_set()
            menu.add_command(label="剪切", accelerator="Ctrl+X", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="复制", accelerator="Ctrl+C", command=lambda: widget.event_generate("<<Copy>>"))
        if editable:
            menu.add_command(label="粘贴", accelerator="Ctrl+V", command=lambda: widget.event_generate("<<Paste>>"))
            if isinstance(widget, tk.Text):
                menu.add_command(label="撤销", accelerator="Ctrl+Z", command=lambda: widget.event_generate("<<Undo>>"))
        menu.add_separator()
        menu.add_command(label="全选", accelerator="Ctrl+A", command=lambda: widget.event_generate("<<SelectAll>>"))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    # ---------- 状态保存 ----------
    def _load_state(self):
        """恢复上次的输入；文件缺失或被改坏都不能挡住程序启动。"""
        try:
            # utf-8-sig：用记事本等手改过的文件可能带 BOM，json 直接读会整份作废。
            state = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False
        if not isinstance(state, dict):
            return False

        def text(key):
            value = state.get(key)
            return value if isinstance(value, str) else ""

        self.terminals.insert("1.0", text("terminals"))
        self.wiring.insert("1.0", text("wiring"))
        self.cabinet.insert(0, text("cabinet"))
        if text("direction") in ARROWS:
            self.direction.set(text("direction"))
        if text("outputDir") and Path(text("outputDir")).is_dir():
            self.output_dir.set(text("outputDir"))
        self.auto_open.set(state.get("autoOpen") is True)
        memory = state.get("directionMemory")
        if isinstance(memory, dict):
            self.direction_memory = {str(key): value for key, value in memory.items() if value in ARROWS}
        for box in (self.terminals, self.wiring):
            box.edit_reset()
        return self._has_input()

    def _save_state(self):
        state = {"version": STATE_VERSION, "terminals": self.get_text(self.terminals),
                 "wiring": self.get_text(self.wiring), "cabinet": self.cabinet.get(),
                 "direction": self.direction.get(), "outputDir": self.output_dir.get(),
                 "autoOpen": self.auto_open.get(),
                 "directionMemory": {self.strip_idents[key]: value for key, value in self.strip_dirs.items()}}
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再替换，写到一半断电也不会留下损坏的状态文件。
            temp = STATE_FILE.with_suffix(".tmp")
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temp, STATE_FILE)
        except OSError:
            pass

    def on_close(self):
        if self.busy and not messagebox.askyesno("正在生成", "DXF 还在生成，确定要退出吗？"):
            return
        self._save_state()
        # 窗口销毁后还没执行的定时任务会报 invalid command name，先全部取消。
        for job in (self._live_job, self._poll_job):
            if job is not None:
                self.after_cancel(job)
        self.destroy()

    def report_callback_exception(self, exc, value, tb):
        # 打包后的窗口版 exe 没有控制台，Tk 默认写到 stderr 的报错会被直接丢掉，用户只看到按钮没反应。
        detail = "".join(traceback.format_exception(exc, value, tb))
        messagebox.showerror("程序出错", "这次操作没有完成：\n\n" + detail[-1500:])

    # ---------- 基础操作 ----------
    @staticmethod
    def get_text(box):
        return box.get("1.0", "end-1c")

    def _has_input(self):
        return bool(self.get_text(self.terminals).strip() or self.get_text(self.wiring).strip())

    def write(self, text="", tag=None):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.configure(state="disabled")
        if text:
            self.append(text, tag)

    def append(self, text, tag=None):
        self.result.configure(state="normal")
        self.result.insert("end", text, tag or ())
        self.result.configure(state="disabled")

    def demo(self):
        if self._has_input() and not messagebox.askyesno("填入示例", "示例会覆盖当前输入，继续吗？\n（输入框内容可按 Ctrl+Z 撤销）"):
            return
        for box, value in ((self.terminals, EXAMPLE_TERMINALS), (self.wiring, EXAMPLE_WIRING)):
            box.delete("1.0", "end")
            box.insert("1.0", value)
        self.cabinet.delete(0, "end")
        self.cabinet.insert(0, EXAMPLE_CABINET)
        self.refresh_directions()
        self.write("已填入示例数据。按 F5 检查，Ctrl+Enter 生成。")

    def clear(self):
        if not self._has_input():
            return
        if not messagebox.askyesno("清空", "清空端子排和接线输入？\n（可按 Ctrl+Z 撤销）"):
            return
        for box in (self.terminals, self.wiring):
            box.delete("1.0", "end")
        self.refresh_directions()
        self.write(GUIDE)

    def choose_dir(self):
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(desktop_dir()), title="选择 DXF 输出目录")
        if folder:
            self.output_dir.set(os.path.normpath(folder))

    def import_file(self, box):
        path = filedialog.askopenfilename(title="导入文本", filetypes=[("文本文件", "*.txt *.csv *.tsv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            if os.path.getsize(path) > MAX_IMPORT_BYTES:
                messagebox.showerror("导入失败", "文件超过 5 MB，不像是端子排或接线清单。")
                return
            content = read_text_file(path)
        except OSError as error:
            messagebox.showerror("导入失败", str(error))
            return
        box.delete("1.0", "end")
        box.insert("1.0", content.replace("\r\n", "\n").replace("\r", "\n"))
        box.focus_set()
        self.status.set("已导入 %s（可按 Ctrl+Z 撤销）" % os.path.normpath(path))

    def inspect(self):
        self.refresh_directions()
        blocks, errors = parse_terminals(self.get_text(self.terminals))
        warnings = duplicate_terminal_warnings(blocks)
        lines = ["识别到的端子排："] + (describe_blocks(blocks, with_numbers=True) or ["（没有识别到端子排）"])
        wiring = self.get_text(self.wiring)
        if blocks and not errors and wiring.strip():
            _, cables, wire_errors, wire_warnings = parse_wiring(wiring, blocks, "", "WL")
            errors = errors + wire_errors
            warnings = warnings + wire_warnings
            lines += ["", "接线识别到 %d 根电缆。" % len(cables)]
        self.write("\n".join(lines) + "\n\n")
        if errors:
            self.append("输入问题（%d 处）：\n%s\n" % (len(errors), "\n".join(errors)), "error")
        else:
            self.append("输入检查通过。\n", "ok")
        if warnings:
            self.append("\n提醒：\n%s\n" % "\n".join(warnings), "warn")
        self.status.set("检查发现 %d 处问题" % len(errors) if errors else "检查通过")

    # ---------- 电缆方向 ----------
    def refresh_directions(self):
        """按当前端子排输入重列方向表。方向按端子排名称记忆，前面插入或删掉别的块也不会串位。"""
        text = self.get_text(self.terminals)
        blocks, errors = parse_terminals(text)
        strips = strips_from_blocks(blocks)
        selected = set(self.strip_table.selection())
        self.strip_table.delete(*self.strip_table.get_children())
        self.strip_dirs, self.strip_idents = {}, {}
        seen = {}
        for strip in strips:
            seen[strip["name"]] = seen.get(strip["name"], 0) + 1
            ident = strip["name"] if seen[strip["name"]] == 1 else "%s#%d" % (strip["name"], seen[strip["name"]])
            value = self.direction_memory.get(ident)
            if value not in ARROWS:
                value = self.direction.get()
            self.strip_dirs[strip["key"]] = value
            self.strip_idents[strip["key"]] = ident
            self.strip_table.insert("", "end", iid=strip["key"], values=(strip["name"], strip["terminals"], ARROWS[value]),
                                    tags=("up",) if value == "向上" else ())
        keep = [key for key in selected if key in self.strip_dirs]
        if keep:
            self.strip_table.selection_set(keep)
        problems = "输入有 %d 处问题，按 F5 查看" % len(errors) if errors and text.strip() else ""
        if strips:
            summary = "共 %d 块、%d 个端子" % (len(strips), sum(strip["terminals"] for strip in strips))
            self.strip_hint.set(summary + ("；" + problems if problems else ""))
        else:
            self.strip_hint.set(problems or "粘贴端子排后自动列出，单击“方向”格切换")

    def _schedule_live_refresh(self):
        # 边输入边解析，停手 0.4 秒后再刷新方向表，粘贴大段文字时不卡。
        if self._live_job is not None:
            self.after_cancel(self._live_job)
        self._live_job = self.after(400, self._live_refresh)

    def _live_refresh(self):
        self._live_job = None
        self.refresh_directions()

    @staticmethod
    def _opposite(value):
        return "向下" if value == "向上" else "向上"

    def _apply_directions(self, keys, value):
        for key in keys:
            self.strip_dirs[key] = value
            self.direction_memory[self.strip_idents[key]] = value
            self.strip_table.set(key, "dir", ARROWS[value])
            self.strip_table.item(key, tags=("up",) if value == "向上" else ())

    def _on_default_direction(self, _event=None):
        value = self.direction.get()
        self._apply_directions(list(self.strip_dirs), value)
        if self.strip_dirs:
            self.status.set("已把全部 %d 块端子排设为%s" % (len(self.strip_dirs), value))

    def _on_table_click(self, event):
        table = self.strip_table
        if table.identify_region(event.x, event.y) != "cell" or table.identify_column(event.x) != "#3":
            return None
        key = table.identify_row(event.y)
        if key:
            self._apply_directions([key], self._opposite(self.strip_dirs[key]))
        return "break"

    def _toggle_selected(self, _event=None):
        for key in self.strip_table.selection():
            self._apply_directions([key], self._opposite(self.strip_dirs[key]))
        return "break"

    def _set_selected(self, value):
        keys = self.strip_table.selection()
        if not keys:
            self.status.set("先在表格里选中要设置的端子排（按住 Ctrl 或 Shift 可多选）")
            return
        self._apply_directions(keys, value)

    # ---------- 生成 ----------
    def _shortcut_build(self, _event=None):
        self.build()
        return "break"

    def build(self):
        if self.busy:
            return
        folder = self.output_dir.get().strip()
        if folder and not Path(folder).is_dir():
            if not messagebox.askyesno("输出目录不存在", "%s\n\n要新建这个目录吗？" % folder):
                return
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
            except OSError as error:
                messagebox.showerror("无法新建目录", str(error))
                return
        self.refresh_directions()
        payload = {"terminals": self.get_text(self.terminals), "wiring": self.get_text(self.wiring),
                   "cabinet": self.cabinet.get(), "direction": "UP" if self.direction.get() == "向上" else "DOWN",
                   "directions": {key: "UP" if value == "向上" else "DOWN" for key, value in self.strip_dirs.items()},
                   "outputDir": folder}
        self._set_busy(True)
        self.write("正在生成 DXF，请稍候……")
        results = queue.Queue()

        def work():
            try:
                results.put(generate(payload))
            except Exception:
                # 后台线程的异常不会自己冒到界面，不接住的话窗口会一直停在“正在生成”。
                results.put({"ok": False, "errors": ["生成时出现未预期的错误：", traceback.format_exc()]})

        def poll():
            # Tk 不是线程安全的，后台线程不碰任何界面对象，由主线程定时来取结果。
            try:
                result = results.get_nowait()
            except queue.Empty:
                self._poll_job = self.after(50, poll)
                return
            self._poll_job = None
            self._show_result(result)
        # 先在主线程回收垃圾：否则生成时分配大量对象，可能在后台线程触发回收，
        # 在那里析构 Tk 对象会报 Tcl_AsyncDelete 并直接终止进程。
        gc.collect()
        threading.Thread(target=work, daemon=True).start()
        self._poll_job = self.after(50, poll)

    def _set_busy(self, busy):
        self.busy = busy
        self.build_button.configure(state="disabled" if busy else "normal")
        self.configure(cursor="watch" if busy else "")
        if busy:
            self.status.set("正在生成……")

    def _show_result(self, result):
        self._set_busy(False)
        if not result.get("ok"):
            self.open_button.configure(state="disabled")
            self.wiring_button.configure(state="disabled")
            self.write("没有生成，请先处理这些问题：\n" + "\n".join(result.get("errors", [])), "error")
            self.status.set("生成失败")
            return
        self.last_output = result.get("path")
        self.last_wiring_output = result.get("wiringPath")
        for button, path in ((self.open_button, self.last_output), (self.wiring_button, self.last_wiring_output)):
            button.configure(state="normal" if path and os.path.isfile(path) else "disabled")
        stats = result.get("stats", {})
        lines = ["完整图：%s" % result["path"], "仅接线图：%s" % result.get("wiringPath", ""),
                 "图幅约 %s；%d 块端子排、%d 个端子、%d 根电缆" % (result.get("size", ""), stats.get("blocks", 0),
                                                        stats.get("terminals", 0), stats.get("cables", 0)),
                 result.get("verify", ""), ""] + list(result.get("parsed", []))
        if result.get("cables"):
            lines += ["", "电缆清单："] + ["%s 至 %s：%s" % (cable["number"], cable["destination"], "、".join(cable["points"]))
                                        for cable in result["cables"]]
        self.write("生成成功\n", "ok")
        self.append("\n".join(lines) + "\n")
        if result.get("warnings"):
            self.append("\n提醒：\n%s\n" % "\n".join(result["warnings"]), "warn")
        self.status.set("已生成：%s" % result["path"])
        self._save_state()
        if self.auto_open.get():
            self.open_output()

    def open_output(self, wiring=False):
        path = self.last_wiring_output if wiring else self.last_output
        if path and os.path.isfile(path):
            try:
                os.startfile(path)
            except OSError as error:
                messagebox.showerror("打开失败", str(error))
        else:
            (self.wiring_button if wiring else self.open_button).configure(state="disabled")
            messagebox.showwarning("没有文件", "请先生成 DXF 文件。")

    def open_folder(self):
        if self.last_output and os.path.isfile(self.last_output):
            # 资源管理器里直接选中刚生成的图。
            subprocess.Popen('explorer /select,"%s"' % os.path.normpath(self.last_output))
            return
        try:
            os.startfile(self.output_dir.get().strip() or str(desktop_dir()))
        except OSError as error:
            messagebox.showerror("打开失败", str(error))


if __name__ == "__main__":
    enable_high_dpi()
    App().mainloop()
