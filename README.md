# 精准营销平台自动化

基于 Playwright 的精准营销平台批量自动化工具。

## 功能

- ✅ 登录保持（一次扫码，后续自动保持）
- ✅ CDP 接管已登录 Chrome（适合内网 + VPN 场景）
- ✅ 第1步：基础信息（12个字段自动填充）
- ✅ 第2步：目标分群
  - iframe 检测与操作
  - 名称填充
  - 更新方式选择
  - 主消费营运区（树形选择器）
  - 券规则ID填充
  - 预跑按钮点击
- ✅ 第3步：触达内容 + 保存
- ✅ CSV 批量处理
- ✅ 并发执行

## 环境要求

- Python 3.10+
- Playwright

## 安装

```bash
# 克隆项目
git clone https://github.com/lmr1123/precision-marketing-auto.git
cd precision-marketing-auto

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install playwright
playwright install chromium
```

## 使用

### 单条测试

```bash
python precision-auto-playwright-batch.py --test
```

### 接管当前 Chrome（推荐内网场景）

先手动启动支持远程调试的 Chrome（示例）：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-pma-debug
```

在该 Chrome 中先登录企业系统，再执行：

```bash
python precision-auto-playwright-batch.py --test --connect-cdp
```

### CSV 批量处理

```bash
python precision-auto-playwright-batch.py --csv data/plans.csv
```

### 可视化任务中心（低门槛）

说明：这是独立新增的 UI 层，底层仍复用 `precision-auto-playwright-batch.py`，不会改动现有命令行能力。

1. 安装 UI 依赖

```bash
pip install -r requirements-ui.txt
```

2. 启动 UI

```bash
uvicorn ui_app.server:app --host 0.0.0.0 --port 8787 --reload
```

3. 浏览器打开

```text
http://127.0.0.1:8787
```

UI 支持：
- 批量导入多个 CSV 文件并入队
- 串行/并行执行（按文件维度）
- 实时日志查看（与脚本日志一致）
- 任务列表总览（状态、开始时间、完成时间、预计完成时间、耗时、成功/失败）
- 失败任务一键重试（单条/全部失败）

## 配置

修改脚本中的 `BASE_URL` 为当前可用的测试链接。

## 关键参数

- `--connect-cdp`：通过 CDP 接管当前 Chrome，复用已有登录态
- `--cdp-endpoint`：CDP 地址，默认 `http://127.0.0.1:9222`
- `--concurrent`：并发数（CDP 模式自动降为 1，优先稳定）
- `--hold-seconds`：任务结束后保持浏览器秒数，默认 `0`
- `--strict-step2`：开启第2步严格校验（默认关闭，便于先联调其它流程）
- `--skip-step2`：跳过第2步内容，仅验证第1步和第3步流程
- `--manual-executor`：第3步“执行员工”改为手动勾选，终端回车后继续并自动打印调试信息

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 注意事项

1. 需要公司内网访问
2. URL 会过期，需要及时更新
3. 首次运行需要扫码登录企业微信

## 版本

- v15 (2026-03-02): 完整功能版
