# TODO

## 2026-06-11 同步 v1.0.29 到 GitHub

- [x] 核对当前 Git remote 和分支
- [x] 从已发布的 `v1.0.29` 安装包恢复当前源码
- [x] 复核 `/simple` 是否仍符合文本粘贴 + 图片/门店文件上传的新方案
- [x] 补充测试覆盖 `/simple` 页面合同和 CDP 持久备用浏览器
- [x] 运行测试
- [x] 提交并推送到 GitHub

### 成功标准

- GitHub 上包含当前业务试运行需要的 `/simple` 新流程、Chrome 插件和 Windows/Mac 启动脚本。
- 不提交 `.env.local`、发布 zip、runtime cache 等本地/敏感/大体积文件。
- 测试证明 `/simple` 没退回旧 Excel 流程，CDP 不兼容时可使用持久备用浏览器。

### Review

- 已从 `release/PrecisionMarketingAuto-v1.0.29-mac.zip` 恢复当前 app 源码到仓库根目录。
- `/simple` smoke 通过：`/api/runtime` 返回 `version=1.0.29`，`/simple` 页面包含新增粘贴框、图片顺序上传、门店文件、草稿、复制日志等当前新方案元素。
- 已提交并推送到 GitHub：`d0546a0 feat: sync simple workflow and review assistant`。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（13 tests OK）。

## 2026-06-11 执行员工加盟区域漏选

- [x] 定位 `执行员工: 肇云营运区` 未勾选加盟区域的判定链路
- [x] 收紧执行员工回读校验：加盟目标必须明确命中加盟节点
- [x] 增加单元测试覆盖非加盟不能替代加盟
- [x] 运行测试
- [x] 发布新版并同步 GitHub

### 成功标准

- `/simple` 默认包含加盟区域时，`执行员工: 肇云营运区` 必须尝试并校验 `肇云营运区加盟`。
- 若页面只选中/回读 `肇云营运区`，不能把 `肇云营运区加盟` 判为成功。

### Review

- 根因：执行员工二级核心词兜底会去掉“加盟/营运区”等后缀，导致 `肇云营运区` 和 `肇云营运区加盟` 都简化为 `肇云`，页面只回读普通区域时也可能误判加盟目标通过。
- 已新增 `executor_targets_confirmed()`：非加盟目标可用核心词兜底；加盟目标必须明确命中完整加盟节点。
- 已将执行员工两处回读判断改为使用该函数，并在 loose fallback 中禁止加盟目标走普通核心词替代。
- 已新增测试覆盖“普通肇云不能替代肇云加盟”。
- 已构建并发布 `v1.0.30`；公网 `latest.json` 返回 `1.0.30`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（14 tests OK）。

## 2026-06-11 Windows 误点 start.command

- [x] 确认 Windows 包内是否同时包含 Mac 启动文件
- [x] 调整 Windows 发布包：根目录只保留 `start.bat`
- [x] 增加 Windows 快速开始说明，提示双击 `start.bat`
- [x] 构建发布新版并验证 zip 内容

### 成功标准

- Windows 同事解压后不会再看到/误点根目录 `start.command`。
- 下载包根目录有明确说明：Windows 请双击 `start.bat`。

### Review

- 根因：Windows 发布包根目录同时包含 `start.bat` 和 Mac 专用 `start.command`，同事误点 `start.command` 后 Windows 弹出“如何打开 .command 文件”。
- 已发布 `v1.0.31`：Windows zip 根目录只保留 `start.bat`，并新增 `WINDOWS_START_HERE.txt`；Windows 包内不再包含 `start.command`。
- Mac zip 仍保留 `start.command`。
- 公网 `latest.json` 返回 `1.0.31`，Win/Mac zip 均 HTTP 200。

## 2026-06-11 Windows 二次双击不唤起浏览器

- [x] 定位 Windows `start.bat` 二次启动复用服务时的打开页面路径
- [x] 增加统一打开 `/simple` 子程序，优先 Chrome，失败再系统默认打开
- [x] 首次启动和服务已运行分支都改用统一子程序
- [x] 构建发布新版并验证 Windows 包内容

### 成功标准

- 服务已运行时再次双击 `start.bat`，也会重新打开 `http://127.0.0.1:8790/simple`。
- 首次启动成功后仍会自动打开页面。

### Review

