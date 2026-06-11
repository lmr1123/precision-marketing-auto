# TODO

- [x] 复现桌面图标点击后 127.0.0.1:8790 无法打开的问题（mac + windows 启动链路）
- [x] 定位根因（启动脚本路径/工作目录/依赖缺失/端口冲突/静默退出）
- [x] 最小修改修复启动链路（优先脚本层，不改业务逻辑）
- [x] 本机端到端验证（脚本启动 -> 端口监听 -> API 可访问 -> 页面可访问）
- [x] 更新安装包并给出业务可直接替换步骤

## Review
- 根因聚焦在 Windows 启动脚本链路：先开浏览器后启服务会导致 127.0.0.1 拒绝连接的“假失败”；服务启动失败时没有稳定暴露日志，业务误判为“网页打不开”。
- 已修复 `scripts/windows/windows_start_ui.bat`：
  - 启动前检测 8790 端口，已运行则直接打开页面。
  - 后台启动 uvicorn 并写入 `logs/ui_server.log`。
  - 增加健康检查，`/api/tasks` 可访问后再打开浏览器。
  - 启动失败自动打印最近 40 行日志并暂停。
- 已重新打包 Windows 一键包，可直接替换给业务。

## 2026-05-22 业务试运行痛点升级方案

- [x] 建立多 agent 共享上下文 `tasks/agent_context.md`
- [x] 建立并行开发看板 `tasks/parallel_board.md`
- [x] 建立经验沉淀文件 `tasks/lessons.md`
- [x] 启动输入解析线：评估“上传文本 + 图片包”到内部计划的解析方案
- [x] 启动结果协议线：评估逐条创建结果、复核链接、复核清单的结构化输出方案
- [x] 启动字段缺口线：盘点现有字段覆盖、历史失败、需要人工演示的字段
- [x] 汇总并行 agent 结论，形成第一阶段实施计划
- [x] 确认第一阶段采用强约束文本模板
- [x] 确认图片主流程改为逐计划上传、按选择顺序执行
- [x] 确认同时支持 `.txt` 上传和页面粘贴框
- [x] 确认新建简洁操作页面，和旧复杂任务中心分离
- [x] 确认图片顺序规则（小程序封面 vs 朋友圈/社群多图）
- [x] 确认简洁操作页上线方式（默认首页或新路径试用）
- [x] 与用户确认第一阶段实施范围后再改业务代码
- [x] 新增强约束文本解析模块与测试
- [x] 新增 `/simple` 简洁操作页
- [x] 新增简洁页上传接口：支持 `.txt` 上传、页面粘贴、多计划图片逐条上传
- [x] 按图片上传顺序写入现有执行字段
- [x] 简洁页提交后自动入队执行并显示逐行结果/错误说明
- [x] 运行单元测试、语法检查和本地页面验证
- [x] 调整 `/simple` 文本字段逻辑：显式支持创建链接、目标商品编码、已领或已使用券规则ID、多值“、”
- [x] 生成 3-5 条覆盖不同渠道/渠道组合的真实小样本文本
- [x] 支持多渠道单计划分别填写 `短信内容` 和 `发送内容`
- [x] 核对并保留组合渠道创建链接与加盟区域默认同步逻辑
- [x] 更新真实小样本文本：营销主题改为 `其他、新店营销`，内容支持换行和表情
- [x] 真实打开 `/simple` 页面完成小样本提交验证
- [x] 修复第2步商品编码上传后“弹窗已选中但主行回读为0/保存后卡住”的执行链路
- [x] 继续收敛执行员工选择后“全国残留/重叠”复核风险
- [x] 从保存响应 `activityId` 提取或构造真实计划查看/编辑链接，替代当前模板创建链接
- [ ] 设计“无 VPN 人工介入”的内网目标人群配置自验证方案：离线本地执行、采集日志/DOM/截图、联网后自动回传给 Codex 分析
- [x] 使用 no-proxy 独立 Chrome 重新跑完整 `/simple` 流程，重点验证第2步目标人群弹窗内嵌页面是否可加载和操作
- [x] 使用显式本地代理独立 Chrome 重新跑完整 `/simple` 流程，验证第2步目标人群 iframe 加载与保存
- [ ] 设计第2步目标人群“人工接管/断点续跑”模式，适配内网不能开 VPN 的操作限制

## 2026-05-23 真实流程复核修复计划

- [x] 修复商品编码复核：弹窗已选中但主行回读为0时，补充确认后等待/二次读回/同弹窗读回兜底，不能把未确认字段静默当成功
- [x] 修复执行员工复核：选择子区域后清理“全国”全选残留，若仍冲突则让任务失败而不是仅提示
- [x] 修复创建成功链接：从保存响应里的 `activityId` 提取真实计划标识，写入任务结果链接
- [x] 增加聚焦单元测试，覆盖真实链接解析和成功/失败摘要边界
- [x] 运行语法检查与相关测试；如条件允许，再用代理独立 Chrome 跑一条真实小样本

### 成功标准

- 商品编码字段结果不能在“主行回读为0”时误判通过；若页面确实回写慢，应通过等待/兜底读回变为明确通过。
- 执行员工若出现“全国 + 子区域”重叠，任务状态必须暴露失败或可读错误，不能让业务误以为完全成功。
- `/simple` 结果里的链接优先返回真实创建后的计划链接，保留模板链接只作为创建入口。

## 2026-05-23 `/simple` 字段复核展示

- [x] 后端解析运行日志里的字段结果清单，输出结构化 `field_results`
- [x] `/simple` 每行展示复核摘要和字段明细，失败字段优先显眼展示
- [x] 增加单元测试覆盖字段结果解析
- [x] 运行语法检查与聚焦测试

### Review

- 已在任务接口输出 `field_results` 和 `field_result_counts`，从运行日志里的 `✅/⚪/❌ 第x步-字段` 解析得到。
- `/simple` 结果列新增复核摘要：通过、待复核、失败数量，并展示字段明细；失败字段会用红色突出。
- 验证通过：`python3 -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`；本机 `/simple` 与 `/api/tasks` smoke。

## 2026-05-23 `/simple` 正式小样本回归（临时跳过第2步）

- [x] `/simple` 增加“跳过目标人群配置（第2步）”开关
- [x] 准备 3-5 条正式小样本文本：短信、客户消息、朋友圈、短信+客户消息组合
- [x] 使用独立 Chrome/CDP 真实跑样本，跳过第2步，验证第1步、第3步、保存、真实链接、字段复核展示
- [x] 若小问题能直接定位则修复并最多复跑 3 次；需要产品/业务决策时暂停
- [x] 记录回归结果和剩余风险

### Review

- 已实现 `/simple` 的“跳过目标人群”开关，并调整脚本：显式 `--skip-step2` 时所有渠道都可跳过第2步；默认行为不变。
- 正式小样本回归结果：
  - 短信单渠道：通过，21/21 字段 ✅。
  - 客户消息单渠道：通过，21/21 字段 ✅。
  - 短信 + 客户消息组合：通过，21/21 字段 ✅。
  - 朋友圈多图：首次用旧测试图失败，接口返回 `图片素材:上传图片大小不是有效值`；更换为正常尺寸 PNG 后复跑通过，21/21 字段 ✅。
- 已修复回归中发现的链接问题：不再使用浏览器上下文里的旧 editPlan URL 作为结果链接；保存请求体里的 `activityId` 会生成当前计划复核链接。链接校验样本返回 `https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=624128912372342784`。
- 验证通过：`python3 -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`。
- 剩余风险：本轮按用户要求跳过第2步，目标人群 iframe、商品编码、券规则 ID、主消费营运区等仍需到公司网络可访问 `cdp.dslyy.com` 时继续回归。

## 2026-05-23 `/simple` 社群渠道补充回归（临时跳过第2步）

- [x] 准备社群渠道小样本文本
- [x] 使用独立 Chrome/CDP 真实跑社群样本，验证第1步、社群第3步、保存、真实链接、字段复核展示
- [x] 若可定位小问题则修复并复跑，最多 3 次
- [x] 记录社群渠道回归结果和剩余风险

### Review

- 社群渠道已纳入真实小样本回归，样本任务 `21584d68-e99a-4897-9c78-f632522de2d0` 按用户要求跳过第2步。
- 第1步基础信息、营销主题、计划时间、发送时间，以及社群第3步结束时间、下发群名、发送内容均已真实填充；保存前发送内容回读长度为 28。
- 已修复保存成功误判：保存判定不再把保存前已存在的旧 editPlan/list 上下文 URL 当作本次提交成功。
- 已修复 UI 链接解析：`上下文页URL` 调试日志中的旧链接不再进入业务结果链接。
- 当前社群阻塞点：页面必填回读显示 `分配方式` 为空，保存未发出社群核心保存接口，任务正确失败。由于已达到 3 次回归尝试，本轮停止继续自动试错；下一步需针对社群单页的“分配方式”控件做一次 DOM/人工操作对照后再补选择器。
- 验证通过：`python3 -m py_compile ui_app/server.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_simple_target_fields tests.test_batch_script tests.test_text_plan_parser`。

## 2026-05-23 社群分配方式历史逻辑核对

- [x] 回看当前代码和历史提交中社群渠道分配方式逻辑
- [x] 确认 `/simple` 文本字段到脚本内部字段的映射是否沿用历史规则
- [x] 修正社群小样本文本或代码映射，避免把不存在的“指定门店分配”作为目标值
- [x] 运行最小测试并记录结论

### Review

- 历史跑通提交 `655eb7e` 显示：社群默认分配方式为 `按条件筛选客户群`；当上传门店时走 `导入门店/选中门店`。`指定门店分配` 是旧默认示例/非社群语义，不应作为社群文本输入。
- `/simple` 文本解析已增加社群分配方式校验：只接受 `按条件筛选客户群`、`按条件筛选客户`、`导入门店`、`选中门店`；其中 `选中门店` 归一为 `导入门店`。
- 新增单元测试覆盖社群分配方式别名和非法值拒绝。
- 验证通过：`python3 -m py_compile ui_app/text_plan_parser.py ui_app/server.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_text_plan_parser tests.test_simple_target_fields tests.test_batch_script`。

## 2026-05-23 社群两种分配方式真实回归

- [x] 准备 `按条件筛选客户群` 社群样本，跳过第2步，真实跑保存和链接
- [x] 准备 `导入门店` 社群样本，使用历史门店文件或可用小样本，真实跑保存和链接
- [x] 若发现小问题，最多各重试约 3 次并记录根因
- [x] 汇总两种方式的结果、字段复核和剩余风险

### 成功标准

- 两种方式都必须通过独立 Chrome/CDP 真实操作业务系统页面。
- 成功样本必须捕获社群核心保存接口或真实复核链接；不接受旧上下文 URL 作为成功证据。
- 若因门店文件/页面控件/网络限制失败，必须给出明确阻塞点。

### Review

- 已生成未来日期临时 CSV：
  - `/private/tmp/pm-community-condition-20260523.csv`
  - `/private/tmp/pm-community-import-20260523.csv`
- `按条件筛选客户群` 真实跑通：任务名 `【回归社群A-按条件-请删除】黑龙江武汉双区域`；分配方式选中；黑龙江省区、黑龙江省区加盟、武汉营运区、武汉营运区加盟均完成添加；已选中人数 2945；保存命中 `https://precision.dslyy.com/api/v1/precision/community-admin/activity/addOrUpdate`，HTTP 200；字段清单 20 项均为 ✅。
- `导入门店` 真实跑通：任务名 `【回归社群B-导入门店-请删除】门店上传`；分配方式选中；上传门店文件 `社群_门店上传文件.xlsx`，回读 `已上传 3 家`；保存命中 `https://precision.dslyy.com/api/v1/precision/community-admin/activity/addOrUpdate`，HTTP 200；字段清单 20 项均为 ✅。
- 两条社群保存接口响应体读取都超时，因此本次未取得 `activityId` 复核链接；当前成功证据来自核心保存接口 HTTP 200 和字段清单。
- 执行后 Playwright 有 `TargetClosedError` 的异步 future 噪音，发生在批量处理完成和浏览器保持阶段之后，不影响本次保存结论。

## 2026-05-24 `/simple` 第一阶段可试用版收口

- [x] 梳理当前 `/simple` 已支持字段、未支持字段和“允许业务创建后复核修改”的边界
- [x] 调整文本解析策略：未知/暂未自动化字段不让整条计划中断，进入警告/复核提示
- [x] 固化 5 类小样本：短信、客户消息、组合、朋友圈、社群两种分配方式
- [x] 优化创建结果展示：成功、链接、字段复核、未自动化字段提示必须清晰
- [x] 跑单元测试和必要的真实小样本回归

### 成功标准

- 业务按强约束模板提交时，核心字段自动创建；未覆盖字段明确提示为“需业务复核/手工补充”，不误报为成功填充。
- 未知字段不会直接导致无法提交，除非它是已知必填字段或取值非法。
- 结果页能让业务知道：创建是否成功、哪里需要复核、哪里要进业务系统手动改。

### Review

- 已将未实现字段从“阻断提交”改为“需业务复核/手工补充”警告；格式错误、缺少核心必填字段、社群分配方式非法仍会阻断。
- `/simple` 提交后会把未实现字段警告写入任务日志和字段复核区域，业务可以继续创建，再到业务系统复核编辑。
- 已新增固定样本文档：`docs/simple_text_samples.md`，覆盖短信、客户消息、短信+客户消息、朋友圈、社群按条件筛选、社群导入门店。
- 验证通过：`python3 -m py_compile ui_app/text_plan_parser.py ui_app/server.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_text_plan_parser tests.test_simple_target_fields tests.test_batch_script`；并解析校验 `docs/simple_text_samples.md` 6 个样本文本。
- 已执行本轮固定样本真实浏览器回归（跳过第2步）：短信、客户消息、短信+客户消息、社群按条件、社群导入门店成功；朋友圈在 6 条批量队列中失败一次，单独复跑成功。
- 已将 `/simple` 后台执行改为单 worker 串行，避免多个任务同时接管同一 CDP 浏览器导致页面互相干扰；同时修正非社群跳过第2步时的误导日志。
- 真实回归链接：
  - 短信：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=624200273291706368`
  - 客户消息：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=624200985337712640`
  - 短信+客户消息：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=624201757827870720`
  - 朋友圈单独复跑：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=624202452400418816`
