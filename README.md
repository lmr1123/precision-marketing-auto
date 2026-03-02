# 精准营销平台自动化

基于 Playwright 的精准营销平台批量自动化工具。

## 功能

- ✅ 登录保持（一次扫码，后续自动保持）
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

### CSV 批量处理

```bash
python precision-auto-playwright-batch.py --csv data/plans.csv
```

## 配置

修改脚本中的 `BASE_URL` 为当前可用的测试链接。

## 注意事项

1. 需要公司内网访问
2. URL 会过期，需要及时更新
3. 首次运行需要扫码登录企业微信

## 版本

- v15 (2026-03-02): 完整功能版