- 根因判断：服务复用分支和首次启动成功分支都依赖单一 `start "" "%UI_URL%"` 打开默认浏览器，在部分 Windows 环境下二次双击没有唤起页面。
- 已新增 `:OPEN_UI` 子程序：优先用 Chrome 路径打开 `/simple`，失败再用 PowerShell `Start-Process`，最后回退到 `start "" "%UI_URL%"`。
- 服务已运行分支和 `UI_READY` 分支均改为调用 `:OPEN_UI`。
- 已新增静态测试覆盖二次启动复用分支和打开页面多级兜底。
- 已构建并发布 `v1.0.32`；Windows zip 根目录仍只包含 `start.bat` 和 `WINDOWS_START_HERE.txt`，不含 `start.command`。
- 公网 `latest.json` 返回 `1.0.32`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（16 tests OK）。

## 2026-06-11 Windows 二次双击仍未唤起浏览器

- [x] 增加 Chrome CDP `/json/new` 打开新标签页兜底
- [x] 增加 `explorer.exe URL` 兜底，覆盖默认浏览器关联异常
- [x] 更新 Windows 启动器测试
- [x] 构建发布新版并验证 Windows 包内容

### 成功标准

- Chrome CDP 已运行时，二次双击可通过 DevTools 接口强制打开 `/simple` 新标签页。
- 即使普通 `start URL` 不生效，也还有 PowerShell 和 explorer 兜底。

### Review

- 已增强 `:OPEN_UI`：优先调用 Chrome CDP `http://127.0.0.1:18800/json/new?...` 强制打开 `/simple` 新标签页；兼容 `PUT` 和普通请求。
- 后续兜底顺序为：Chrome 路径打开、PowerShell `Start-Process`、`explorer.exe URL`、Windows `start "" URL`。
- 已更新测试覆盖 CDP `/json/new` 和 `explorer.exe` 兜底。
- 已构建并发布 `v1.0.33`；Windows zip 根目录仍只有 `start.bat` 和 `WINDOWS_START_HERE.txt`，不含 `start.command`。
- 公网 `latest.json` 返回 `1.0.33`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（16 tests OK）。

## 2026-06-12 Windows 打开命令返回成功但页面未显示

- [x] 取消 `OPEN_UI` 中间步骤成功即退出的逻辑
- [x] 改为连续尝试 CDP、Chrome、PowerShell、explorer、rundll32、start
- [x] 更新测试，防止打开页面逻辑再次提前退出
- [x] 构建发布新版并验证 Windows 包内容

### 成功标准

- 某个打开命令返回成功但没有显示页面时，后续兜底命令仍会继续执行。
- 二次双击 `start.bat` 至少会通过一种方式唤起 `/simple` 页面。

### Review

- 根因进一步收敛：`v1.0.33` 在 CDP `/json/new` 返回成功后立即退出 `OPEN_UI`，但部分 Windows/Chrome 环境中该成功并不代表页面被拉到前台。
- 已取消 `OPEN_UI` 中的中途成功退出，改为连续尝试：CDP `/json/new`、Chrome `--new-window`、PowerShell `Start-Process`、`explorer.exe`、`rundll32 url.dll,FileProtocolHandler`、Windows `start`。
- 已新增测试防止 `OPEN_UI` 再出现 `if not errorlevel 1 exit /b 0` 的提前退出。
- 已构建并发布 `v1.0.34`；Windows zip 根目录仍只有 `start.bat` 和 `WINDOWS_START_HERE.txt`。
- 公网 `latest.json` 返回 `1.0.34`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（17 tests OK）。

## 2026-06-12 Windows 自更新后服务未启动

- [x] 定位 `start.bat.pending` 自更新分支是否会中断启动链路
- [x] 改为当前窗口同步应用 `start.bat.pending` 后继续启动
- [x] 增加测试禁止 pending 分支再用最小化后台中转
- [x] 构建发布新版并验证 Windows 包内容

### 成功标准

- 自动更新启动器后，同一次双击仍继续进入依赖检查、服务启动和打开页面流程。
- 如果启动器更新失败，窗口要停留并提示日志位置，不再“闪一下就没了”。

### Review

- 根因进一步定位：`start.bat.pending` 分支位于脚本最开头，旧逻辑会启动一个最小化中转窗口应用更新，然后当前窗口直接退出；若中转窗口没有继续跑，就会出现“终端闪一下、服务没启动、手动访问 8790 也打不开”。
- 已改为当前窗口同步应用 `start.bat.pending`，删除 pending 后继续正常启动流程，不再使用最小化中转窗口。
- 如果启动器更新失败，会停留窗口并提示 `data\logs`，不再静默闪退。
- 已新增测试覆盖 pending 分支：必须同步 copy、继续启动，且不能包含 `/min cmd` 或成功后直接 `exit /b 0`。
- 已构建并发布 `v1.0.35`；公网 `latest.json` 返回 `1.0.35`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（18 tests OK）。