- 社群两条批量样本字段清单均全绿，但本次批量结果页未拿到复核链接；此前单独导入门店复跑已确认链接捕获可成功。后续需要继续提升社群按条件保存响应捕获稳定性。

## 2026-05-24 复核协同路线补充

- [x] 明确当前阶段复核提醒的输出协议：页面结果、字段清单、需人工补充字段、创建链接
- [x] 将浏览器插件定位为人工协同复核层：业务逐页打开详情或弹窗，插件侧边栏对比原文与页面值并标红
- [x] 保持创建链路先稳定，不因未覆盖字段中断；后续根据插件复核结果逐步补自动化字段
- [x] 优先修复社群保存后 `activityId`/复核链接捕获，提高页面结果可用性

### Review

- 当前复核提醒分两层：`/simple` 执行结果显示创建状态、复核链接、字段清单、需人工补充字段；后续浏览器插件作为业务系统页面内的人工协同复核层。
- 插件定位已明确：业务逐页打开详情页或弹窗，插件侧边栏读取页面字段，与原始文本/创建结果对比，差异标红；先辅助人工判断和修改，稳定后再考虑自动修复。
- 社群保存响应体读取从 5 秒提升为有限长等待，已真实复跑 `导入门店` 样本并成功捕获复核链接：`https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=edit&activityId=624199635266777088`。
- 真实复跑样本 `【回归社群C-链接捕获-请删除】门店上传` 保存命中 `community-admin/activity/addOrUpdate`，返回 `code=A0200/msg=成功`，字段清单 20 项均为 ✅。首轮因 SSO 跳转重试一次，第二轮成功。

## 2026-05-24 社群复核链接捕获兜底

- [x] 查找社群列表/详情接口线索，确认是否能按计划名称反查 activityId
- [x] 在社群保存成功但未拿到响应体链接时增加低风险兜底
- [x] 增加单元测试覆盖兜底解析/链接构造
- [x] 运行测试，并用社群样本做真实验证

### 成功标准

- 社群保存成功后优先使用保存响应体 `activityId`；响应体超时或丢失时，尽量通过页面/接口兜底生成复核链接。
- 不把旧上下文页面 URL 当作当前任务链接。
- 兜底失败时创建仍应显示成功和字段清单，只把“链接缺失”作为剩余风险。

### Review

- 已实现社群列表 UI 兜底：保存成功但响应体/请求体没有稳定拿到链接时，进入 `communityPlanList`，用计划名称搜索并从表格行提取 `activityId`，构造 `addcommunityPlan?checkType=edit&activityId=...`。
- 兜底只操作已登录页面 UI，不读取 cookie、localStorage、鉴权 header。
- 新增 `extract_community_activity_id_from_rows` 单元测试，覆盖正常提取和相似名称误匹配防护。
- 验证通过：`python3 -m py_compile ui_app/text_plan_parser.py ui_app/server.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_batch_script tests.test_text_plan_parser tests.test_simple_target_fields`。
- 真实回归样本 `【回归社群D-列表兜底-请删除】门店上传` 跑通：保存接口 `community-admin/activity/addOrUpdate` 返回 HTTP 200，响应体读取超时但仍输出复核链接 `https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=edit&activityId=624206866641104896`，字段清单 20/20 通过。
- 已单独验证列表 UI 兜底：按同一计划名搜索社群列表，返回同一个复核链接 `https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=edit&activityId=624206866641104896`。

## 2026-05-23 正式小样本回归

## 2026-05-28 云端共享视觉复核代理部署

- [x] 确认腾讯云 SSH、sudo、项目目录可用
- [x] 安装云端 Python 依赖并创建独立服务用户
- [x] 写入云端 `.env.cloud`：仅保存 Ark key、模型名、共享复核 token，不在日志输出 key
- [x] 启动 `review-proxy` systemd 服务并验证本机健康检查
- [x] 配置公网窄代理暴露 `/api/review/`，验证公网健康检查
- [x] 给出插件填写方式、服务地址和共享 token

### 成功标准

- 业务同事插件只需要填写云端服务地址和共享 token，不需要知道 Ark key。
- 云端 `/api/review/health` 在 token 正确时返回 `ok=true`，无 token 时拒绝访问。
- 云端只开放复核代理接口，不暴露本地创建 UI。

### Review

- 已部署到腾讯云 `49.232.195.165`：`review-proxy.service` 运行在 `127.0.0.1:8790`，服务用户为 `pmreview`。
- 已写入云端 `.env.cloud`，包含 Ark key、`doubao-seed-2-0-lite-260428`、共享复核 token；部署过程未输出 Ark key。
- 服务器本机验证：带 token 访问 `http://127.0.0.1:8790/api/review/health` 返回 `ok=true`；无 token 返回 `401`。
- 公网直连 `80/443` 被腾讯云安全组或边界防火墙拦截，Caddy 本机路由正常但外部访问失败；已保留 Caddy 配置，后续放行安全组后可切换到正式域名/HTTPS。
- 临时公网入口采用独立 Cloudflare quick tunnel，先接到本机窄代理 `127.0.0.1:8791`：根路径返回 `404`，只转发 `/api/review/*` 到复核服务。
- 公网验证通过：`https://selections-rely-pre-cleveland.trycloudflare.com/api/review/health` 带 token 返回 `ok=true`，无 token 返回 `401`；实际 `/api/review/vision` 已成功调用 Ark 模型。
- Nginx 尝试后未使用，已禁用，避免重启后与现有 Caddy 抢占 `80` 端口；当前 `caddy`、`review-proxy`、`review-proxy-tunnel` 均为 enabled/active。

## 2026-05-28 新增发送渠道：智能电话

- [x] 确认字段口径：智能电话是否先只支持单渠道；“活动介绍”内容来源优先用 `活动介绍` 字段，未填时复用 `推送内容/发送内容`
- [x] 扩展文本解析、渠道归一化、默认创建链接，新增 `智能电话` 和创建链接 `useId=620450416034897920`
- [x] 扩展 CSV/任务字段：支持 `活动介绍`，并保留现有目标人群、主题、区域、商品/券等通用字段逻辑
- [x] 扩展 Playwright 第1步：智能电话默认 `计划区域=营运区`，任务有效期按起止日期时间填写
- [x] 扩展 Playwright 第3步：在自定义参数表中定位参数名称 `活动介绍`，把对应 `参数详情` 输入框填入活动介绍文案，并点击 `保存自定义参数`
- [x] 补充固定样本和单元测试，避免后续新增渠道时样本缺失
- [x] 本地语法/单元测试通过后，真实打开业务系统跑 1 条智能电话小样本回归
- [ ] 内网可访问 `cdp.dslyy.com` 后，补跑智能电话第2步主消费门店严格回归

### 成功标准

- `/simple` 可粘贴智能电话样本文本并生成任务，不需要业务手动填写创建链接。
- 创建时第1步通用字段、目标人群字段沿用现有能力；智能电话特有参数 `活动介绍` 能填到截图所示的 `参数详情` 输入框。
- 任务结果能输出创建成功/失败、复核字段结果；如果页面结构和截图不一致，应失败并给出明确字段定位错误。

### Review

- 已按确认口径实现：`活动介绍` 字段、`智能电话` 单渠道、默认创建链接 `useId=620450416034897920`、默认计划区域 `营运区`。
- `/simple` 固定样本已新增智能电话样本，目标人群样本按主消费门店文件路径：`data/ui-test/community/社群_门店上传文件.xlsx`。
- 智能电话第3步已适配：
  - 切换/识别智能电话渠道；
  - 真实打开 `任务有效期` 日期范围面板，写入计划开始/结束时间；
  - 按参数名称 `活动介绍` 定位同一行 `参数详情` 输入框并写入文案；
  - 点击 `保存自定义参数`，再点击页面主保存。
- 验证通过：`python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`python -m unittest tests.test_batch_script tests.test_text_plan_parser tests.test_simple_target_fields`。
- 首轮真实回归被用户复核指出不正确：`--skip-step2` 不能代表第2步主消费门店已填充；且旧选择器只显示脚本“已填充”，实际页面参数详情仍可能保留模板旧值。
- 已修复 `活动介绍` 定位：必须按表格/栅格行匹配左侧 `参数名称=活动介绍`，再写同一行右侧可编辑 `参数详情`；写后输出目标输入框可见回读，避免误写隐藏副本或禁用控件。
- 修复后真实回归结果（仍跳过第2步）：样本 `【回归-智能电话-请删除】活动介绍主消费门店` 创建成功，保存接口命中 `content-rights-setting/batch-create/v2`，复核链接 `https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=629761612210827264`；日志明确回读 `活动介绍参数详情回读: 您好，我是大参林药店的员工。来电是想通知您门店会员福利活动上线...`，`第3步-任务有效期`、`第3步-活动介绍` 均为 ✅。
- 第2步主消费门店严格回归（2026-06-08 09:23）仍未通过：不带 `--skip-step2` 执行时，目标人群 iframe 诊断连续为 `href=chrome-error://chromewebdata/, title=cdp.dslyy.com`，未进入主消费门店上传步骤。
- 本机网络检查：`scutil --proxy` 为空，`curl -I https://cdp.dslyy.com` 返回 `Could not resolve host`。当前失败点是内网域名解析/网络访问，不是主消费门店选择器已执行失败。
- 继续排查（2026-06-08）：Chrome Beta 默认资料即使带 `--remote-debugging-port=18801` 启动，也未开放可连接调试端口；Chrome 插件通道因机器仅有 Chrome Beta、插件脚本查找普通 Google Chrome 而无法接管。
- 已确认 iKuuuVPN/CorpLink 进程存在；iKuuu 日志显示当前代理端口应为 `7890`（系统代理）/`7891`（httplib）。下一步应通过 `curl -x http://127.0.0.1:7890 https://cdp.dslyy.com` 验证，再用独立 Chrome profile + `--proxy-server=http://127.0.0.1:7890` + CDP 跑严格第2步。
- 当前阻塞：沙箱外本机代理访问命令被工具审批系统 usage limit 拒绝，需用户显式批准/稍后重试后继续。
- 未完成项：需要在能解析并访问 `cdp.dslyy.com` 的浏览器环境中补跑第2步主消费门店严格回归；该项不能视为验收通过。

- [ ] 准备 3-5 条正式小样本文本，覆盖短信、客户消息、组合渠道、商品编码/券规则、可用时覆盖朋友圈图片
- [ ] 使用隔离 Chrome/CDP 和 `/simple` 提交回归任务
- [ ] 汇总每条任务状态、真实链接、字段复核结果
- [ ] 小问题自行修复并最多复测约 3 次；需要产品/业务决策时暂停确认
- [ ] 记录最终验证结论和下一步建议

### 成功标准

- 至少 3 条样本跑出明确结论：成功或具体失败原因。
- 成功样本必须返回真实创建结果链接和字段复核摘要。
- 若连续复测仍卡在同一外部条件或业务策略选择，停止并报告，不继续消耗。

## 2026-05-24 浏览器插件复核 MVP（进行中）

- [ ] 不跳过第2步目标人群，使用既有样本做完整端到端自测并记录结果
- [x] 复现并修复 `/simple` 粘贴内容测试失败，确保能复制复核数据给插件
- [x] 明确插件第一版只做“人工协同复核”，不自动改业务系统字段
- [x] 设计插件数据输入：从 `/simple` 执行结果复制/导入单条计划原文与字段清单
- [x] 设计侧边栏复核范围：当前打开的计划详情页/编辑页，读取可见字段值并与原文字段对比
- [x] 实现最小 Chrome 扩展：manifest、content script、sidebar/popup UI、字段提取和差异标红
- [x] 先支持核心字段：计划名称、营销主题、计划时间、发送时间、短信内容、发送内容、社群下发群名、结束时间、图片数量提示
- [ ] 在真实业务页面验证 2-3 条已创建计划，输出可用性结论和未覆盖字段
- [x] 验证扩展加载方式：测试 Chrome 可通过 `--load-extension` 启动，业务 Chrome 可通过扩展管理页加载
- [x] 实现 Ark 视觉接口本地代理：仅从环境变量读取 API Key，不写入代码/日志
- [x] 验证 Ark 视觉接口 smoke：仅使用环境变量读取 API Key，不写入代码/日志
- [x] 插件接入视觉兜底：仅对待复核字段手动触发，增加单页预算和截图缓存

### 成功标准

- 业务人员打开已创建计划页面后，能一键打开插件侧边栏查看“原文值 vs 页面值”。
- 差异项必须标红并给出字段名；无法读取的字段显示“待人工复核”，不能误报通过。
- 第一版不依赖业务系统后端接口、不读取鉴权信息，只读取当前页面 DOM 的可见内容。

### Review

