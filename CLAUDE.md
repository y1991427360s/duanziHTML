# 端子排出图工具 — 项目约定

本项目只保留简洁版：`出图工具.cmd` 启动 `duanzi_dxf_tool.py`，浏览器填写数据后直接生成 DXF 到桌面。

## 硬规则

- `出图工具.cmd` 必须保持纯 ASCII 和 CRLF 换行。
- 1 图形单位 = 1 mm，DXF R2010。
- 文字样式 `HZ`，字体 `txt.shx` + `hztxt.shx`，字高 3，宽度因子 0.7，色号 7。
- 端子格节距 5 mm，端子排总高 75 mm。
- 坐标输入按横坐标划分物理端子排：相同横坐标的多个不同名称段必须连续绘制在同一行；有几种横坐标就生成几条横向端子排。
- 每块物理端子排的电缆方向可单独选向上或向下（页面里每块一个按钮，POST /build 用 `directions` 传 `{物理组: "UP"|"DOWN"}`），默认向下。
- 每行电缆距离独立按 10、15、20、25……计算。
- 同一端子接多根电缆时，引线以 1 mm 间距居中展开；左侧引线对应离端子排更近的电缆。
- 坐标输入只把纯数字识别为端子号；原理号文字自动忽略。
- 不要修改或删除 `html电缆/`，其中是 DWG 原图、清册和 CAD 锁文件。

## 验证

- `python -m py_compile duanzi_dxf_tool.py`
- `python -m unittest -v test_duanzi_dxf_tool.py`
- 启动服务后请求 `/`、`POST /strips` 和 `POST /build`，确认 `ok=true`（/strips 返回每块端子排概览，/build 带 `directions` 时各块方向生效）。
- 用 `ezdxf.readfile()` 回读 DXF，检查 `HZ`、文字宽度因子、75 mm 高度、5 mm 节距和每行独立电缆距离。
- 测试生成的桌面 DXF 用完删除。
