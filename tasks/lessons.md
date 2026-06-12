# Lessons

## 2026-06-12 Windows 启动器兼容性

- 问题：`v1.0.35/v1.0.36` 为了解决二次双击和日志可观测性，把浏览器打开方式改成多路径兜底，并改写了 UI 服务启动包装；结果在部分 Windows 业务电脑上出现二次双击打不开、本地 `127.0.0.1:8790/simple` 无法访问，且 Chrome 多开页面。
- 已验证可行方案：`v1.0.24` 的简单启动路径在至少一台业务电脑上可反复打开；`v1.0.37` 恢复该兼容路径后，用户确认可以成功打开。
- 固化规则：Windows `start.bat` 的服务启动和打开页面逻辑应保持简单兼容，不要轻易叠加多种浏览器打开兜底。当前可靠合同是：
  - 服务启动使用 `start "Precision Marketing UI Server" /min cmd /c ""%SERVER_CMD%" > "%UI_LOG%" 2>&1"`。
  - 打开业务页只使用单一 `start "" "%UI_URL%"`。
  - 不使用 CDP `/json/new`、Chrome `--new-window`、`explorer.exe`、`rundll32` 等连续兜底打开 `/simple`，避免多开页面。
- 后续要求：任何 Windows 启动器改动必须先对比 `v1.0.24/v1.0.37` 的兼容路径，并更新 `tests/test_windows_launcher_contract.py` 防止回归。