- 已新增 Chrome 扩展目录 `browser_extension/review_assistant/`，包含 manifest、service worker、content script、side panel UI 和使用说明。
- `/simple` 结果页新增“复制复核数据”按钮，复制内容包含原始期望字段、创建链接、字段结果清单和复制时间，供插件侧边栏粘贴载入。
- 插件第一版只走 DOM 读取和规则对比；视觉模型调用统计固定为 0，后续再按预算策略接入。
- 已实现页面变化监听与 1.2 秒防抖；同页面状态重复复核会计入缓存跳过，不重复做昂贵检查。
- 已支持核心字段：计划名称、发送渠道、营销主题、计划区域、计划时间、发送时间、主消费营运区、执行员工、商品编码、券规则、员工任务结束时间、短信内容、发送内容、社群下发群名、分配方式、图片数量。
- 验证通过：Python 语法检查、25 个单元测试、扩展 manifest JSON 检查、3 个扩展 JS 文件 `node --check`。
- 本轮未完成真实业务页验证：需要在 Chrome 扩展管理页加载 `browser_extension/review_assistant/` 后，打开 2-3 条已创建计划页面实测 DOM 读取覆盖率。
- 已验证测试 Chrome 可通过 `--load-extension=/Users/liminrong/precision-marketing-auto/browser_extension/review_assistant` 启动扩展。
- Ark 视觉接口 smoke 尚未执行：当前 shell 没有 `ARK_API_KEY` 环境变量；为避免密钥进入代码、命令日志或 Git，不使用聊天里的明文 key 直接拼命令。
- 已新增本地代理接口 `POST /api/review/vision`：插件/本地调用只传截图和字段清单，服务端从 `ARK_API_KEY` 环境变量读取密钥并调用 Ark Responses API。
- 已验证未配置密钥时返回 `503 未配置 ARK_API_KEY，视觉兜底不可用`，不会误触发外部费用。
- 已完成 Ark smoke：使用 `.env.local` 中的 `ARK_API_KEY` 调用 `doubao-seed-2-0-lite-260428` 成功，返回字段 1 个，usage `input_tokens=1431/output_tokens=775/total_tokens=2206`；命令输出未打印密钥。
- 插件已接入“视觉复核待复核项”按钮：仅对 DOM 结果为待复核的字段手动触发；同页面状态和同字段组合会缓存；单页最多 3 次视觉调用。
- 插件视觉调用通过 `http://127.0.0.1:8790/api/review/vision` 本地代理，不在扩展中保存或暴露 Ark Key。
- 本轮未重复真实调用 Ark，避免为了包装层验证再次产生费用；已通过 manifest JSON、扩展 JS 语法、Python 语法和 27 个单元测试。
- 已复现 `/simple` 粘贴提交失败：根因不是文本解析，而是默认 CDP `127.0.0.1:18800` 未启动，自动化任务连接失败；同时发现“复制复核数据”在当前浏览器中因 `prompt()` fallback 不支持而失败。
- 已修复复制逻辑：`navigator.clipboard` 不可用时改用隐藏 textarea + `document.execCommand('copy')` 兼容复制；页面实测按钮会显示“已复制”。

### 成功标准

- 所有并行 agent 先读同一份上下文，避免重复解释项目背景。
- 每条并行线有明确写入边界、阻塞点和验收标准。
- 第一阶段方案必须服务于业务目标：业务只上传文本和图片，系统自动创建并返回逐条复核结果。
- 在用户确认第一阶段实施范围前，不改动 `ui_app/server.py` 或 `precision-auto-playwright-batch.py`。

### Review

- 已建立共享上下文、并行看板和 lessons 文件。
- 已启动 3 条只读并行线：
  - 输入解析线：建议第一阶段采用强约束中文键值文本，转内部 CSV/标准 dict 后复用现有链路；图片优先按 `计划图片ID` 匹配 ZIP。
  - 结果协议线：建议新增 `--result-jsonl` 和 `@@PM_RESULT@@` 哨兵日志，逐条输出创建、保存、复核结果；弱成功未复核时显示 `needs_review`。
  - 字段缺口线：高频失败集中在第2步主消费营运区、第3步执行员工、保存信号缺失、控件等待超时；建议优先补复核闭环。
- 用户已确认第一阶段文本采用强约束模板，并修正图片策略：不走 zip/ID 匹配，改为每条计划旁边手动上传图片，按选择顺序自动填写。
- 用户希望新建一个简洁操作页面：一列文本上传或粘贴框，一列对应图片上传，点击执行，执行后显示每行结果和直接错误说明。
- 用户后续会做浏览器插件侧边栏复核；当前项目内的复核结果仍应结构化输出，但主交互不必强制业务回到自动化 UI 修复。
- 实施默认假设：简洁页先挂 `/simple` 试用，不替换旧首页；图片顺序规则为“客户消息且有小程序字段时第1张作为小程序封面，第2张起作为内容图；朋友圈/社群按上传顺序作为内容图；短信忽略图片并提示”。
- 用户已正式确认：简洁页先放 `/simple` 试用；图片顺序规则接受。
- 已完成 `/simple` 第一阶段最小闭环：
  - 新增 `ui_app/text_plan_parser.py` 解析强约束中文键值文本，支持 `推送内容: |` 多行。
  - 新增 `/api/simple/submit`，逐行生成单计划 CSV，保存对应图片并自动入队执行。
  - 新增 `SIMPLE_HTML` 页面，支持 `.txt/.md` 批量导入、粘贴框、逐计划图片上传和结果轮询。
  - `Task.to_dict()` 新增 `error_summary`，简洁页失败时优先展示可读错误。
- 验证通过：`python3 -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_text_plan_parser tests.test_batch_script`；本地 `/simple` 页面和错误接口 smoke test。
- 用户要求真实小样本参考旧上传模板逻辑：样本文本要包含创建链接；目标人群筛选要覆盖购买目标商品编码、已领或已使用券规则ID；营销主题、主消费营运区、执行员工、目标商品编码、券规则ID多值统一用 `、` 分隔展示。
- 已补 `/simple` 文本预处理：`目标商品编码/购买目标商品编码` 普通多值会生成第2步商品编码上传文件；`已领或已使用券规则ID` 普通多值会转成脚本内部 `coupon_ids`；解析器新增 `目标商品编码` 别名。
- 验证通过：`python3 -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_text_plan_parser tests.test_simple_target_fields tests.test_batch_script`；`.venv/bin/python -m unittest tests.test_simple_target_fields`。
- 用户要求补充：单计划多渠道要区分不同渠道内容配置；推送内容/短信内容/发送内容支持换行和表情；营销主题统一改为 `其他、新店营销`；`主消费营运区` 和 `执行员工` 相关加盟区域默认同步能力不能丢。
- 已调整 `/simple` 文本解析：不再强制要求 `推送内容`，改为 `推送内容 / 短信内容 / 发送内容` 至少填写一个；`短信内容`、`发送内容` 均支持 `: |` 多行和表情。
- 已调整统一映射：`推送内容` 只作为空字段兜底，不再覆盖显式填写的 `短信内容` 和 `发送内容`。
- 已修复 `/simple` 组合渠道创建链接匹配：按渠道集合匹配 `短信 + 会员通-发客户消息`，避免排序导致误用短信单渠道模板。
- 加盟逻辑核对结果：`执行员工` 已通过 `/simple` 默认 `executor_include_franchise=True` 保留旧能力；`主消费营运区` 当前旧链路支持多值选择但没有独立“自动追加加盟节点”的通用逻辑，真实小样本先显式写多值，避免贸然改第2步树选择造成误选。
- 已通过独立测试 Chrome（`--user-data-dir=/tmp/pm-auto-chrome-profile --remote-debugging-port=18800`）真实打开 `/simple` 并提交组合渠道样本。
- 真实样本 1 `【Codex真实自测-组合-请删除】短信加客户消息`：保存接口返回 `code=A0200/msg=成功`，任务状态 `success`；组合创建链接、短信内容、客户消息多行表情内容、营销主题 `其他/新店营销`、执行员工包含加盟区域均有日志证据。
- 真实样本 2 `【Codex真实自测2-组合商品-请删除】短信加客户消息`：商品编码弹窗上传后回读 `已选中(2)`，但商品编码主行回读仍为 0，并且保存后任务停留 `running`；这暴露旧商品编码链路需要继续修复，不能视为通过。
- 真实样本日志再次出现执行员工“全国”残留/重叠提示，虽然保存可成功，但复核风险仍需单独收敛。
- 真实样本 1 保存响应里有 `activityId`，但 UI 的 `latest_link` 仍是模板创建链接；后续应把 `activityId` 转为真实计划查看/编辑链接，才能满足“创建成功后返回链接”的业务要求。
- 已修复成功任务 `error_summary` 误显示“任务失败，详情见日志”的 UI 数据问题，并补充单元测试。
- 新约束：目标人群配置涉及内网，业务网络不允许开 VPN；但 Codex/模型会话可能依赖外网/VPN。后续自验证不能要求用户边开 VPN 边操作内网页面，必须把内网执行变成可离线运行的本地脚本任务，执行完落盘证据后再由 Codex 分析。
- 已验证可行替代方案：使用独立 Chrome profile + `--no-proxy-server` + CDP 端口 `18801`，业务后台 `https://precision.dslyy.com/admin#/dashboard` 可正常打开并显示“首页 - 精准营销管理后台”。这说明可以让 Codex 保持在线，同时让业务测试 Chrome 直连内网页面。
- 用户补充：dashboard 能打开不代表目标人群弹窗可用，真正要验证的是点击目标人群配置后内嵌的另一套页面。下一轮必须跑完整流程并重点观察第2步 iframe。
- 用户补充环境限制：第2步目标人群配置涉及内网，不能开 VPN；而远程协作/思考可能依赖 VPN。后续不能假设全程在线自动化，应支持第2步暂停、用户断网/关 VPN 人工处理、再恢复执行。
- 已完成两条真实浏览器验证：
  - `--no-proxy-server` 独立 Chrome 可以打开 `https://precision.dslyy.com/admin#/dashboard`，但点击目标人群配置后内嵌 `cdp.dslyy.com` iframe 变成 `chrome-error://chromewebdata/`，无法加载。
  - 显式使用 iKuuuVPN 本地 HTTP 代理 `--proxy-server=http://127.0.0.1:12002` 的独立 Chrome 可以加载目标人群 iframe，日志显示 `title=创建分群 - 智能营销平台`，并完成保存，任务状态 `success`。
- 这次代理路径真实样本 `【Codex代理路径自测-组合-请删除】短信加客户消息` 验证通过：组合创建链接、短信内容、客户消息多行表情内容、第2步 iframe、券规则ID、保存请求均有日志证据。
- 仍未通过的复核点：商品编码上传弹窗显示 `已选中(2)`，但主行回读仍为 0，字段结果清单标记 `第2步-商品编码` 为未确认；执行员工仍出现“全国”残留/重叠提示。
- 2026-05-23 已修复并真实复跑通过：
  - 商品编码主行回读增强后，真实样本显示 `商品编码行回读: 已选：2`，字段清单 `第2步-商品编码` 为 ✅。
  - 修复商品编码 Python 数字解析误写为字面量 `\\d` 的问题；这是此前“已选：2 但判定为 0”的直接根因。
  - 执行员工调试只读取可见级联面板，避免隐藏旧面板把“全国”误报为当前选中；真实复跑 checkedNodes 不再包含“全国”全选。
  - 保存阶段增加响应体读取超时保护，避免核心保存请求已发出但 `resp.text()` 卡住导致任务长期 running。
  - 真实复跑任务 `b05f245a-8e45-44bb-9b62-0426af780861` 状态 `success`，`latest_link` 已返回真实复核链接 `https://precision.dslyy.com/admin#/marketingPlan/viewPlan?type=limit&id=624081307797884928&checkType=1`。
  - 验证命令通过：`python3 -m py_compile precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_batch_script tests.test_simple_target_fields tests.test_text_plan_parser`。

## 2026-05-26 `/simple` 不跳过第2步真实回归

- [x] 使用显式代理 Chrome `127.0.0.1:18801` 跑短信、客户消息、短信+客户消息、朋友圈样本
- [x] 核对第2步 iframe 是否真实加载 `cdp.dslyy.com`
- [x] 验证商品编码、券规则 ID、主消费营运区等第2步字段回读
- [x] 复跑社群两种分配方式，确认历史逻辑未回退
- [x] 修复回归中发现的小问题并复跑通过
- [x] 固化 `docs/simple_text_samples.md` 为后续新增渠道/字段的长期回归基线

### Review

- 无代理 Chrome `127.0.0.1:18800` 在第2步 iframe 进入 `chrome-error://chromewebdata/`，不能作为第2步回归环境；本轮使用 iKuuu 本地代理 `127.0.0.1:12002` 的 Chrome `127.0.0.1:18801` 完成验证。
- 组合样本成功：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=625134571331072000`，第2步商品编码 `已选：2`，券规则 ID 填充 2 处。
- 短信样本成功：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=625135164632133632`，第2步商品编码、券规则 ID、主消费营运区均通过。
- 客户消息样本成功：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=625139365592473600`，修复未配置券规则 ID 被字段清单误标红的问题后，结果为 `28 ok / 3 warn / 0 fail`。
- 朋友圈样本首次失败在第3步执行员工级联控件点击超时；已为级联勾选增加短超时 + DOM 事件点击兜底，复跑成功：`https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=625142307280199680`，结果为 `29 ok / 2 warn / 0 fail`。
- 社群按条件筛选成功：复核链接 `https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=edit&activityId=625140594775220224`，字段 `22 ok / 0 fail`。
- 社群导入门店成功：复核链接 `https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=edit&activityId=625140866125713408`，上传门店回读 `已上传 3 家`，字段 `22 ok / 0 fail`。
- 已将 `docs/simple_text_samples.md` 中无效的短信商品编码/券规则 ID 更新为本轮真实回读通过的值：`1010002、1012058` 和 `1-20000005313、1-20000005475`。
- 已补充样本维护规则：后续新增渠道组合或新增字段填充时，只在 `docs/simple_text_samples.md` 上增补；测试失败原因、真实链接和修复方式写入 `tasks/todo.md`，可复用经验同步到 `tasks/lessons.md`。
- 验证通过：`python3 -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`python3 -m unittest tests.test_text_plan_parser tests.test_simple_target_fields tests.test_batch_script`；`python3 -m unittest tests.test_batch_script`。

## 2026-05-26 插件复核数据随页面切换刷新

- [x] 复现/定位侧边栏一直显示旧计划 `【测试2-客户消息】新店会员福利` 的原因
- [x] 修复插件期望数据与当前业务页面计划不一致时的刷新/提示逻辑
- [x] 增加最小验证，确保切换到 `【试用-朋友圈-请删除】多图内容` 时不会继续展示旧客户消息期望值
- [x] 记录问题原因和后续使用注意事项
- [x] 修复扩展重新加载后仍自动恢复旧复核数据的问题
- [x] 修复扩展重新加载后旧 content script 报 `Extension context invalidated`

### 成功标准

