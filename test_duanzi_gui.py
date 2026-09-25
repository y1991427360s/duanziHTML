"""桌面界面的逻辑测试：窗口隐藏运行，状态文件和对话框全部替换成临时对象。"""
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duanzi_gui as gui


class ReadTextFileTests(unittest.TestCase):
    def test_common_encodings(self):
        with TemporaryDirectory() as folder:
            cases = {"utf8.txt": "ZD、1、2".encode("utf-8"), "bom.txt": "﻿ZD、1、2".encode("utf-8"),
                     "gbk.txt": "ZD、1、2".encode("gbk"), "utf16.txt": "ZD、1、2".encode("utf-16")}
            for name, data in cases.items():
                path = Path(folder) / name
                path.write_bytes(data)
                self.assertEqual("ZD、1、2", gui.read_text_file(path), name)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.state = Path(self.folder.name) / "state" / "state.json"
        patches = [patch.object(gui, "STATE_FILE", self.state),
                   patch.object(gui.messagebox, "askyesno", return_value=True),
                   patch.object(gui.messagebox, "showerror"),
                   patch.object(gui.messagebox, "showwarning")]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            try:
                app.on_close()
            except Exception:
                pass
        self.folder.cleanup()

    def open(self):
        app = gui.App()
        app.withdraw()
        app.update()
        self.apps.append(app)
        return app

    def close(self, app):
        app.on_close()
        self.apps.remove(app)

    def test_broken_state_file_does_not_block_startup(self):
        self.state.parent.mkdir(parents=True)
        for content in ("{坏的", '["不是字典"]', '{"terminals": 5, "directionMemory": {"a": 1}, "direction": null}'):
            self.state.write_text(content, encoding="utf-8")
            app = self.open()
            self.assertEqual("", app.get_text(app.terminals))
            self.assertTrue(app.get_text(app.result).startswith("使用步骤"))
            self.close(app)

    def test_state_file_with_bom_is_still_restored(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text('{"terminals": "ZD、1、2", "cabinet": "甲柜"}', encoding="utf-8-sig")
        app = self.open()
        self.assertEqual("ZD、1、2", app.get_text(app.terminals))
        self.assertEqual("甲柜", app.cabinet.get())
        self.assertTrue(app.get_text(app.result).startswith("已恢复"))

    def test_state_round_trip_keeps_input_and_directions_by_name(self):
        app = self.open()
        app.terminals.insert("1.0", "10,100 1QD 端子名\n10,95 1\n60,100 2QD 端子名\n60,95 1")
        app.wiring.insert("1.0", "1QD1、a、柜")
        app.cabinet.insert(0, "测试柜")
        app.refresh_directions()
        second = app.strip_table.get_children()[1]
        app._apply_directions([second], "向上")
        self.close(app)
        self.assertEqual(gui.STATE_VERSION, json.loads(self.state.read_text(encoding="utf-8"))["version"])

        app = self.open()
        self.assertIn("2QD 端子名", app.get_text(app.terminals))
        self.assertEqual("测试柜", app.cabinet.get())
        self.assertEqual(["向下", "向上"], [app.strip_dirs[key] for key in app.strip_table.get_children()])
        # 在前面插入一块新端子排后，方向仍跟着名称走，不会串到别的块上。
        app.terminals.insert("1.0", "5,100 0QD 端子名\n5,95 1\n")
        app.refresh_directions()
        names = {app.strip_table.item(key)["values"][0]: app.strip_dirs[key] for key in app.strip_table.get_children()}
        self.assertEqual({"0QD": "向下", "1QD": "向下", "2QD": "向上"}, names)

    def test_default_direction_applies_to_every_strip(self):
        app = self.open()
        app.terminals.insert("1.0", "10,100 1QD 端子名\n10,95 1\n60,100 2QD 端子名\n60,95 1")
        app.refresh_directions()
        app.direction.set("向上")
        app._on_default_direction()
        self.assertEqual({"向上"}, set(app.strip_dirs.values()))

    def test_ctrl_enter_is_bound_on_inputs_and_stops_newline(self):
        app = self.open()
        for box in (app.terminals, app.wiring):
            self.assertTrue(box.bind("<Control-Return>"))
        with patch.object(app, "build") as build:
            self.assertEqual("break", app._shortcut_build())
            build.assert_called_once()

    def wait(self, app):
        deadline = time.time() + 30
        while app.busy and time.time() < deadline:
            app.update()
            time.sleep(0.02)
        self.assertFalse(app.busy)

    def test_build_writes_files_and_reenables_after_failure(self):
        app = self.open()
        app.demo()
        app.output_dir.set(self.folder.name)
        app.build()
        self.wait(app)
        self.assertTrue(app.get_text(app.result).startswith("生成成功"))
        self.assertTrue(Path(app.last_output).is_file())
        self.assertEqual("normal", str(app.open_button["state"]))

        with patch.object(gui, "generate", side_effect=RuntimeError("意外")):
            app.build()
            self.wait(app)
        self.assertIn("意外", app.get_text(app.result))
        self.assertEqual("normal", str(app.build_button["state"]))
        self.assertEqual("disabled", str(app.open_button["state"]))

    def test_missing_output_dir_is_created_on_confirmation(self):
        app = self.open()
        app.demo()
        target = Path(self.folder.name) / "新目录" / "子目录"
        app.output_dir.set(str(target))
        app.build()
        self.wait(app)
        self.assertTrue(target.is_dir())
        self.assertEqual(target, Path(app.last_output).parent)


if __name__ == "__main__":
    unittest.main()
