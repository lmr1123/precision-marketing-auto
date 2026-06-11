# TODO

## 2026-06-11 同步 v1.0.29 到 GitHub

- [x] 核对当前 Git remote 和分支
- [x] 从已发布的 `v1.0.29` 安装包恢复当前源码
- [x] 复核 `/simple` 是否仍符合文本粘贴 + 图片/门店文件上传的新方案
- [x] 补充测试覆盖 `/simple` 页面合同和 CDP 持久备用浏览器
- [x] 运行测试
- [ ] 提交并推送到 GitHub

### 成功标准

- GitHub 上包含当前业务试运行需要的 `/simple` 新流程、Chrome 插件和 Windows/Mac 启动脚本。
- 不提交 `.env.local`、发布 zip、runtime cache 等本地/敏感/大体积文件。
- 测试证明 `/simple` 没退回旧 Excel 流程，CDP 不兼容时可使用持久备用浏览器。

### Review

- 已从 `release/PrecisionMarketingAuto-v1.0.29-mac.zip` 恢复当前 app 源码到仓库根目录。
- `/simple` smoke 通过：`/api/runtime` 返回 `version=1.0.29`，`/simple` 页面包含新增粘贴框、图片顺序上传、门店文件、草稿、复制日志等当前新方案元素。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest discover -s tests`（13 tests OK）。