- 侧边栏不能在当前页面计划名称变化后继续静默展示旧计划的期望数据。
- 如果用户没有粘贴/选择当前页面对应的复核数据，插件必须明确提示“期望数据与当前页面不匹配”，不能继续给出看似正常的对比结果。

### Review

- 根因：`sidepanel.js` 会从 `chrome.storage.local` 自动恢复上一次载入的 `reviewPayload`，但复核前没有校验该 payload 是否属于当前业务页面；用户切换计划后，旧客户消息复核数据仍会参与对比。
- 已修复：复核前读取当前页面计划名称，与复核数据中的计划名称比较；若不一致，立即显示红色“数据不匹配”，停止字段对比和视觉复核，提示从 `/simple` 对应行重新复制复核数据。
- 当前页面计划名读取增加兜底：优先用 DOM 字段 `name/计划名称`，读不到时从页面可见文本里的 `计划名称: ...` 或 `【...】` 提取。
- 已更新插件 README，明确侧边栏会记住上一次复核数据，切换计划时必须重新载入对应复核数据。
- 验证通过：`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。
- 用户复测后仍看到旧数据，确认原因是扩展重新加载不会自动清空 `chrome.storage.local`。已进一步修改：侧边栏启动时清除上一次复核数据，不再自动恢复；如果计划名不匹配，也会清空已载入数据，强制用户从 `/simple` 当前计划对应行重新复制。
- 用户复测遇到 `Extension context invalidated`，根因是业务页面里旧 content script 在扩展重新加载后仍收到 DOM 变化并调用 `chrome.runtime.sendMessage`。已修复：发送消息前检查扩展上下文；同步异常或 Promise reject 时断开 MutationObserver，避免旧脚本继续报错。
- 验证通过：`node --check browser_extension/review_assistant/content_script.js browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件支持直接粘贴强约束文本

- [x] 支持侧边栏粘贴 `/simple` 复核 JSON，保持现有能力
- [x] 支持侧边栏直接粘贴强约束计划文本，解析为 `expected_fields`
- [x] 覆盖多行字段、短信内容、发送内容、社群字段、图片数量等核心字段
- [x] 更新插件使用说明
- [x] 运行扩展 JS 语法检查

### 成功标准

- 业务可以不经过 `/simple` 结果页复制 JSON，直接把样本文本/原始计划文本粘贴到插件侧边栏复核。
- JSON 和文本两种输入都能载入，且计划名称校验仍生效。

### Review

- 已在 `sidepanel.js` 新增文本解析：支持 `字段: 值`、`字段：值`、`字段: |` 多行内容，字段映射对齐 `/simple` 复核字段。
- 支持字段包括：计划名称、发送渠道、营销主题、计划区域、计划时间、发送时间、主消费营运区、执行员工、目标商品编码、券规则 ID、员工任务结束时间、短信内容、发送内容、社群下发群名、分配方式、图片数量。
- JSON 输入继续保留；输入以 `{` 开头时按 `/simple` 复核 JSON 解析，否则按强约束计划文本解析。
- 计划名称一致性校验继续生效，避免文本/JSON 与当前业务页面不匹配时误复核。
- 已更新插件 README。
- 验证通过：`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件复核不应清空用户粘贴文本

- [x] 修复计划名不匹配时清空用户刚粘贴样本文本的问题
- [x] 保留“阻断旧数据误用”的提示，但不删除输入框内容
- [x] 运行扩展 JS 语法检查

### Review

- 根因：计划名不匹配分支复用了 `clearLoadedPayload()`，该函数固定清空 `payloadInput`，导致用户刚粘贴的样本文本丢失。
- 已修复：`clearLoadedPayload()` 增加 `clearInput` 选项；计划名不匹配时只清理内存态和缓存、不清空输入框；插件启动清理历史缓存时仍清空输入框。
- 验证通过：Node smoke 模拟侧边栏 DOM、Chrome storage 和业务页快照，覆盖强约束文本载入、计划名不匹配保留输入框、计划名匹配正常复核；同时通过 `node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件缺少 content script 接收方

- [x] 修复 `Could not establish connection. Receiving end does not exist.`
- [x] 侧边栏复核时若当前页未注入 content script，主动注入后重试
- [x] 更新 manifest 权限并运行扩展语法/JSON 检查

### Review

- 根因：侧边栏向当前 tab 调用 `chrome.tabs.sendMessage` 时，业务页面尚未加载或尚未注入 `content_script.js`，因此没有消息接收方。
- 已修复：新增 `readCurrentPage()`，首次发消息失败且错误为 `Receiving end does not exist / Could not establish connection` 时，使用 `chrome.scripting.executeScript` 主动注入 `content_script.js`，再重试读取页面。
- `manifest.json` 已增加 `scripting` 权限。
- 验证通过：manifest JSON 解析；`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件计划名称读取误抓页面导航文案

- [x] 修复当前页面计划名误读为 `单次/重复计划事件触发计划社群群发计划`
- [x] 收紧 content script 的 `计划名称` 字段读取范围，优先读取可编辑输入框/详情值，不从泛文本拼接结果误判
- [x] 保留计划名不匹配保护
- [x] 运行扩展语法检查

### Review

- 根因：计划名称原来复用泛用 `readByAliases(["计划名称", "营销计划"])`，会扫描页面所有 `span/div`，在业务页复杂 DOM 中把导航/计划类型文案拼接结果误当成计划名称。
- 已修复：新增 `readPlanName()`，只从明确的表单 label、对应 input/textarea/contenteditable 或详情值节点读取；最后兜底也只匹配 `计划名称:` 后面的单行文本。
- `readPage()` 中 `name/计划名称` 改为使用 `readPlanName()`，其他字段暂保持原有读取策略。
- 验证通过：`node --check browser_extension/review_assistant/content_script.js browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件复核字段规范化与分组展示

- [x] 修复发送渠道别名/页面文案导致的误判差异
- [x] 修复计划开始时间、计划结束时间、发送时间格式差异导致的误判差异
- [x] 对计划时间范围字段支持从同一页面值中拆分开始/结束时间
- [x] 结果区分“已复核字段”和“待打开页面/弹窗继续复核字段”
- [x] 运行扩展语法检查和 smoke

### 成功标准

- `会员通-发客户朋友圈` 与页面等价渠道文案应判定一致。
- `2026-06-01 00:00:00` 与 `2026-06-01 00 00 00` 应判定一致。
- 页面一次展示两个计划时间时，开始时间和结束时间都能从范围文本中匹配。
- 当前页面读不到的目标人群等字段不应和普通差异混在一起，应标记为待打开对应页面/弹窗继续复核。

### Review

- 已新增渠道归一：`客户朋友圈/朋友圈` 视为 `会员通-发客户朋友圈`，`客户消息/1对1/会员通群客户消息` 视为 `会员通-发客户消息`，`社群/群发` 视为 `会员通-发送社群`。
- 已新增时间归一：支持 `2026-06-02 12:00:00` 与 `2026-06-02 12 00 00` 等格式等价；计划开始/结束时间可从同一个时间范围文本中匹配。
- 结果展示已分组为“已复核字段”和“待打开页面/弹窗继续复核”，读不到的目标人群字段会提示打开第2步目标人群弹窗继续复核。
- 验证通过：Node smoke 覆盖朋友圈渠道别名、计划起止时间范围、发送时间格式、目标商品编码待弹窗复核分组；同时通过 `node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件渠道/员工/结束时间误判

- [x] 修复发送渠道读取范围过宽导致 `会员通发客户朋友圈` 仍误判的问题
- [x] 修复执行员工读取和多值匹配不稳定的问题
- [x] 修复员工任务结束时间误拿页面其他日期如 `2026-05-26 15:25:33` 的问题
- [x] 明确插件复核方式：读取当前页面 DOM 可见字段，不读业务接口源码
- [x] 运行扩展语法检查和 smoke

### Review

- 插件复核方式确认：当前版本读取业务页面 DOM 中的可见文本、input/textarea 值和标签值，不读取业务接口或网页源码。
- 发送渠道修复：新增按表格表头读取 `通知渠道/发送渠道/触达渠道` 的值，优先取截图中这类表格列下的 `会员通发客户朋友圈`，再走泛用字段读取。
- 执行员工修复：多值匹配改为包含式匹配，页面值 `广佛省区加盟` 可匹配原文 `广佛省区`，避免因默认包含加盟区域误判差异。
- 员工任务结束时间修复：content script 只读精确 `员工任务结束时间`，不再用泛化 `任务结束时间`；时间比较对 `step3_end_time` 不再从全页面文本里抓任意日期，避免把创建时间 `2026-05-26 15:25:33` 误当页面值。
- 验证通过：Node smoke 覆盖发送渠道 `会员通发客户朋友圈`、执行员工 `广佛省区加盟`、员工任务结束时间不误抓创建时间；同时通过 `node --check browser_extension/review_assistant/content_script.js browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-26 插件读取朋友圈模块结束时间

- [x] 支持从 `会员通-发客户朋友圈` 模块内的 `结束时间` 字段读取员工任务结束时间
- [x] 避免重新扩大到全页面任意 `结束时间/创建时间`
- [x] 运行扩展语法检查和 smoke

### Review

- 已新增模块内读取：先定位 `会员通-发客户朋友圈/客户消息` 相关模块标题，再只在该模块内读取精确标签 `结束时间`。
- 不再全页面泛化抓 `结束时间`，避免重新误拿创建时间或其他系统时间。
- 验证通过：content script DOM smoke 可从截图结构同类 DOM 读取 `2026-06-10`，且扩展 JS 语法检查通过。

## 2026-05-26 插件朋友圈结束时间真实 DOM 未命中

- [x] 改进 `会员通-发客户朋友圈` 模块内 `结束时间` 读取，不依赖固定 section 容器
- [x] 支持从标题后邻近可见文本/日期输入中提取结束时间
- [x] 避免误抓页面创建时间
- [x] 运行扩展语法检查和 smoke

### Review

- 上一版依赖标题和 `结束时间` 标签在同一个 section/card/form 容器内，真实页面 DOM 可能不是这种结构，导致未命中。
- 已增强为两段读取：先尝试容器内精确读取；失败后，从 `会员通-发客户朋友圈/客户消息` 标题后的邻近可见节点中寻找精确 `结束时间` 标签，并从后续几个节点提取日期。
- 日期提取仍限制在该模块标题后的邻近范围，不回到全页面扫描，避免误抓创建时间。
- 验证通过：DOM smoke 覆盖截图同类布局（标题、说明、企微标签、结束时间、日期输入为相邻节点），可读取 `2026-06-10`；扩展 JS 语法检查通过。

## 2026-05-26 插件视觉复核截图权限

- [x] 修复视觉复核 `Either the '<all_urls>' or 'activeTab' permission is required`
- [x] 明确截图权限只在用户手动点击视觉复核时使用
- [x] 运行 manifest 和扩展 JS 检查

### Review

- 根因：视觉复核使用 `chrome.tabs.captureVisibleTab` 截取当前页。侧边栏按钮触发时，Chrome 不一定保留 action 点击授予的临时 `activeTab` 权限，因此截图 API 报缺少 `<all_urls>` 或 `activeTab`。
- 已修复：`manifest.json` 的 `host_permissions` 增加 `<all_urls>`，用于允许截图当前可见页面；本地视觉接口仍只在用户手动点击“视觉复核待复核项”时调用。
- 已更新 README 说明截图权限用途。
- 验证通过：manifest JSON 解析；`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`。

## 2026-05-27 云端共享版视觉代理

- [x] 梳理现有 `/api/review/vision` 云端部署依赖和安全边界
- [x] 服务端增加共享 token 校验，避免任意人调用模型费用
- [x] 插件增加视觉服务地址和 token 配置
- [x] 支持本机模式和云端模式并存
- [x] 增加腾讯云/阿里云轻量服务器部署说明
- [x] 运行后端和扩展检查

### 成功标准

- 业务同事安装插件后，只需配置云端视觉服务地址和 token，即可复用同一个服务端模型 key。
- Ark/Doubao API Key 只存在云端服务环境变量，不进入插件代码、README 示例或浏览器存储明文以外的服务端配置。
- 未携带正确 token 的视觉请求会被拒绝，不产生模型费用。

### Review

- 现有服务端已经支持 `REVIEW_API_TOKEN` 校验，插件已经支持配置视觉服务地址和访问 token；本轮补齐云端健康检查 `GET /api/review/health`，便于部署后验证 Ark Key、模型和 token 状态。
- 已新增部署模板：
  - `deploy/review-proxy.service`
  - `deploy/nginx-review-proxy.conf`
