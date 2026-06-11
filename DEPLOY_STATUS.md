# 精准营销自动化 - 部署进度总结

**更新日期**: 2026-06-08

---

## 一、已完成工作

### 1. server.py 路径配置 (PM_DATA_DIR)

文件: `ui_app/server.py` (第32-61行)

实现了 app/data 目录分离的部署结构，支持三级检测:
1. 环境变量 `PM_DATA_DIR`
2. 同级 `data/` 目录存在 → 使用 `ROOT.parent / "data"`
3. 兜底使用 `ROOT`

导出模板也支持环境变量 `PM_EXPORT_TEMPLATE` 覆盖。

### 2. 部署脚本 (scripts/deploy/)

| 文件 | 用途 |
|------|------|
| `start.bat` | Windows 启动器（6步：更新→Python→依赖→CDP→服务→浏览器） |
| `auto_update.ps1` | PowerShell 自动更新脚本 |
| `start.command` | Mac 启动器 |
| `auto_update.sh` | Mac 自动更新脚本 |
| `build_release.py` | 构建发布包（app/data 分离） |
| `prepare_embedded_python.py` | Windows 嵌入式 Python 构建 |
| `index.html` | 中文引导页 |
| `VERSION.txt` | 当前版本号 1.0.3 |

**关键设计**:
- 启动器默认打开 `/simple` 页面（文本粘贴），不是文件上传首页
- `start.bat` 支持零依赖：自动下载嵌入式 Python 3.11
- 自动更新只替换 `app/`，不动 `data/`
- 更新服务器地址: `http://49.232.195.165`

### 3. 构建系统

