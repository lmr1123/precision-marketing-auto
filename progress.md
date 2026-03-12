# Precision Marketing Auto - Progress

## 2026-03-11

### 今日完成
- 恢复并稳定了自动化主脚本，完成多次回退与修复，确保第1/2/3步主流程可执行。
- 修复第3步执行员工关键问题：
  - 小窗口/缩放导致的视口外点击问题。
  - 默认区域残留清理逻辑（含“全国”双击清空）。
  - 可见面板绑定与状态回读修复（避免读到隐藏面板）。
- 修复第2步 iframe 早执行问题：
  - 增加“关键控件就绪”等待，避免空壳 iframe 导致主消费营运区和券规则ID未命中。
- 调整第3步策略为“不区分渠道切换”，统一按当前页面字段填充，避免“渠道未命中”干扰。
- 更新测试数据 `data/plans.csv` 为未来时间，避免“发送时间不能选历史时间”拦截。
- 完成可视化UI增强（已在之前提交）：
  - 支持下载 Excel 模板与 UTF-8 BOM CSV 模板。
  - 支持上传 `.xlsx` 并自动转 `.csv`。
  - 脚本读取 CSV 改为 `utf-8-sig`，兼容 Windows Excel。
- 安装了 `chrome-devtools` 技能（来自 `ChromeDevTools/chrome-devtools-mcp`）用于后续调试。

### 已打稳定标记
- `stable-cb0fe65-known-good-20260306`
- `stable-e2e-pass-20260306-employee-fixed`

### 当前状态
- 代码已推送到 `main`，最新提交包含：
  - `12d393e`（第3步入口强校验）
  - `0b72824`（测试数据时间更新）

### 下一步计划
- 用最新 `data/plans.csv` 进行一轮完整回归（第1/2/3步 + 保存）。
- 重点验证第2步在不同网络波动下的 iframe 就绪稳定性。
- 若通过，新增一个“生产发布候选标签”（stable tag）供全国推广回退。
- 继续优化可视化UI：
  - 增加业务“通过/失败判定清单”提示。
  - 增加第2步失败的可视化诊断提示（就绪状态、缺失控件项）。

### 本轮新增（渠道多选）
- 脚本新增参数：`--step3-channels`（支持多选，逗号分隔）。
- CSV 新增可选列：`channels`（例如：`会员通-发客户消息,会员通-发客户朋友圈`）。
- 第3步改为按渠道判断：
  - 选中“会员通-发客户消息”才强制填写/校验“短信内容”。
  - 未选短信渠道时，短信内容自动跳过，不再记失败。
- 第3步等待时间放宽，降低“加载慢导致未进入第3步”的误判。
- 可视化 UI 新增“第3步渠道多选”复选项，并透传到脚本执行。
- 渠道字段映射规则已落地：
  - 选择“会员通-发客户消息” => 仅填写“短信内容”。
  - 选择“会员通-发客户朋友圈” => 填写“结束时间 / 执行员工 / 发送内容”。
  - 多选时按并集执行；未选择时按页面自动识别兜底。

### 本轮新增（朋友圈图片上传）
- 第3步新增朋友圈图片上传逻辑（渠道=会员通-发客户朋友圈）：
  - 新增 CSV 字段：`moments_add_images`（是/否）、`moments_image_paths`（多图路径，`|` 分隔）。
  - 当 `moments_add_images=是` 时，脚本会逐张上传图片（按路径顺序，最多9张）。
  - 上传前校验：仅 `jpg/png`，单张小于 10MB，文件必须存在。
  - 当 `moments_add_images=否` 时，自动跳过图片上传。
- UI 模板（CSV/XLSX 下载）同步增加上述字段，并添加业务提示文案。
- UI 直接上传朋友圈图片能力：
  - 上传页新增“朋友圈上传图片 + 图片文件选择”控件（无需手工改本地CSV路径）。
  - 勾选后会把图片保存到 `ui_uploads/<task_id>_images/`，并自动回写任务CSV：
    - `moments_add_images=是`
    - `moments_image_paths=本地保存路径（按上传顺序）`
  - 这样业务只需要在UI上传 CSV + 图片即可执行，不需要手工在企业页面点文件夹。

### 本轮新增（Windows 一键使用）
- 新增 Windows 一键启动脚本：`scripts/windows/windows_start_ui.bat`
  - 自动创建 `.venv`
  - 自动安装 `requirements.txt` + `requirements-ui.txt`
  - 自动执行 `playwright install chromium`
  - 自动打开 `http://127.0.0.1:8790`
- 新增桌面图标生成脚本：`scripts/windows/create_desktop_shortcut.ps1`
  - 一次执行后在桌面生成“精准营销自动化工具”快捷方式
- 新增 Windows 打包脚本：`scripts/windows/build_windows_exe.bat`
  - 在 Windows 上可打包 `dist/PrecisionMarketingUIStarter.exe`
- README 已新增 Windows 使用说明，便于发给非技术执行同事。
- 新增“单文件下载包”输出：
  - 脚本：`scripts/windows/build_windows_release_zip.py`
  - 产物：`release/precision-marketing-auto-windows-oneclick.zip`
  - 同事可直接下载 zip，解压后双击 `scripts/windows/windows_start_ui.bat`。

---

## 维护约定
- 每次会话结束前更新本文件：
  - 今天做了什么
  - 完成了哪些
  - 下一步做什么
- 关键可回退版本必须同步写入“已打稳定标记”。