- 已新增部署文档：`docs/cloud_review_proxy.md`，覆盖腾讯云/阿里云轻量服务器、`.env.cloud`、systemd、Nginx、HTTPS、插件配置、安全和常见问题。
- 云端服务使用 `ARK_API_KEY`、`ARK_VISION_MODEL`、`REVIEW_API_TOKEN` 环境变量；模型 key 不进入插件。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py`；manifest JSON 解析；`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`；直接调用 `_check_review_api_token` 验证空 token 拒绝、`X-Review-Token` 和 Bearer token 通过。

## 2026-05-27 插件稳定共享版

- [x] 服务端 `/api/review/vision` 支持访问 token 校验
- [x] 服务端支持浏览器扩展跨域调用
- [x] 插件支持配置视觉服务地址
- [x] 插件支持配置访问 token，请求视觉服务时发送 `X-Review-Token`
- [x] `.env.example` 增加共享部署配置
- [x] README 增加稳定共享版部署和同事安装说明
- [x] 运行服务端/扩展检查

### Review

- 服务端新增 `REVIEW_API_TOKEN`：设置后，`POST /api/review/vision` 必须携带 `X-Review-Token` 或 `Authorization: Bearer ...`；未设置时兼容本机开发。
- 服务端新增 CORS middleware，允许浏览器扩展从同事电脑调用统一视觉代理服务。
- 插件侧边栏新增“视觉服务地址”和“访问 Token”配置，保存在 Chrome 扩展本地存储；Ark Key 不进入插件。
- 插件视觉请求会把服务地址规范化：填写 `http://服务器IP:8790` 时自动请求 `/api/review/vision`；也兼容直接填写完整接口地址。
- `.env.example` 增加 `REVIEW_API_TOKEN=replace-with-a-random-shared-review-token`。
- README 已补充稳定共享版部署：管理员在内网/云服务器配置 `ARK_API_KEY` 和 `REVIEW_API_TOKEN`，用 `--host 0.0.0.0` 启动；业务同事只安装插件并填写服务地址/token。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py`；manifest JSON 解析；`node --check browser_extension/review_assistant/sidepanel.js browser_extension/review_assistant/content_script.js browser_extension/review_assistant/service_worker.js`；直接调用 `_check_review_api_token` smoke 覆盖缺 token、`X-Review-Token`、Bearer token。

## 2026-05-26 插件第2步字段误用第3步字段

- [x] 修复 `主消费营运区` 未打开第2步弹窗时误判一致的问题
- [x] 禁止第2步目标人群字段使用全页面文本兜底匹配
- [x] 修复执行员工读取别名过宽导致误判差异的问题
- [x] 运行扩展语法检查和 smoke

### Review

- 根因：`主消费营运区` 使用全页面文本兜底，执行员工区域出现 `广佛省区` 时会被误判为第2步字段一致。
- 已修复：第2步目标人群字段 `主消费营运区/目标商品编码/券规则ID` 不再使用页面全文兜底；没打开第2步弹窗或字段未展示时进入待复核。
- content script 中 `主消费营运区` 只认精确标签，不再用泛化 `营运区`；`执行员工` 只认精确标签，不再用泛化 `员工`。
- 验证通过：Node smoke 覆盖未打开第2步时 `主消费营运区` 待复核、执行员工 `广佛省区加盟` 匹配原文 `广佛省区`；扩展 JS 语法检查通过。

## 2026-06-08 QoderWork 智能电话第2步严格回归

- [x] 确认 QoderWork 环境下 cdp.dslyy.com 可达（DNS 解析到 10.0.100.221，TLS 握手成功）
- [x] 启动独立 Chrome `/tmp/pm-auto-chrome-proxy` + `--no-proxy-server` + CDP 18801
- [x] 确认 cdp.dslyy.com iframe 在浏览器中加载（title=智能营销平台）
- [x] 先跑短信渠道第2步回归验证基础链路
- [x] 跑智能电话渠道第2步严格回归
- [x] 修复智能电话渠道第2步商品编码校验逻辑
- [x] 复跑智能电话并验证成功

### Review

- QoderWork 环境下网络正常：`cdp.dslyy.com` 解析到 `10.0.100.221`（内网 IP），无需代理直连即可 TLS 握手。此前 Codex 环境受 VPN 假路由（198.18.0.253）阻塞的问题不存在。
- 短信渠道第2步回归：成功，32 ok / 1 warn / 0 fail，复核链接 `https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=629781039354535936`。iframe 加载正常，商品编码、券规则 ID、主消费营运区均通过。
- 智能电话渠道首次回归失败：iframe 加载正常（title=创建分群 - 智能营销平台），门店文件上传成功（已选中 4），但商品编码"选择数据"按钮未找到。
- 根因：智能电话渠道的 cdp.dslyy.com 分群页面结构与短信/客户消息不同，页面不含"商品编码"、"门店信息"、"券规则ID"、"主消费营运区"字段，仅有"会员消费次数"条件配置。
- 修复：在 `precision-auto-playwright-batch.py` 第2步严格校验前，先检测 iframe 页面是否实际包含商品编码/券规则字段；页面不含时降级为警告（跳过校验），不再作为失败条件。
- 修复后复跑：智能电话成功，31 ok / 3 warn / 0 fail，复核链接 `https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=629783944530825216`。3 个 warn 均为预期（智能电话分群页面不含的字段：主消费营运区、商品编码、门店信息已选）。
- 智能电话第3步特有字段验证通过：`活动介绍` ✅、`任务有效期` ✅。
- 验证通过：`python3 -m py_compile precision-auto-playwright-batch.py`；`python3 -m unittest tests.test_batch_script tests.test_simple_target_fields tests.test_text_plan_parser`（34 tests OK）。

---

## 2026-06-08 业务部署包（app/data 分离 + 自动更新）

- [x] 修改 server.py：UPLOAD_DIR/HISTORY_DIR 改为 PM_DATA_DIR 环境变量驱动，兼容新旧布局
- [x] 编写 Windows start.bat：自动更新 → Python检测 → 依赖安装 → CDP检查 → 启动UI
- [x] 编写 Windows auto_update.ps1：semver比较 → 下载zip → 解压 → 替换app/（data/永不触碰）
- [x] 编写 Mac start.command + auto_update.sh：等价实现
- [x] 重构 build_release.py：输出 app/data 分离的 zip 包，自动生成 latest.json
- [x] 编写 prepare_embedded_python.py：Windows 嵌入式 Python预装脚本（待Windows环境运行）
- [x] 编写 nginx-pm-auto.conf：腾讯云Nginx配置模板
- [x] 编写 index.html 引导页：版本检测 + 下载按钮 + 快速开始说明
- [x] 编写 INSTALL_GUIDE.md：业务用户安装指南
- [x] 创建 VERSION.txt：初始版本 1.0.0

### Review

- server.py 路径检测 4 项测试全部通过：自动检测兄弟data/、PM_DATA_DIR环境变量、旧布局回退、ui_uploads存在时保持ROOT
- 构建输出验证：Win/Mac zip 包结构正确，latest.json 格式正确，无警告
- Shell 脚本语法检查通过（auto_update.sh、start.command）
- server.py 语法检查通过（py_compile）
- 向后兼容：现有 .venv + 旧目录结构下 server.py 正常加载，32 条路由全部注册

### 待办（需腾讯云环境）

- [ ] 在腾讯云服务器上部署 Nginx + latest.json + release zip
- [ ] 在 Windows 机器上运行 prepare_embedded_python.py 构建自包含Python
- [ ] 端到端测试：首次安装 → 启动 → 自动更新 → 回退

---

## 2026-06-08 腾讯云部署（Caddy + 文件服务）

- [x] SSH 连接服务器 49.232.195.165（Ubuntu 24.04, Caddy 已安装）
- [x] 创建 /var/www/pm-auto 目录结构（releases/, extension/）
- [x] 上传 latest.json + index.html + Win/Mac zip 包
- [x] 配置 Caddy 文件服务（合并到 80 端口，保留已有 review-proxy）
- [x] 腾讯云安全组开放 80 端口入站
- [x] 外网验证：index.html (200), latest.json (200), zip 下载 (200)
- [x] 更新 auto_update.ps1/sh + build_release.py 使用 IP 地址

### Review

- 服务器运行 Caddy（非 Nginx），80 端口已有 review-proxy 服务
- 解决方案：将 pm-auto 路由合并到 `:80` 块，与 review API 共存
- 公网 DNS 存在劫持（nip.io 解析到 198.18.0.x），直接 IP 访问正常
- 密钥有 passphrase 保护，使用 expect + 密码方式 SSH
- 部署地址：`http://49.232.195.165`（后续可改域名）

### 待办

- [ ] 获取域名管理权后配置 pm-auto.dslyy.com + SSL
- [ ] 在 Windows 机器运行 prepare_embedded_python.py 构建自包含 Python
- [ ] 端到端测试：首次安装 → 启动 → 自动更新

## 2026-06-08 Codex 接手 qoder 部署迭代

- [x] 复核 `DEPLOY_STATUS.md` 与当前代码差异，确认已完成内容和真实阻塞点
- [x] 定位 `/simple` 执行时 CDP 连接超时的代码路径，判断是启动脚本、服务端入队还是 Playwright 连接策略问题
- [x] 做最小修复：增加 CDP 预检/失败快返或连接兜底，避免任务长时间 running 且业务无明确错误
- [x] 运行语法检查和相关单元测试
- [x] 如本机 CDP 环境可用，跑一次 `/simple` smoke；否则记录准确的人工验证步骤和剩余阻塞

### 成功标准

- 业务点击 `/simple` 执行后，如果 CDP 不可用，应在短时间内显示清晰错误，不再 3 次各卡 180 秒。
- 如果 CDP 可用，应至少完成一条样本的真实执行入口验证。
- 不改动 qoder 已经完成的 app/data 分离、发布包结构和云端静态分发逻辑，除非它们直接导致启动失败。

### Review

- 已确认 qoder 本轮主要完成：`PM_DATA_DIR` app/data 分离、Win/Mac 启动器与自动更新、发布包构建、腾讯云 Caddy 静态分发、智能电话第2步严格回归修复和部署状态文档。
- 当前真实阻塞点位于 `precision-auto-playwright-batch.py` 的 `connect_browser()`：此前即使 `/json/version` 可访问，`connect_over_cdp` 仍可能在 Playwright 初始化阶段等待 180 秒；脚本默认重试 3 次，导致 `/simple` 任务长时间 running。
- 已修复：CDP 接管前先请求 `/json/version` 并校验 `webSocketDebuggerUrl`；`connect_over_cdp` 默认超时降为 15000ms、默认重试 2 次，并新增 `--cdp-timeout-ms`、`--cdp-retries` 参数。
- 已修复：CDP 预检失败时输出短错误和启动示例，不再打印整段 Python traceback；这会让 `/simple` 结果里更快出现可读失败原因。
- 失败路径 smoke：连接不存在的 `http://127.0.0.1:18899` 在约 1.1 秒内失败，并输出明确 `CDP 预检失败`。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_text_plan_parser tests.test_simple_target_fields`（36 tests OK）。
- 后续已在“发布包 `/simple` 不拉起业务系统排查”中补做 v1.0.3 发布包和服务器上传；仍未做业务机真实 `/simple` 成功路径复测。

## 2026-06-08 发布包 `/simple` 不拉起业务系统排查

- [x] 确认用户从压缩包启动的是哪个目录/版本，读取本机运行日志和任务状态
- [x] 判断 `/simple` 点击执行后是否成功创建任务、是否进入 worker、是否调用批处理脚本
- [x] 判断 CDP 端口 `18800` 是否启动，以及 Chrome 是否可被 Playwright 接管
- [x] 修复导致“粘贴后无自动化动作/无清晰错误”的问题
- [x] 运行验证并给出用户可复测步骤

### 成功标准

- 用户在发布包 `/simple` 粘贴样本文本后，要么打开业务系统并执行自动化，要么 30 秒内在页面/日志显示可读的失败原因。

### Review

- 现场判断：当前本机 `127.0.0.1:8790` 和 `127.0.0.1:18800` 均未监听；旧 `v1.0.2` Mac 包内 `start.command` 只查找 `/Applications/Google Chrome.app`，不支持本机实际使用的 `Google Chrome Beta`，因此可能出现 UI 已打开但 CDP 浏览器未启动。
- 旧 `v1.0.2` 包内批处理脚本仍是 `connect_over_cdp(cdp_endpoint)` 默认 180 秒连接超时，没有 CDP 预检和短错误提示。
- 修复发布包：
  - `start.command` 同时支持 `Google Chrome.app` 与 `Google Chrome Beta.app`，使用独立 `data/chrome-cdp-profile`，并打开业务 dashboard 方便先登录；
  - `start.bat` 启动 Chrome 时补 `--no-first-run`、`--no-default-browser-check` 和业务 dashboard；
  - `auto_update.sh` 优先读取 `latest.json.url_mac`；
  - `auto_update.ps1` 优先读取 `latest.json.url_win`；
  - 批处理脚本保留 CDP 预检与 15 秒短超时。
- 已构建 `v1.0.3`：`release/PrecisionMarketingAuto-v1.0.3-win.zip`、`release/PrecisionMarketingAuto-v1.0.3-mac.zip`、`release/latest.json`。
- 已上传腾讯云 `/var/www/pm-auto/`，公网 `http://49.232.195.165/latest.json` 返回 `1.0.3`；服务器本机校验 mac zip HTTP 200。
- 验证通过：`bash -n scripts/deploy/start.command scripts/deploy/auto_update.sh`；`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_text_plan_parser tests.test_simple_target_fields`（36 tests OK）。
- 待用户复测：下载/自动更新到 `v1.0.3` 后，双击启动器应额外打开一个独立 Chrome/Chrome Beta 窗口到 `precision.dslyy.com`；业务需先在这个窗口登录，再回 `/simple` 执行。

## 2026-06-08 首页 Chrome 插件下载报错

- [x] 复现 `http://49.232.195.165` 首页插件下载链接
- [x] 确认服务器 `/extension/` 实际文件和首页链接是否一致
- [x] 修复插件下载入口，优先提供可直接下载的 zip 包
- [x] 验证公网链接返回 200

### 成功标准

- 用户点击首页 Chrome 插件下载后能拿到可解压安装的插件包，或页面明确提示当前插件尚未发布。

### Review

- 根因：首页 `scripts/deploy/index.html` 的插件按钮指向 `/extension/`，但服务器 `/var/www/pm-auto/extension/` 没有 index 或插件包，点击会报错。
- 已生成插件包 `release/extension/pm-review-assistant-v0.1.0.zip`，zip 根目录包含 `manifest.json`，业务解压后可直接在 Chrome “加载已解压的扩展程序”中选择该目录。
- 已更新首页按钮为 `/extension/pm-review-assistant-v0.1.0.zip`，并把快速开始说明改为“下载并解压插件，在 `chrome://extensions/` 开启开发者模式后加载已解压扩展”。
- 已上传服务器：`/var/www/pm-auto/extension/pm-review-assistant-v0.1.0.zip`。
- 验证通过：公网首页包含新链接；`curl -I http://49.232.195.165/extension/pm-review-assistant-v0.1.0.zip` 返回 HTTP 200、`Content-Type: application/zip`。

## 2026-06-08 `/simple` 支持多个文本计划输入框

- [x] 梳理 `/simple` 当前粘贴框、文件导入、图片上传和提交逻辑
- [x] 增加多个文本计划输入框能力，保持单计划图片按行对应
- [x] 保持原有 `.txt/.md` 导入和执行结果展示不退化
- [x] 运行语法检查/相关测试

### 成功标准