- 当前版本: **v1.0.3**
- 构建产物: `PrecisionMarketingAuto-v1.0.3-win.zip` (约158KB) / `mac.zip` (约157KB)
- APP_FILES 列表包含: server.py, text_plan_parser.py, precision-auto-playwright-batch.py, browser_extension/*, requirements.txt, data/plans.csv

### 4. 腾讯云服务器部署

**服务器信息**:
- IP: `49.232.195.165`
- 系统: Ubuntu 24.04
- Web服务器: **Caddy**（不是 Nginx）
- SSH: user=`ubuntu`, password=`Hermes123`（需 `PubkeyAuthentication=no`，密钥有密码短语）

**Caddy 配置**:
- 端口 80 提供 pm-auto 静态文件服务
- `/latest.json` 无缓存 + CORS
- `/releases/` 1天缓存
- 同时代理 `/api/review/*`

**服务器文件** (`/var/www/pm-auto/`):
```
latest.json        # v1.0.3，IP 地址 URL
index.html         # 中文引导页
releases/
  PrecisionMarketingAuto-v1.0.3-win.zip
  PrecisionMarketingAuto-v1.0.3-mac.zip
extension/         # Chrome 扩展（预留）
```

### 5. /simple 页面默认打开修复

- `start.bat`: 分离 `BASE_URL`（健康检查用）和 `UI_URL`（浏览器打开 = `/simple`）
- `start.command`: 同理，`OPEN_URL="$UI_URL/simple"`

### 6. v1.0.3 发布包启动修复

- `start.command`: CDP 启动支持 `/Applications/Google Chrome.app` 和 `/Applications/Google Chrome Beta.app`，并使用独立 `data/chrome-cdp-profile`。
- `start.command` / `start.bat`: 启动 CDP Chrome 时增加 `--no-first-run`、`--no-default-browser-check`，并打开 `https://precision.dslyy.com/admin#/dashboard` 方便业务先登录。
- `auto_update.sh`: Mac 自动更新优先读取 `latest.json.url_mac`，避免误下载 Windows 包。
- `auto_update.ps1`: Windows 自动更新优先读取 `latest.json.url_win`。
- `precision-auto-playwright-batch.py`: CDP 接管增加 `/json/version` 预检；`connect_over_cdp` 默认 15 秒超时、2 次重试，并支持 `--cdp-timeout-ms` / `--cdp-retries`。

---

## 二、已处理问题: CDP 连接超时 / 启动包不拉起业务系统

### 现象

用户在 `/simple` 页面粘贴文本 → 点击"开始执行" → 任务状态为 running，但 Chrome **没有打开新标签页**进行自动化填充。

### 日志分析

```
🔌 通过 CDP 接管已有浏览器: http://127.0.0.1:18800
⚠️ CDP 连接失败(1/3): BrowserType.connect_over_cdp: Timeout 180000ms exceeded.
  - <ws preparing> retrieving websocket url from http://127.0.0.1:18800
  - <ws connecting> ws://127.0.0.1:18800/devtools/browser/ae3805de-...
  - <ws connected>  ← WebSocket 连接成功，但 Playwright 初始化超时
```

**关键线索**: WebSocket 连接成功（`<ws connected>`），但 Playwright 在 180 秒内无法完成浏览器初始化。重试 3 次后失败。

### 环境信息

| 组件 | 版本/值 |
|------|---------|
| Chrome | 149.0.7827.54 |
| Playwright (venv) | **1.58.0** |
| Python (venv) | 3.14.5 |
| CDP 端口 | 18800 |
| Chrome Profile | `/tmp/pm-auto-chrome-proxy`（有缓存 SSO 登录） |

### 可能原因

1. **Playwright 1.58.0 与 Chrome 149 不兼容** — Chrome 149 较新，Playwright 可能尚未适配其 CDP 协议变更
2. **Chrome profile 状态异常** — `/tmp/pm-auto-chrome-proxy` 可能有损坏的会话数据
3. **Chrome 内部挂起** — 某个内部请求（如扩展、同步）阻塞了 CDP 初始化
4. **Mac 启动器只查找普通 Google Chrome** — 用户机器实际使用 Google Chrome Beta 时，UI 可启动但 CDP 浏览器未启动。
5. **Mac 自动更新误用 Windows 包 URL** — 旧版 `auto_update.sh` 读取 `latest.json.url`，而该字段指向 Windows 包。

### v1.0.3 处理结果

- 已发布 `v1.0.3` 到 `http://49.232.195.165/latest.json`。
- 服务器本机验证：`latest.json` 返回 `1.0.3`；`/releases/PrecisionMarketingAuto-v1.0.3-mac.zip` 返回 HTTP 200。
- 本机验证：脚本语法检查通过；Python 语法检查通过；`tests.test_batch_script` / `tests.test_text_plan_parser` / `tests.test_simple_target_fields` 共 36 项通过。
- CDP 不可用失败路径 smoke：连接不存在端口时约 1 秒内输出清晰 `CDP 预检失败`，不再等待 180 秒。

### 建议排查步骤

```bash
# 1. 验证 CDP
curl http://127.0.0.1:18800/json/version

# 2. 手动登录 precision.dslyy.com（在启动器打开的 CDP Chrome 窗口中）

# 3. 重新测试
# 打开 http://127.0.0.1:8790/simple → 粘贴文本 → 执行
```

---

## 三、下一步计划

### P0 - 立即解决（阻塞端到端测试）

1. **业务机复测 v1.0.3**
   - 下载/自动更新到 `v1.0.3`
   - 双击启动器后确认打开一个独立 Chrome/Chrome Beta 窗口，并能访问 `precision.dslyy.com`
   - 在该窗口完成登录后，再到 `/simple` 粘贴文本执行

### P1 - 端到端测试验证

2. **Mac 本地完整测试**
   - `/simple` 页面粘贴 → 执行 → Chrome 打开 precision.dslyy.com → 自动填充 → 成功
   - 验证 7 个渠道样本（docs/simple_text_samples.md）至少通过 1-2 个

3. **Windows 端到端测试**
   - 从服务器下载 zip → 解压 → 双击 start.bat → 自动下载 Python → 安装依赖 → UI 打开 → 执行任务

### P2 - 可选优化

4. **域名 + SSL**（用户说"先不用"）
   - 用户已购买腾讯云域名服务（非 dslyy.com）
   - 配好后更新 Caddy 配置 + latest.json URL

5. **start.bat 中 CDP Chrome 自动启动逻辑**
   - 当前 start.bat 会启动 Chrome 带 `--remote-debugging-port=18800`
   - 如果用户机器没有 Chrome，需要处理 fallback

---

## 四、关键文件路径速查

```
项目根目录: /Users/liminrong/precision-marketing-auto
核心脚本:   precision-auto-playwright-batch.py (~8655行)
UI 服务:    ui_app/server.py (~5770行)
文本解析:   ui_app/text_plan_parser.py
部署脚本:   scripts/deploy/
构建脚本:   scripts/deploy/build_release.py
测试样本:   docs/simple_text_samples.md
版本号:     VERSION.txt (当前 1.0.3)
```

## 五、服务器操作备忘

```bash
# SSH 连接（需要 expect，密钥有密码短语）
expect -c '
  spawn ssh -o PubkeyAuthentication=no ubuntu@49.232.195.165
  expect "password:"
  send "Hermes123\r"
  interact
'

# 上传文件
expect -c '
  spawn scp -o PubkeyAuthentication=no <本地文件> ubuntu@49.232.195.165:/var/www/pm-auto/
  expect "password:"
  send "Hermes123\r"
  expect eof
'

# 远程重载 Caddy
ssh ... "sudo systemctl reload caddy"

# 构建新版本并发布
cd /Users/liminrong/precision-marketing-auto
python3 scripts/deploy/build_release.py --version 1.0.3
# 然后上传 latest.json + releases/*.zip 到服务器
```

## 六、历史成功任务参考

任务 `77e47f3e` (2026-06-08 10:49) 成功执行，CDP 端口 18801，耗时 56 秒:
- 渠道: 智能电话
- 计划名: 【QW回归2-智能电话-请删除】活动介绍
- 34 个字段结果: 31 ok, 3 warn, 0 fail

说明脚本逻辑本身是正确的，问题仅在 CDP 连接层。