- 业务可在 `/simple` 页面新增多个计划输入框，每个输入框粘贴一条计划文本，点击执行后按多条计划提交。
- 原有单输入框粘贴、文本文件导入、每条计划对应图片上传仍可用。

### Review

- `/simple` 已新增“批量新增 N 个”控件，默认一次新增 5 个粘贴框，最多 100 个；原“新增粘贴框”仍保留。
- 每个计划输入框新增行号展示，删除行后自动重排行号；图片上传仍在对应行内按选择顺序绑定。
- 点击执行时只提交有文本的行，空白行显示“空白文本已忽略”，避免业务为了批量预留输入框而产生空文本失败。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_text_plan_parser tests.test_simple_target_fields`。
- 浏览器验证通过：`/simple` 默认 1 行，点击“批量新增”后为 6 行且行号为计划 1-6；只填写第 1 行时，空白行被忽略，未触发业务系统创建。

## 2026-06-08 Chrome 插件智能电话活动介绍复核

- [x] 定位插件读取“活动介绍/参数详情”的字段映射和 DOM 抽取逻辑
- [x] 支持直接粘贴样本文本里的“活动介绍”字段
- [x] 支持业务页面“参数名称=活动介绍 / 参数详情=输入值”的两列表格读取
- [x] 运行插件脚本语法检查和本地抽取逻辑 smoke

### 成功标准

- 智能电话详情页当前可见“参数详情”输入框时，插件能把它识别为“活动介绍”页面值。
- 业务直接粘贴强约束样本文本时，`活动介绍` 也进入待复核字段。

### Review

- 根因：插件原来没有把 `活动介绍` 放入侧边栏文本解析映射；页面读取也只按普通 label/表单结构找值，没有处理智能电话页面的“参数名称 / 参数详情”两列表格式。
- 已修复 `content_script.js`：新增 `readParameterDetailValue(["活动介绍"])`，优先读取“参数名称=活动介绍”同一行/相邻输入框中的“参数详情”值，并输出到 `activity_intro` 和 `活动介绍`。
- 已修复 `sidepanel.js`：直接粘贴强约束样本文本时，`活动介绍` 会进入 `expected_fields`。
- 已将 Chrome 插件版本升到 `0.1.1`，生成 `release/extension/pm-review-assistant-v0.1.1.zip`，并更新下载页链接。
- 已上传腾讯云，公网首页指向 `/extension/pm-review-assistant-v0.1.1.zip`；下载链接返回 HTTP 200、`Content-Type: application/zip`。
- 验证通过：`node --check browser_extension/review_assistant/content_script.js`；`node --check browser_extension/review_assistant/sidepanel.js`；公网 `curl` 验证。

## 2026-06-08 Chrome 插件渠道结束时间/图片/第2步复核

- [x] 定位员工任务结束时间、图片数量、主消费门店读取失败的插件路径
- [x] 修复渠道模块内“结束时间”读取，覆盖客户消息/朋友圈/社群当前页
- [x] 修复图片数量读取，支持发送内容下方上传文件名行
- [x] 评估第2步主消费门店弹窗/iframe 是否能自动读取，能低风险实现则补齐
- [x] 运行插件脚本语法检查，并更新插件包/公网下载

### 成功标准

- 当前页可见渠道模块“结束时间”时，`员工任务结束时间` 不再显示未读取到。
- 当前页可见上传图片文件名时，`图片数量` 能按文件名/图片项计数。
- 第2步目标人群如果在弹窗/iframe 中可见，插件尽量读取；不可见时明确提示需要打开弹窗，不误判。

### Review

- 根因 1：`员工任务结束时间` 实际是渠道模块内的 `* 结束时间`，原插件只识别客户消息/朋友圈标题，且 label 必须精确等于“结束时间”，漏了社群和必填星号。
- 根因 2：`图片数量` 原来只数上传区域里的 `<img>`，截图里的图片是文件名行 `(图片) 01__Q1_.png`，没有 `<img>` 时会读不到。
- 根因 3：第2步目标人群通常在 `cdp.dslyy.com` iframe/弹窗内，原侧边栏只读取主 frame；弹窗打开后也可能无法合并 iframe 字段。
- 已修复 `content_script.js`：渠道结束时间支持客户消息/朋友圈/社群标题，支持 `* 结束时间`；图片数量同时统计上传图片节点和图片文件名；主消费字段增加 `主消费门店` 别名。
- 已修复 `sidepanel.js`：复核时读取所有可访问 frame 并合并字段，弹窗/iframe 已打开时可自动读取；未打开时继续提示打开第2步目标人群弹窗。暂不让插件自动点击打开弹窗，避免主动改变业务页面状态。
- 已发布 Chrome 插件 `v0.1.2`，公网首页已指向 `/extension/pm-review-assistant-v0.1.2.zip`，zip 下载返回 HTTP 200。
- 验证通过：`node --check browser_extension/review_assistant/content_script.js`；`node --check browser_extension/review_assistant/sidepanel.js`；公网 `curl` 验证。

## 2026-06-08 Chrome 插件底部操作栏

- [x] 梳理侧边栏按钮和滚动布局
- [x] 将常用复核操作按钮固定到底部显示
- [x] 保持配置输入、结果列表滚动不被遮挡
- [x] 运行插件脚本/结构检查并重新打包发布

### 成功标准

- 业务在侧边栏滚动到字段结果底部时，也能直接点击载入、复核当前页、视觉复核等操作按钮。
- 底部操作栏不遮挡最后一条复核结果。

### Review

- 已将侧边栏操作按钮移动到底部固定栏：`载入`、`复核当前页`、`视觉复核待复核项`、`保存配置`。
- `body` 增加底部留白，避免底部操作栏遮挡最后一条复核结果。
- 已发布 Chrome 插件 `v0.1.3`，公网首页已指向 `/extension/pm-review-assistant-v0.1.3.zip`，zip 下载返回 HTTP 200。
- 验证通过：`node --check browser_extension/review_assistant/sidepanel.js`；`node --check browser_extension/review_assistant/content_script.js`；公网 `curl` 验证。

## 2026-06-08 固定样本时间和小程序字段补充

- [x] 梳理固定样本文档中的时间字段和渠道覆盖
- [x] 将样本时间统一调整为 10 月未来日期
- [x] 给会员通-发客户消息、会员通-发送社群样本补充小程序相关字段
- [x] 运行文本解析/样本解析检查

### 成功标准

- 固定样本不会因日期早于当前时间触发业务系统校验失败。
- 客户消息和社群样本能覆盖小程序字段解析与后续图片/封面上传逻辑。

### Review

- 已将 `docs/simple_text_samples.md` 里的业务样本时间统一调整到 2026 年 10 月；智能电话样本使用 2026-10-15 至 2026-10-22，其余样本使用 2026-10-01 至 2026-10-10。
- 已给 `会员通-发客户消息`、`短信 + 会员通-发客户消息`、`会员通-发送社群：按条件筛选客户群`、`会员通-发送社群：导入门店` 补充小程序字段：是否添加小程序、小程序名称、标题、链接。
- 已在维护规则中提醒：客户消息/社群样本包含小程序字段时，`/simple` 对应行至少上传 1 张图片，第 1 张作为小程序封面。
- 验证通过：`.venv/bin/python -m unittest tests.test_text_plan_parser tests.test_simple_target_fields`；解析 `docs/simple_text_samples.md` 中 7 个 `text` 样本全部成功，其中客户消息/组合/社群样本均识别 `mini=是`。

## 2026-06-08 `/simple` 图片多次追加上传

- [x] 梳理 `/simple` 每行图片上传和提交 FormData 逻辑
- [x] 支持同一计划行多次选择图片并累加，保持选择顺序
- [x] 增加清空本行图片能力，避免误选后只能刷新页面
- [x] 运行语法检查和页面静态验证

### 成功标准

- 业务可对会员通-发客户消息、会员通-发送社群、朋友圈等计划行分多次上传图片。
- 提交时按累计顺序上传图片；客户消息/社群有小程序字段时，第 1 张仍作为小程序封面，其余图片继续按顺序作为内容图片。

### Review

- `/simple` 每行新增前端图片累计状态 `rowImages`，多次选择图片会追加到同一计划行，不再被浏览器默认 FileList 替换。
- 提交时按累计数组顺序写入 `images_${idx}`；后端原有逻辑保持不变：小程序启用时第 1 张作为小程序封面，剩余图片作为内容图。
- 每行新增“清空本行图片”按钮，并在预览区显示已选择张数、前 12 张缩略图和文件名顺序。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser`；本机 `/simple` 页面已加载 `rowImages/appendRowImages/clearRowImages` 新代码。

## 2026-06-08 `/simple` 文本计划数量和粘贴拆分

- [x] 增加当前文本计划数量显示
- [x] 点击新增/批量新增/删除/文件导入后同步数量
- [x] 支持粘贴多个计划时按独立分隔行 `--` 自动拆分成多个输入框
- [x] 运行语法检查和相关测试

### 成功标准

- `/simple` 页面能实时显示当前共有几条文本计划输入框。
- 在任一输入框粘贴用 `--` 分隔的多个计划时，自动拆成多条计划行。

### Review

- `/simple` 工具栏新增 `X 个文本计划` 计数，新增、批量新增、删除、文本文件导入都会同步更新。
- 文本拆分规则从独立一行 `---` 扩展为独立一行 `--` 或更多横线；`.txt/.md` 导入和粘贴拆分共用同一规则。
- 任一计划输入框粘贴多段文本时，会拦截粘贴：当前框填第 1 条，其余自动追加为新计划行，并提示“已从粘贴内容拆分 X 条计划”。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser`；本机 `/simple` 页面已加载 `planCount/handlePlanTextPaste` 新代码。

## 2026-06-08 发布主程序 v1.0.4

- [x] 确认桌面启动自动更新链路：启动器读取云端 latest.json 并下载新包
- [x] 构建包含 `/simple` 最新改动的 Win/Mac v1.0.4 压缩包
- [x] 上传云端 latest.json 和 v1.0.4 压缩包
- [x] 验证公网 latest.json、Win/Mac zip 下载链接
- [x] 给出业务电脑更新方式说明

### 成功标准

- 云端 `latest.json` 指向 v1.0.4。
- 用户双击桌面启动器后，应能自动检查并更新到 v1.0.4；如果自动更新失败，也能从首页手动下载 v1.0.4。

### Review

- 已确认桌面启动自动更新链路：Mac `start.command` 和 Windows `start.bat` 都会先调用 `auto_update`，读取 `http://49.232.195.165/latest.json`；发现云端版本更高时只替换 `app/`，保留本机 `data/`。
- 已构建本地发布包：`release/PrecisionMarketingAuto-v1.0.4-win.zip`、`release/PrecisionMarketingAuto-v1.0.4-mac.zip`、`release/latest.json`。
- 已校验两端 zip 内 `app/VERSION.txt` 为 `1.0.4`，且包含 `/simple` 新代码：文本计划数量、`--` 粘贴拆分、图片多次追加上传。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（38 tests OK）。
- 已上传腾讯云：
  - `/var/www/pm-auto/latest.json`
  - `/var/www/pm-auto/releases/PrecisionMarketingAuto-v1.0.4-win.zip`
  - `/var/www/pm-auto/releases/PrecisionMarketingAuto-v1.0.4-mac.zip`
- 公网验证通过：`http://49.232.195.165/latest.json` 返回 `version=1.0.4`；Win/Mac zip 均返回 HTTP 200、`Content-Type: application/zip`。
- 业务电脑更新方式：双击桌面启动器即可自动检查云端版本并更新；如自动更新失败，可从 `http://49.232.195.165` 手动下载 v1.0.4 包。

## 2026-06-08 v1.0.3 旧包运行导致 `/simple` 生成任务失败

- [x] 确认当前 8790 服务实际运行目录和版本
- [x] 检查旧包 `data/ui_uploads` 是否缺失或被更新过程影响
- [x] 给出业务侧立即恢复方法
- [x] 判断是否需要调整启动器：即使旧 UI 正在运行，也要提示/执行更新

### 成功标准

- 明确为什么错误路径仍是 `PrecisionMarketingAuto-v1.0.3`。
- 业务能切换到 v1.0.4 或恢复旧包数据目录后重新提交。

### Review

- 根因：8790 仍有旧 Python 服务运行，cwd 为 `/Users/liminrong/.Trash/PrecisionMarketingAuto-v1.0.3/app`。旧包已被移到废纸篓/删除，运行中的旧服务仍尝试写旧数据目录，导致 `No such file or directory`。
- 这不是计划文本或字段填充问题，而是旧服务进程未停止、路径失效。
- 已停止旧进程，并用 macOS `open /Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.4/start.command` 按真实双击方式启动 v1.0.4。
- 已确认当前 8790 服务 cwd 为 `/Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.4/app`，`/simple` 页面包含 v1.0.4 新代码。
- 后续启动器需要优化：如果 8790 已运行但来自旧包/废纸篓，不能直接打开旧服务，应提示关闭旧服务或自动切换到当前包。

## 2026-06-08 `/simple` 草稿保存和批量下载文本

- [x] 增加 `/simple` 本地草稿保存/恢复
- [x] 增加清空草稿能力，避免误恢复旧内容
- [x] 支持批量下载当前计划文本，多个计划用独立一行 `--` 分隔
- [x] 运行语法检查和相关测试

### 成功标准

- 业务可以把当前多个计划输入框保存为草稿，刷新或重新打开 `/simple` 后可恢复。
- 业务可以一键下载当前所有非空计划文本为 `.txt`，文件内多个计划用 `--` 分隔。

### Review

- `/simple` 新增工具栏按钮：保存草稿、恢复草稿、下载文本、清空草稿。
- 草稿保存到浏览器 `localStorage`，只保存文本，不保存图片；恢复草稿后会提示重新选择对应图片。
- 下载文本会把当前所有非空计划文本写入一个 `.txt`，计划之间用独立一行 `--` 分隔。
- 已构建并发布主程序 `v1.0.5`；公网 `latest.json` 指向 v1.0.5，Win/Mac zip 均返回 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（39 tests OK）。

## 2026-06-09 v1.0.4 旧服务路径失效

- [x] 确认当前 8790 服务进程 cwd 和版本
- [x] 检查 `PrecisionMarketingAuto-v1.0.4/data/ui_uploads` 是否存在
- [x] 停止旧服务并启动最新包
- [x] 验证 `/simple` 当前服务来自最新版本

### 成功标准

- 不再写入已失效的 `PrecisionMarketingAuto-v1.0.4` 路径。
- `/simple` 当前运行版本包含 v1.0.5 功能。

### Review

- 根因复现：8790 旧进程 cwd 为 `/Users/liminrong/.Trash/PrecisionMarketingAuto-v1.0.4/app`，而 `/Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.4` 已不存在，导致旧服务继续写失效 data 路径时报 `No such file or directory`。
- 已停止旧进程 PID `16351`，并通过 `open /Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.5/start.command` 启动 v1.0.5。
- 当前 8790 进程 PID `23056`，cwd 已确认为 `/Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.5/app`。
- 当前 `/simple` 已确认包含 v1.0.5 功能：保存草稿、下载文本、文本计划计数、图片累计上传。
- 必须修启动器：端口已运行时不能直接打开页面；需要识别运行目录/版本，旧包或废纸篓进程应提示并切换。

## 2026-06-09 启动器防旧服务复发

- [x] 增加后端运行信息接口，返回版本、app 目录、data 目录和进程号
- [x] 修改 Mac 启动器：端口已开时校验运行目录/版本，发现旧包或废纸篓进程自动停止后继续启动当前包
- [x] 修改 Windows 启动器：端口已开时校验运行目录/版本，发现旧包或版本不一致自动 taskkill 后继续启动当前包
- [x] 增加聚焦测试或静态校验，避免后续发布包回退到只检查端口
- [x] 补充启动器自愈：新版 app 启动后同步外层 `start.bat/start.command`，后续自动更新也同步启动器
- [x] 构建并发布 v1.0.7，验证公网 latest.json 和 zip 下载

### 成功标准

- 端口 8790 已有旧服务时，启动器不能直接打开旧页面。
- 当前包版本和运行中服务版本/目录一致时，启动器才复用现有服务。
- 旧服务来自 `.Trash`、旧 `PrecisionMarketingAuto-v*` 目录或没有运行信息接口时，启动器应停止旧服务并启动当前包。

### Review

- 已新增 `/api/runtime`，返回 `version/pid/app_dir/data_dir`，用于启动器和后续远程排查确认当前实际运行的是哪个包。
- Mac `start.command` 已调整为先自动更新，再校验 8790 现有服务；只有版本和 app 目录都匹配当前包时才复用，否则停止旧进程并启动当前包。
- Windows `start.bat` 已增加同等校验：通过 `/api/runtime` 精准识别当前服务，旧版本/旧目录/无 runtime 接口时停止 8790 监听进程再继续。
- 已补充启动器自愈：发布包会把 `start.bat/start.command` 放入 `app/scripts/deploy/`；新版 app 启动时会同步外层启动器；新版自动更新脚本以后也会同步外层启动器。
- 已构建并发布 `v1.0.7`：公网 `latest.json` 返回 `version=1.0.7`，Win/Mac zip 均 HTTP 200。
- 本机已停止旧 `v1.0.5` 服务并按真实双击方式启动包，自动更新到 `v1.0.7`；当前 `/api/runtime` 返回 `app_dir=/Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.5/app`、`data_dir=/Users/liminrong/Downloads/PrecisionMarketingAuto-v1.0.5/data`、`version=1.0.7`。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`bash -n scripts/deploy/start.command scripts/deploy/auto_update.sh`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（42 tests OK）。

## 2026-06-09 会员通图片素材格式非法

- [x] 定位 `/simple` 图片保存与第3步上传链路，确认是否只按扩展名校验
- [x] 增加上传图片规范化：业务上传 png/jpg 后本地转为业务系统更稳的 RGB JPEG
- [x] 保留原始上传顺序和小程序封面/内容图片分配规则
- [x] 增加测试覆盖：PNG 输入会保存为可上传 JPEG，非图片仍然拦截
- [x] 运行相关测试，必要时发布新版本

### 成功标准

- 业务上传 `01_dashenlin-reference.png` 这类 PNG 时，不再直接把原 PNG 送到业务素材接口。
- `/simple` 仍按图片选择顺序匹配每条计划；客户消息/社群有小程序字段时第 1 张仍作为封面，其余作为内容图。
- 非真实 jpg/png 图片不能仅凭扩展名通过。

### Review

- 根因判断：此前 `/simple` 保存图片主要按扩展名和粗略文件头校验，PNG 会以原文件进入第3步素材上传；业务接口 `content-rights-setting/batch-create/v2` 对部分 PNG 变体返回 `图片格式非法`。
- 已新增上传图片规范化：所有 UI 上传的 jpg/png 在保存到 `ui_uploads` 前都会用 Pillow 解码并转成 RGB JPEG；透明 PNG 会铺白底，输出 `.jpg`，再进入原有自动化上传链路。
- 小程序封面和内容图片共用同一规范化逻辑；原有顺序规则不变：客户消息/社群有小程序字段时第 1 张为封面，其余为内容图。
- 已新增依赖 `Pillow>=10.4.0`，并修复启动器依赖标记为按 app 版本生成，确保业务电脑升级到新版本时会重新安装新增依赖。
- 已构建并发布 `v1.0.8`：公网 `latest.json` 返回 `version=1.0.8`，Win/Mac zip 均 HTTP 200。
- 本机已按真实启动器升级到 `v1.0.8`，`/api/runtime` 确认当前运行版本为 `1.0.8`。
- 本机运行包 smoke：`01_dashenlin-reference.png` 保存为 `01_01_dashenlin-reference.jpg`，文件头 `ffd8`，Pillow 版本 `12.2.0`。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`bash -n scripts/deploy/start.command scripts/deploy/auto_update.sh`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（45 tests OK）。

## 2026-06-09 业务界面显示当前版本

- [x] 在 `/simple` 简洁页显示当前运行版本
- [x] 在 `/` 任务中心显示当前运行版本
- [x] 版本号从 `/api/runtime` 读取，避免前端写死
- [x] 增加静态测试覆盖版本显示入口
- [x] 运行测试，必要时发布新版本

### 成功标准

- 业务人员打开页面即可看到 `v1.x.x`。
- 截图反馈问题时能快速判断是否已升级到云端最新版。

### Review

- `/simple` 和 `/` 任务中心均已显示当前运行版本胶囊。
- 版本号通过 `/api/runtime` 异步读取，不依赖前端写死文本；悬停可看到运行目录，便于定位旧包/旧服务问题。
- 已发布 `v1.0.9` 并验证公网 latest/zip；随后本机已升级到 `v1.0.9` 并确认页面包含版本显示代码。

## 2026-06-09 `/simple` 失败重试与草稿语义优化

- [x] 失败行支持单独点击重试
- [x] 支持批量重新执行失败行
- [x] 页面显示本轮执行汇总：成功 x 个、失败 x 个、执行中 x 个
- [x] 移除“恢复草稿”按钮
- [x] 保存草稿同时保存文本和图片，并在下次进入 `/simple` 自动恢复
- [x] 清空草稿时同时清空页面输入框、图片和持久化草稿
- [x] 增加测试覆盖关键 UI/JS 入口
- [x] 运行测试，必要时发布新版本

### 成功标准

- 失败任务不需要业务重新粘贴整批内容，可以单条或批量重试。
- 保存草稿后刷新或下次进入页面，文本和已选图片都能恢复。
- 清空草稿后页面立即变空，下次进入也不再恢复旧内容。

### Review

- `/simple` 新增执行汇总：成功、失败、执行中数量会随每行状态实时更新。
- 每行失败后会启用“重试”按钮；工具栏新增“批量重试失败”，只重新提交失败行，不影响已成功行。
- 已移除“恢复草稿”按钮；页面进入时自动恢复上次保存的草稿。
- 草稿从仅保存文本升级为 IndexedDB 保存文本和图片 File/Blob；保存后下次进入页面自动恢复文本与图片顺序。
- “清空草稿”会同时删除 IndexedDB/localStorage 草稿、清空当前文本框和图片，并停止当前页面跟踪的任务轮询。
- 已构建并发布 `v1.0.10`：公网 `latest.json` 返回 `version=1.0.10`，Win/Mac zip 均 HTTP 200。
- 本机已按真实启动器升级到 `v1.0.10`；`/api/runtime` 返回当前运行版本 `1.0.10`。
- 本机 `/simple` 页面验证：`restoreDraft=False`，`executionSummary/retryAllFailedRows/retryFailedRow/pm_simple_draft_db_v1/autoRestoreDraft/runtimeVersion=True`。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`bash -n scripts/deploy/start.command scripts/deploy/auto_update.sh`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（47 tests OK）。

## 2026-06-09 `/simple` Vercel 风格界面优化

- [x] 只调整 `/simple` 页面，不影响 `/` 任务中心
- [x] 改造成克制的控制台风格：黑白灰、细边框、清晰状态和主操作
- [x] 保留现有功能入口：版本、保存草稿、清空草稿、下载文本、批量重试失败、开始执行
- [x] 优化执行汇总和行状态的可读性
- [x] 增加静态测试覆盖关键样式和功能入口
- [x] 运行测试，必要时发布新版本

### 成功标准

- `/simple` 看起来像批量创建工作台，不像普通表单堆叠。
- 所有已有业务功能入口仍可见、名称不混乱。
- 不改任务中心、不改自动化执行字段逻辑。

### Review

- 只调整了 `/simple` 页面视觉结构；`/` 任务中心和自动化执行字段逻辑未改。
- `/simple` 改为 Vercel 式克制控制台风格：sticky 顶栏、黑白灰主色、细边框、独立页面标题区、主操作按钮右置。
- 执行汇总改为独立状态条；成功/失败/执行中仍按现有行状态实时统计。
- 保留所有业务入口：版本号、文本上传、新增/批量新增、保存草稿、下载文本、清空草稿、批量重试失败、开始执行、单行重试。
- 已新增静态测试覆盖控制台结构和关键样式。
- 已构建并发布 `v1.0.11`：公网 `latest.json` 返回 `version=1.0.11`，Win/Mac zip 均 HTTP 200。
- 本机已按真实启动器升级到 `v1.0.11`；`/api/runtime` 返回当前运行版本 `1.0.11`。
- 本机 `/simple` 页面验证：`Batch Creation Console/page-head/summary-strip/--bg:#fafafa/position:sticky;top:0/批量创建营销计划/retryAllFailedRows/pm_simple_draft_db_v1` 均存在。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（48 tests OK）。

## 2026-06-09 回退 `/simple` Vercel 风格

- [x] 仅回退 `/simple` 视觉改版，不回退功能
- [x] 保留版本号、失败重试、执行汇总、图片草稿能力
- [x] 移除 Vercel 风格页面标题区和黑白灰控制台样式
- [x] 恢复 `开始执行` 到工具栏内的朴素业务页布局
- [x] 更新测试断言，避免继续要求 Vercel 风格结构
- [x] 运行测试并发布回退版本

### 成功标准

- `/simple` 不再显示 `Batch Creation Console` 和额外大标题区。
- 页面功能仍包含：版本号、保存草稿、清空草稿、下载文本、批量重试失败、开始执行、失败行重试、执行汇总。

### Review

- 已仅回退 `/simple` 的 Vercel 风格视觉改版：移除 `Batch Creation Console`、额外大标题区、sticky/黑白灰控制台样式。
- 已恢复 `开始执行` 到工具栏内，恢复朴素业务页布局。
- 功能未回退：版本号、保存草稿、清空草稿、下载文本、批量重试失败、失败行重试、执行汇总、图片草稿仍保留。
- 已更新测试：不再要求 Vercel 风格结构，并确认关键功能入口仍存在。
- 已构建并发布 `v1.0.12`：公网 `latest.json` 返回 `version=1.0.12`，Win/Mac zip 均 HTTP 200。
- 本机已按真实启动器升级到 `v1.0.12`；`/api/runtime` 返回当前运行版本 `1.0.12`。
- 本机 `/simple` 页面验证：`Batch Creation Console=False`，`page-head=False`，`bg_old/submit_in_toolbar/retry/draft_db/runtimeVersion=True`。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_text_plan_parser tests.test_batch_script`（48 tests OK）。

## 2026-06-09 插件精简与业务下载入口

- [ ] Chrome 插件移除访问 Token 配置
- [ ] Chrome 插件主操作只保留“文本复核”和“截图复核”两个按钮
- [ ] 后端复核视觉接口不再要求 Review Token
- [ ] `/simple` 增加“下载模版”按钮，下载强约束文本样本
- [ ] `/simple` 增加“字段清单”按钮，下载已支持自动化字段清单
- [ ] 更新插件 README/云端说明，避免继续要求业务填写 token
- [ ] 增加测试覆盖关键入口
- [ ] 运行测试并发布新版本

### 成功标准

- 业务安装插件后无需配置 token；扫码登录内部系统后即可使用插件。
- 插件侧边栏只暴露两个核心动作：文本复核、截图复核。
- `/simple` 可下载文本模版和字段清单，便于业务自助参考。

## 2026-06-10 Windows 同事双击后提示无访问权限

- [x] 确认 `/simple` 是否存在访问权限/Token 拦截
- [x] 检查 Windows 启动器默认打开 URL 和版本包状态
- [x] 判断是否为旧版本包、错误页面、业务系统登录态或本机服务问题
- [x] 给出业务侧可执行的排查步骤；若代码问题再做最小修复

### 成功标准

- 能明确说明“无访问权限”的最可能来源。
- 业务同事按步骤能验证当前版本、访问地址和日志位置。
- 若定位为代码/打包问题，需要给出修复和验证结果。

### Review

- 当前 `v1.0.20` 本地 `/simple` 路由无 Token/权限校验，`/api/review/*` 也已取消 token 必填，代码层面不会主动返回“无访问权限”页面。
- 当前 Windows 包 `PrecisionMarketingAuto-v1.0.20-win.zip` 内根目录 `start.bat` 默认工具页是 `http://127.0.0.1:8790/simple`。
- 启动器会先为自动化打开 Chrome CDP 到业务系统 `https://precision.dslyy.com/admin#/dashboard`，然后再打开本地工具页；若业务账号/角色无权限，业务系统页可能显示“无访问权限”，但这不等于本地 `/simple` 不可用。
- 另一个高概率原因是旧包/旧服务占用端口；需让业务同事确认浏览器地址栏、页面版本号、解压目录版本，并提供 `data\logs\ui_server.log`。

## 2026-06-10 Windows 双击 start.bat 一闪而过

- [x] 增加 Windows 启动器外层守护，失败时不关闭窗口
- [x] 将启动全过程写入 `data\logs\launcher.log`
- [x] 增加缺少 `app/` 目录的明确提示，覆盖未解压/目录不完整场景
- [x] 增加静态测试覆盖启动器守护逻辑
- [x] 运行相关测试

### 成功标准

- 业务同事双击失败时能看到错误，不再一闪而过。
- 即使窗口截图不清楚，也能从 `data\logs\launcher.log` 追溯启动失败原因。
- 不改变 `/simple` 和自动化字段填充逻辑。

### Review

- 已在 `scripts/deploy/start.bat` 增加外层守护：首次双击进入外层，真正启动逻辑由内层执行；失败时会打印 `data\logs\launcher.log` 并 `pause`，避免窗口一闪而过。
- 启动全过程写入 `data\logs\launcher.log`；服务进程日志仍写入 `data\logs\ui_server.log`。
- 增加缺少 `app\ui_app\server.py` 的明确错误提示，覆盖未完整解压、目录结构损坏、在错误目录运行 `start.bat` 的情况。
- 已新增静态测试 `test_windows_launcher_keeps_failure_visible_and_logs_outer_startup`。
- 已构建并发布 `v1.0.21` 到腾讯云；公网 `latest.json` 返回 `1.0.21`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields`（28 tests OK）。

## 2026-06-10 Windows 启动器第3步 bat 括号解析错误

- [x] 修复 `start.bat` 第3步依赖提示中的未转义括号
- [x] 增加测试覆盖 Windows 启动器括号代码块内的危险 echo
- [x] 构建并发布新版本
- [x] 验证云端 `latest.json` 和 Windows 包可下载

### 成功标准

- 日志不再在 `[3/6] Checking dependencies ...` 后出现 `was unexpected at this time`。
- 业务端可通过旧目录双击触发自动更新，也可重新下载最新包。
- 启动器失败守护和日志能力保留。

### Review

- 根因：`start.bat` 在 `if not exist "%DEPS_MARKER%" (` 代码块内执行 `echo Installing dependencies (first run, this may take a minute) ...`，未转义的 `)` 被 Windows 批处理解析为代码块结束，导致 `... was unexpected at this time.`。
- 已将提示改为 `Installing dependencies - first run may take a minute ...`，避免括号解析问题。
- 已新增测试 `test_windows_launcher_avoids_unescaped_parentheses_in_echo_blocks`，同时保留 `launcher.log` 守护测试。
- 已构建并发布 `v1.0.22` 到腾讯云；公网 `latest.json` 返回 `1.0.22`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields`（29 tests OK）。

## 2026-06-10 Windows 自动更新覆盖运行中的 start.bat

- [x] 修改 Windows 自动更新：不再直接覆盖正在执行的根目录 `start.bat`
- [x] 写入待更新启动器文件，避免批处理执行到一半被替换
- [x] 启动器在安全时机检测并应用待更新启动器
- [x] 增加测试覆盖：禁止 `auto_update.ps1` 直接 `Copy-Item` 到根目录 `start.bat`
- [x] 构建并发布新版本

### 成功标准

- 自动更新不会在当前 `start.bat` 运行中覆盖自身。
- 后续版本升级不会再出现空指令/批处理执行错乱。
- 保留失败日志和一键启动能力。

### Review

- 判断根因：旧启动器在自动更新或服务启动自愈时直接覆盖正在执行的根目录 `start.bat`，Windows 批处理可能边执行边被替换，导致空指令/跳行/异常状态。
- `auto_update.ps1` 已改为写入 `start.bat.pending`，不再直接覆盖根目录 `start.bat`。
- `ui_app/server.py` 的 `_refresh_parent_launchers()` 对 Windows 也改为写入 `start.bat.pending`，避免服务启动时覆盖当前启动器。
- `start.bat` 外层新增 pending 应用逻辑：发现 `start.bat.pending` 时生成 `data\logs\apply_launcher_update.bat`，退出当前脚本，由 helper 复制新启动器并重新启动。
- 已更新测试：确认启动器包含 pending/helper 逻辑，确认 `auto_update.ps1` 禁止直接复制到根目录 `start.bat`。
- 已构建并发布 `v1.0.23` 到腾讯云；公网 `latest.json` 返回 `1.0.23`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields`（29 tests OK）。

## 2026-06-10 Windows 离线 wheelhouse 缺少 colorama

- [x] 补齐 Windows 离线依赖 `colorama`
- [x] bump runtime version，强制重建 Windows wheelhouse
- [x] 增加测试覆盖发布脚本显式包含 `colorama`
- [x] 构建并发布新版本
- [x] 验证发布包内包含 `colorama` wheel，公网可下载

### 成功标准

- 业务端第3步依赖安装不再报 `No matching distribution found for colorama`。
- Windows 包在无外网依赖下载情况下可完成依赖安装。

### Review

- 根因：Windows 离线 wheelhouse 缺少 `colorama`；`click` 在 Windows 下通过环境标记依赖 `colorama`，但 Mac 构建环境未自动纳入该条件依赖。
- 已在 `scripts/deploy/build_release.py` 显式加入 `"colorama"`，并将 `RUNTIME_VERSION` 从 `wheelhouse-v1` bump 到 `wheelhouse-v2`，强制重建 Windows runtime cache。
- 已新增测试 `test_windows_release_wheelhouse_includes_colorama`。
- 已构建并发布 `v1.0.24` 到腾讯云；包内确认包含 `runtime/wheelhouse/colorama-0.4.6-py2.py3-none-any.whl`，`runtime/RUNTIME_VERSION.txt` 为 `win-python-3.11.9-wheelhouse-v2`。
- 公网 `latest.json` 返回 `1.0.24`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py scripts/deploy/build_release.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields`（30 tests OK）。

## 2026-06-11 执行员工肇云营运区未选择

- [x] 补充执行员工级联路径：`肇云营运区`
- [x] 补充加盟路径：`肇云营运区加盟`
- [x] 收紧执行员工宽松放行逻辑，避免默认值残留被当成成功
- [x] 增加静态测试覆盖路径和放行条件
- [x] 运行相关测试

### 成功标准

- `执行员工: 肇云营运区` 能按路径定位到 `华南大区 > 广佛省区 > 肇云营运区`。
- 若没有命中目标文本，不再仅因字段已有默认值就放行。

### Review

- 根因：第3步执行员工路径表已有 `肇庆营运区`、`云浮营运区`，但没有业务系统真实节点 `肇云营运区`；同时原宽松兜底会在“执行员工字段已有默认值且无报错”时放行，导致默认门店标签残留也可能被视为成功。
- 已补充普通级联路径：`肇云营运区 -> 华南大区 / 广佛省区 / 肇云营运区`，以及 `肇云营运区加盟 -> 华南大区加盟 / 广佛省区加盟 / 肇云营运区加盟`。
- 已同步补充“按条件筛选客户”员工弹窗路径：`肇云`、`肇云营运区`、`肇云加盟`、`肇云营运区加盟`。
- 已收紧执行员工兜底：只有回读文本包含目标全称或目标核心词时才放行，不再因任意默认值存在就放行。
- 已新增测试覆盖路径和放行文案。
- 已构建并发布 `v1.0.25` 到腾讯云；公网 `latest.json` 返回 `1.0.25`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_simple_target_fields`（45 tests OK）。

## 2026-06-11 朋友圈肇云样本 exit_code=1

- [x] 本地解析用户粘贴文本，确认字段是否正确进入 CSV
- [x] 排查 `exit_code=1` 的可能失败点，优先定位任务日志中的真实错误
- [x] 如为可预防输入问题，补充前置校验/提示；如为自动化字段问题，最小修复
- [x] 运行相关测试

### 成功标准

- 能说明该样本失败的真实原因，不停留在 `exit_code=1`。
- 后续业务粘贴同类内容时，要么能创建，要么在执行前给出清晰错误说明。

### Review

- 本地解析用户粘贴文本通过：`创建链接`、`计划区域`、`营销主题`、`主消费营运区`、`执行员工`、`员工任务结束时间`、`发送内容` 均能进入内部字段；`员工任务结束时间` 对应内部字段为 `step3_end_time`。
- 本机历史日志显示同类“肇云朋友圈”失败曾出现两类真实原因：`第1步失败：营销主题未选择成功`，以及第2步 `主消费营运区` 回读未通过。用户本次只给出 `exit_code=1`，无法 100% 确认具体失败点，需要该任务日志最后 30 行。
- 已修复 UI 错误展示：子进程失败时优先提取日志中最后一条 `错误: ...` 写入 `task.error`，不再只显示 `exit_code=1`。
- 已新增测试 `test_error_summary_prefers_runtime_error_line`。
- 已构建并发布 `v1.0.26` 到腾讯云；公网 `latest.json` 返回 `1.0.26`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_batch_script tests.test_text_plan_parser`（57 tests OK）。

## 2026-06-11 /simple 失败行复制日志

- [x] 在 /simple 每行结果操作区增加“复制日志”按钮
- [x] 任务创建后保存 task_id，并在任务完成/失败后允许复制日志尾部
- [x] 复制日志时调用 `/api/tasks/{task_id}/logs`，把可诊断日志复制到剪贴板
- [x] 增加静态测试覆盖按钮和函数入口
- [x] 运行测试并发布

### 成功标准

- 业务看到 `exit_code=1` 或其他失败时，可以一键复制真实任务日志给维护人员。
- 不需要进入任务中心或查找安装目录文件。

### Review

- `/simple` 每行结果操作区已新增“复制日志”按钮。
- 任务提交后保存 `task_id`，日志按钮启用；点击后调用 `/api/tasks/{task_id}/logs?offset=0&limit=5000`，复制最后 220 行日志。
- 失败行仍显示 `error_summary`；新版本会优先显示日志中的 `错误: ...`，不再只显示 `exit_code=1`。
- 已新增静态测试覆盖按钮、函数和日志 API 路径。
- 已构建并发布 `v1.0.27` 到腾讯云；公网 `latest.json` 返回 `1.0.27`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile ui_app/server.py ui_app/text_plan_parser.py precision-auto-playwright-batch.py`；`.venv/bin/python -m unittest tests.test_simple_target_fields tests.test_batch_script tests.test_text_plan_parser`（57 tests OK）。

## 2026-06-11 Chrome 149 CDP setDownloadBehavior 不兼容

- [x] 定位 CDP 接管失败路径，确认是否可自动降级到本地 Chromium
- [x] 增加 CDP 连接失败后的 fallback 逻辑，避免任务直接失败
- [x] 增加测试覆盖错误信息/降级入口
- [x] 运行相关测试并构建发布包
- [ ] 上传云端并验证公网下载

### 成功标准

- Chrome CDP 报 `Browser.setDownloadBehavior` 不兼容时，不再直接让任务失败。
- 任务能自动切换到 Playwright 自带 Chromium 或给出明确可执行提示。

### Review

- 根因：业务同事机器上的 Chrome 149 虽然 `/json/version` 预检通过，但 Playwright `connect_over_cdp` 初始化时调用 `Browser.setDownloadBehavior`，该浏览器返回 `Browser context management is not supported`，导致自动化还没进入业务页面就失败。
- 已修复：遇到该特定 CDP 兼容错误时，脚本会自动改用 Playwright 内置 Chromium，并提示业务在新浏览器扫码登录；后续登录和填充逻辑按实际浏览器模式执行，不再误用 CDP 登录态。
- 已新增测试覆盖该错误识别。
- 已构建本地 `v1.0.28` 发布包：`release/PrecisionMarketingAuto-v1.0.28-win.zip`、`release/PrecisionMarketingAuto-v1.0.28-mac.zip`、`release/latest.json`。
- 云端上传被当前 Codex 环境审批/额度拦截，尚未完成公网发布。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_simple_target_fields tests.test_text_plan_parser`（58 tests OK）。

## 2026-06-11 CDP 降级持久登录态

- [x] 将 CDP 不兼容降级改为固定用户目录的备用浏览器
- [x] 确保降级后后续填充逻辑按实际浏览器模式运行
- [x] 增加测试覆盖备用 profile 路径/提示
- [x] 自测语法和相关单测
- [x] 构建并发布新版安装包

### 成功标准

- Chrome CDP 不兼容时，业务首次扫码后，下次备用浏览器可复用登录态。
- 降级不会影响字段填充主流程，也不会每次都要求重新扫码。

### Review

- 已将 CDP 兼容错误兜底从“临时内置 Chromium”升级为“固定 profile 备用浏览器”，profile 目录为 `data/playwright-profile`，自动更新 `app/` 时不会清掉登录态。
- 降级后仍按非 CDP 模式执行登录检查和字段填充；持久 context 不会在每条计划结束后被关闭。
- 已新增测试覆盖持久 profile、`launch_persistent_context` 和适配层。
- 已完成持久 context smoke：普通沙盒因 macOS 权限拒绝，授权环境下启动/打开 `about:blank`/关闭通过。
- 已构建并发布 `v1.0.29` 到腾讯云；公网 `latest.json` 返回 `1.0.29`，Win/Mac zip 均 HTTP 200。
- 验证通过：`.venv/bin/python -m py_compile precision-auto-playwright-batch.py ui_app/server.py ui_app/text_plan_parser.py`；`.venv/bin/python -m unittest tests.test_batch_script tests.test_simple_target_fields tests.test_text_plan_parser`（59 tests OK）。
