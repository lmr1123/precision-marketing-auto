#!/usr/bin/env python3
"""
精准营销平台自动化 - Playwright 并发批量版

支持：
1. 第1步：12个基础字段填充
2. 第2步：目标分群弹窗操作
3. 第3步：触达内容 + 保存
4. CSV 批量处理
5. 并发执行（可配置并发数）
6. 飞书进度通知

使用方式：
    # 单条测试
    python3 precision-auto-playwright-batch.py --test
    
    # CSV 批量处理（3并发）
    python3 precision-auto-playwright-batch.py --csv memory/plans.csv
    
    # 指定并发数
    python3 precision-auto-playwright-batch.py --csv memory/plans.csv --concurrent 5
    
    # 指定处理范围
    python3 precision-auto-playwright-batch.py --csv memory/plans.csv --start 1 --end 10
"""

import asyncio
import sys
import csv
import argparse
import subprocess
import re
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Windows 控制台默认 gbk，遇到 emoji 日志会抛 UnicodeEncodeError。
def _enable_utf8_stdio():
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_enable_utf8_stdio()

# ============ 配置 ============

BASE_URL = "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=594094287227023360"
CHANNEL_CREATE_URLS = {
    "会员通-发客户消息": "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=594094287227023360",
    "会员通-发送社群": "https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=add",
    "会员通-发客户朋友圈": "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=599702926159527936",
    "短信": "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=599702746907561984",
    "会员通-发短信": "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=599702746907561984",
}
CHANNEL_COMBO_CREATE_URLS = {
    frozenset(["短信", "会员通-发客户消息"]): "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=600035736992907264",
}

# 默认测试数据
DEFAULT_PLAN = {
    "name": "测试-广佛省区-3月会员活动",
    "region": "省区",
    "theme": "其他",
    "scene_type": "",
    "plan_type": "",
    "use_recommend": "否",
    "start_time": "2026-03-16 08:00",
    "end_time": "2026-03-27 08:00",
    "trigger_type": "定时-单次任务",
    "send_time": "2026-03-20 08:00",
    "global_limit": "不限制",
    "set_target": "否",
    "group_name": "测试-≥20积分会员（未绑客）",
    "update_type": "自动更新",
    "main_operating_area": "广佛省区",
    "main_store_file_path": "",
    "step2_store_file_path": "",
    "step2_product_file_path": "",
    "coupon_ids": "1-20000005475",
    "sms_content": "短信内容测试",
    "step3_end_time": "2026-03-27 08:00",
    "executor_employees": "西北大区、湖北省区",
    "distribution_mode": "指定门店分配",
    "group_send_name": "福利",
    "executor_include_franchise": "否",
    "send_content": "企微1对1内容测试",
    "channels": "",
    "create_url": "",
    "moments_add_images": "否",
    "moments_image_paths": "",
    "upload_stores": "否",
    "store_file_path": "",
    "msg_add_mini_program": "否",
    "msg_mini_program_name": "大参林健康",
    "msg_mini_program_title": "",
    "msg_mini_program_cover_path": "",
    "msg_mini_program_page_path": "",
}

HEADLESS = False
SLOW_MO = 100
MAX_RETRIES = 2
MAX_CONCURRENT = 3
FEISHU_USER_ID = "ou_ed20f9990c63fa5448a0f2cd613ecf30"
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"
DEBUG_DROPDOWN_OPTIONS = os.getenv("PM_DEBUG_DROPDOWN_OPTIONS", "0").strip() in ("1", "true", "yes", "on")
MOMENTS_UPLOAD_MODE = os.getenv("PM_MOMENTS_UPLOAD_MODE", "batch_then_slow").strip().lower()
MOMENTS_UPLOAD_DELAY_SECONDS = float(os.getenv("PM_MOMENTS_UPLOAD_DELAY", "1.4") or 1.4)
MOMENTS_UPLOAD_WAIT_SECONDS = float(os.getenv("PM_MOMENTS_UPLOAD_WAIT", "8") or 8)

# ============ 工具函数 ============

def load_plans_from_csv(csv_path: str, start: int = None, end: int = None) -> list:
    """从 CSV 加载计划数据"""
    def _parse_dt(raw: str, *, end_of_day_for_date_only: bool = False) -> datetime:
        text = (raw or "").strip().replace("T", " ").replace("/", "-")
        if not text:
            raise ValueError("为空")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                if fmt == "%Y-%m-%d":
                    if end_of_day_for_date_only:
                        dt = dt.replace(hour=23, minute=0, second=0)
                    else:
                        dt = dt.replace(hour=0, minute=0, second=0)
                return dt
            except Exception:
                pass
        raise ValueError(f"不支持的时间格式: {raw}")

    plans = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            # 容错读取：兼容中文表头、带空格/括号/下划线差异。
            normalized_row = {}
            for rk, rv in (row or {}).items():
                key_raw = str(rk or "")
                key_norm = re.sub(r"[\s_()（）]+", "", key_raw).strip().lower()
                normalized_row[key_norm] = rv

            def _gv(*keys: str) -> str:
                for k in keys:
                    if k in row:
                        v = str(row.get(k, "") or "").strip()
                        if v:
                            return v
                for k in keys:
                    key_norm = re.sub(r"[\s_()（）]+", "", str(k or "")).strip().lower()
                    v = str(normalized_row.get(key_norm, "") or "").strip()
                    if v:
                        return v
                return ""

            if start and i < start:
                continue
            if end and i > end:
                break
            plan = {
                "name": _gv("name", "计划名称"),
                "region": _gv("region", "计划区域"),
                "theme": _gv("theme", "营销主题"),
                "scene_type": _gv("scene_type", "场景类型"),
                "plan_type": _gv("plan_type", "计划类型"),
                "use_recommend": _gv("use_recommend", "推荐算法"),
                "push_content": _gv("push_content", "推送内容"),
                "start_time": _gv("start_time", "计划开始时间"),
                "end_time": _gv("end_time", "计划结束时间"),
                "trigger_type": _gv("trigger_type", "触发方式"),
                "send_time": _gv("send_time", "发送时间"),
                "global_limit": _gv("global_limit", "全局触达限制"),
                "set_target": _gv("set_target", "是否设置目标"),
                "group_name": _gv("group_name", "分群名称"),
                "update_type": _gv("update_type", "更新方式"),
                "main_operating_area": _gv("main_operating_area", "主消费营运区", "主消费运营区"),
                "main_store_file_path": _gv("main_store_file_path", "主消费门店文件路径"),
                "step2_store_file_path": _gv("step2_store_file_path", "第2步门店信息文件路径"),
                "step2_product_file_path": _gv("step2_product_file_path", "第2步商品编码文件路径"),
                "purchase_target_product_code": _gv("purchase_target_product_code", "购买目标商品编码"),
                "coupon_ids": _gv("coupon_ids", "券规则ID"),
                "coupon_ids_sheet_ref": _gv("coupon_ids_sheet_ref", "已领或已使用券规则ID"),
                "sms_content": _gv("sms_content", "短信内容"),
                "step3_end_time": _gv("step3_end_time", "员工任务结束时间", "第3步结束时间"),
                "executor_employees": _gv("executor_employees", "执行员工"),
                "distribution_mode": _gv("distribution_mode", "社群任务分配方式", "分配方式"),
                "group_send_name": _gv("group_send_name", "delivery_group_name", "下发群名"),
                "executor_include_franchise": _gv("executor_include_franchise", "执行员工包含加盟区域"),
                "send_content": _gv("send_content", "发送内容"),
                "channels": _gv("channels", "发送渠道"),
                "create_url": _gv("create_url", "创建链接"),
                "moments_add_images": _gv("moments_add_images", "朋友圈是否上传图片"),
                "moments_image_paths": _gv("moments_image_paths", "朋友圈图片路径", "朋友圈图片路径(用|分隔)"),
                "upload_stores": _gv("upload_stores", "是否上传门店"),
                "store_file_path": _gv("store_file_path", "门店文件路径"),
                "msg_add_mini_program": _gv("msg_add_mini_program", "会员通消息是否添加小程序"),
                "msg_mini_program_name": _gv("msg_mini_program_name", "1对1-小程序名称"),
                "msg_mini_program_title": _gv("msg_mini_program_title", "1对1-小程序标题"),
                "msg_mini_program_cover_path": _gv("msg_mini_program_cover_path", "小程序封面路径"),
                "msg_mini_program_page_path": _gv("msg_mini_program_page_path", "1对1-小程序链接"),
            }
            # 统一模板：推送内容按渠道路由到短信/发送内容。
            push_content = plan.get("push_content", "")
            if push_content:
                channels_raw = str(plan.get("channels", "") or "")
                if ("短信" in channels_raw) and (not plan.get("sms_content", "")):
                    plan["sms_content"] = push_content
                if any(k in channels_raw for k in ("会员通-发客户消息", "会员通-发客户朋友圈", "会员通-发送社群")) and (not plan.get("send_content", "")):
                    plan["send_content"] = push_content
                if (not plan.get("sms_content", "")) and (not plan.get("send_content", "")):
                    # 未指定渠道时兜底：两个都写，交给后续渠道判定使用。
                    plan["sms_content"] = push_content
                    plan["send_content"] = push_content

            # 前置业务校验（避免跑到页面保存阶段才失败）
            try:
                st = _parse_dt(plan.get("start_time", ""))
                et = _parse_dt(plan.get("end_time", ""), end_of_day_for_date_only=True)
                if et < st:
                    raise ValueError(f"第{i}行：计划结束时间早于开始时间")
                if (et - st).total_seconds() > 14 * 24 * 3600:
                    raise ValueError(f"第{i}行：计划时间起止不能超过14天")
            except Exception as e:
                if isinstance(e, ValueError) and str(e).startswith(f"第{i}行："):
                    raise
                raise ValueError(f"第{i}行：计划时间格式错误（start_time/end_time）: {e}")

            try:
                send_dt = _parse_dt(plan.get("send_time", ""))
                now_dt = datetime.now()
                if send_dt < now_dt:
                    raise ValueError(
                        f"第{i}行：发送时间不能小于当前时间（send_time={send_dt.strftime('%Y-%m-%d %H:%M:%S')}，"
                        f"now={now_dt.strftime('%Y-%m-%d %H:%M:%S')}）"
                    )
            except Exception as e:
                if isinstance(e, ValueError) and str(e).startswith(f"第{i}行："):
                    raise
                raise ValueError(f"第{i}行：发送时间格式错误（send_time）: {e}")

            plans.append(plan)
    return plans

async def send_notification(title: str, message: str):
    """发送飞书通知"""
    try:
        cmd = [
            "openclaw", "message",
            "--action", "send",
            "--channel", "feishu",
            "--target", f"user:{FEISHU_USER_ID}",
            "--message", f"**{title}**\n\n{message}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"   ✅ 通知已发送")
            return True
    except Exception as e:
        print(f"   ⚠️ 通知发送失败: {e}")
        return False

async def wait_and_log(page, seconds: float, msg: str = ""):
    """等待并打印日志"""
    if msg:
        print(f"   ⏳ {msg}")
    await asyncio.sleep(seconds)

async def click_by_label(page, label_text: str, timeout: int = 5000):
    """通过 label 文本点击元素"""
    try:
        await page.click(f'text={label_text}', timeout=timeout)
        return True
    except:
        return False

async def get_form_item_by_label(page, label: str):
    """按 label 匹配表单项，兼容 Element/Ant。"""
    form_items = page.locator('.el-form-item, .ant-form-item')
    count = await form_items.count()
    visible_fuzzy_hit = None
    for i in range(count):
        item = form_items.nth(i)
        label_el = item.locator('.el-form-item__label, .ant-form-item-label label').first
        try:
            visible = await item.evaluate("""(el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            }""")
            if not visible:
                continue
            text = (await label_el.text_content() or "").strip().replace("：", "").replace(":", "")
            if text == label:
                return item
            if label in text:
                visible_fuzzy_hit = item
        except:
            continue
    return visible_fuzzy_hit

async def fill_with_retry(input_locator, value: str):
    """统一输入策略：先 fill，失败后 click+快捷键清空再 type。"""
    try:
        await input_locator.fill(value)
    except:
        await input_locator.click(force=True)
        await input_locator.press("ControlOrMeta+A")
        await input_locator.press("Backspace")
        await input_locator.type(value, delay=30)
    try:
        await input_locator.blur()
    except:
        pass

def escape_js_string(value: str) -> str:
    """转义注入到 JS 字符串中的特殊字符，避免脚本断裂。"""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )

async def select_option(page, label: str, value: str, is_multi: bool = False):
    """选择下拉选项（Element UI / Ant Design）"""
    print(f"   🏷️  {label}: {value}")

    targets = [value]
    if is_multi:
        targets = [x.strip() for x in re.split(r"[、，,|;\\n]+", str(value or "")) if x.strip()]
        if not targets:
            targets = [str(value or "").strip()]
    # 去重保序，避免同一项重复点击触发“选中/取消”来回反选
    targets = list(dict.fromkeys([t for t in targets if str(t).strip()]))
    label_name = label.strip()
    strict_label = (label_name == "营销主题")
    strict_exact = strict_label or (label_name in {"场景类型", "计划类型", "计划区域"})

    async def clear_multi_selected_tags(item_locator):
        """清空多选标签（仅用于营销主题），避免历史默认值/脏值导致越选越多。"""
        try:
            cleared = await item_locator.evaluate("""(root) => {
                const closes = Array.from(root.querySelectorAll('.el-tag__close, .ant-select-selection-item-remove'));
                let n = 0;
                closes.forEach(btn => {
                    try {
                        btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        btn.click();
                        n++;
                    } catch (e) {}
                });
                return n;
            }""")
            return int(cleared or 0)
        except Exception:
            return 0

    async def clear_tags_except_targets(item_locator, keep_targets: List[str]) -> int:
        """直接在标签区删除非目标项（不依赖下拉是否可展开）。"""
        try:
            removed = await item_locator.evaluate(
                """(root, payload) => {
                    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                    const keep = new Set((payload.keep || []).map(norm));
                    let n = 0;
                    const tags = Array.from(root.querySelectorAll('.el-tag, .ant-select-selection-item'));
                    tags.forEach(tag => {
                        const txtNode = tag.querySelector('.el-select__tags-text, .el-tag__content, .ant-select-selection-item-content') || tag;
                        const txt = norm(txtNode.textContent || '');
                        if (!txt || /^\\+\\s*\\d+$/.test(txt)) return;
                        if (keep.has(txt)) return;
                        const closeBtn = tag.querySelector('.el-tag__close, .ant-select-selection-item-remove');
                        if (!closeBtn) return;
                        try {
                            closeBtn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            closeBtn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            closeBtn.click();
                            n++;
                        } catch (e) {}
                    });
                    return n;
                }""",
                {"keep": keep_targets},
            )
            return int(removed or 0)
        except Exception:
            return 0

    async def clear_multi_via_clear_icon(item_locator):
        """优先点击清空图标（若组件支持 clearable，通常可一次清空全部）。"""
        try:
            clicked = await item_locator.evaluate("""(root) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                // 某些页面需 hover 后才显示 clear 图标
                try {
                    root.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
                } catch (e) {}
                const cands = Array.from(root.querySelectorAll(
                    '.el-icon-circle-close, .el-input__icon.el-icon-circle-close, .ant-select-clear, .ant-select-clear *'
                )).filter(isVisible);
                const btn = cands[0];
                if (!btn) return false;
                btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                return true;
            }""")
            return bool(clicked)
        except Exception:
            return False

    async def clear_multi_by_dropdown_selection(item_locator) -> int:
        """通过下拉面板逐个反选已勾选项，确保真正清空（兼容 +N 汇总标签场景）。"""
        cleared = 0
        for _ in range(6):
            try:
                await click_field(item_locator)
            except Exception:
                break
            try:
                res = await page.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const dd = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                    if (!dd || !isVisible(dd)) return { clicked: false, remaining: 0 };
                    const selected = Array.from(dd.querySelectorAll('.el-select-dropdown__item.selected, .ant-select-item-option-selected'))
                        .filter(isVisible);
                    if (!selected.length) return { clicked: false, remaining: 0 };
                    // 逐个点第一个已选项即可（点击后会取消选择）
                    const el = selected[0];
                    el.scrollIntoView({ block: 'center' });
                    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    el.click();
                    return { clicked: true, remaining: selected.length - 1 };
                }""")
                if res and res.get("clicked"):
                    cleared += 1
                    await asyncio.sleep(0.1)
                    continue
            except Exception:
                break
            break
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return cleared

    async def read_selected_options_from_dropdown(item_locator) -> List[str]:
        """重新展开下拉后读取“当前勾选项”，用于营销主题强校验。"""
        try:
            await click_field(item_locator)
        except Exception:
            return []
        try:
            vals = await page.evaluate("""() => {
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const dd = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                if (!dd) return [];
                const out = [];
                // Element UI 多选：item.selected
                dd.querySelectorAll('.el-select-dropdown__item.selected').forEach(el => {
                    const t = norm(el.textContent);
                    if (t) out.push(t);
                });
                // AntD 多选：option-selected
                dd.querySelectorAll('.ant-select-item-option-selected').forEach(el => {
                    const t = norm(el.textContent);
                    if (t) out.push(t);
                });
                return Array.from(new Set(out));
            }""")
            # 收起下拉，避免影响后续字段
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return vals or []
        except Exception:
            return []

    async def unselect_extra_options(item_locator, keep_targets: List[str]) -> int:
        """仅取消当前已选中的“非目标项”，避免全清空后重选引发误触发。"""
        try:
            await click_field(item_locator)
        except Exception:
            return 0
        try:
            removed = await page.evaluate(
                """(payload) => {
                    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                    const keep = new Set((payload.keep || []).map(norm));
                    const dd = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                    if (!dd) return 0;
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const selected = Array.from(dd.querySelectorAll('.el-select-dropdown__item.selected, .ant-select-item-option-selected'))
                        .filter(isVisible);
                    let n = 0;
                    selected.forEach(el => {
                        const txt = norm(el.textContent);
                        if (keep.has(txt)) return;
                        try {
                            el.scrollIntoView({ block: 'center' });
                            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            el.click();
                            n++;
                        } catch (e) {}
                    });
                    return n;
                }""",
                {"keep": keep_targets},
            )
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return int(removed or 0)
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return 0

    async def click_field(item_locator):
        # 先尝试收起旧下拉，避免串到上一个字段面板
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.05)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.05)
        except Exception:
            pass

        field = item_locator.locator(
            '.el-select .el-input__inner, .ant-select-selector, .ant-select-selection-item, .el-input__inner, .el-select .el-input'
        ).first
        await field.click(force=True)
        try:
            await page.locator('.el-select-dropdown:visible, .ant-select-dropdown:visible').first.wait_for(timeout=1200)
            return
        except Exception:
            pass
        # 兜底：点箭头再拉起一次下拉
        arrow = item_locator.locator(
            '.el-input__suffix, .el-select__caret, .ant-select-arrow, .el-icon-arrow-up, .el-icon-arrow-down'
        ).first
        if await arrow.count() > 0:
            await arrow.click(force=True)
        try:
            await page.locator('.el-select-dropdown:visible, .ant-select-dropdown:visible').first.wait_for(timeout=900)
            return
        except Exception:
            pass

        # 兜底：直接在容器内触发 mousedown/click，避免“点击输入框无效”
        try:
            await item_locator.evaluate(
                """(root) => {
                    const target = root.querySelector('.el-select, .ant-select, .el-input__inner, .ant-select-selector');
                    if (!target) return false;
                    target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                    target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                    target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                    return true;
                }"""
            )
        except Exception:
            pass
        await page.locator('.el-select-dropdown:visible, .ant-select-dropdown:visible').first.wait_for(timeout=1200)

    async def read_selected_text(item_locator) -> str:
        try:
            txt = await item_locator.evaluate(
                """(root) => {
                    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                    const parts = [];
                    const seen = new Set();
                    const pushUnique = (v) => {
                        const t = norm(v);
                        if (!t) return;
                        // 忽略纯“+N”汇总标签，避免把摘要当作真实已选值
                        if (/^\\+\\s*\\d+$/.test(t)) return;
                        if (seen.has(t)) return;
                        seen.add(t);
                        parts.push(t);
                    };
                    const selectors = [
                        '.el-select__tags-text',
                        '.el-tag',
                        '.el-select__selected-item',
                        '.el-select__input',
                        '.el-input__inner',
                        '.ant-select-selection-item',
                        '.ant-select-selection-overflow-item',
                        '.ant-select-selection-search-input'
                    ];
                    selectors.forEach(sel => {
                        root.querySelectorAll(sel).forEach(el => {
                            pushUnique(el.value || el.textContent);
                        });
                    });
                    return norm(parts.join(' '));
                }"""
            )
            return (txt or "").strip()
        except Exception:
            return ""

    async def pick_one(target: str, item_locator=None) -> bool:
        async def attempt_pick_from_open_dropdown() -> bool:
            if not strict_label:
                option = page.locator(
                    '.el-select-dropdown:visible .el-select-dropdown__item, '
                    '.ant-select-dropdown:visible .ant-select-item-option, '
                    '.ant-select-dropdown:visible .ant-select-item'
                ).filter(has_text=target).first
                try:
                    if await option.count() > 0:
                        await option.click(force=True)
                        await asyncio.sleep(0.2)
                        return True
                except Exception:
                    pass

            # 兜底：在当前可见下拉中用 JS 按文本精准点击（兼容首项/滚动项）
            try:
                js_res = await page.evaluate(
                    """({target, strict}) => {
                        const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                        const t = norm(target);
                        const dropdown = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                        if (!dropdown) return { ok: false, reason: 'dropdown_not_found', options: [] };
                        const candidates = Array.from(dropdown.querySelectorAll('.el-select-dropdown__item, .ant-select-item-option, .ant-select-item'));
                        const options = candidates.map(el => norm(el.textContent)).filter(Boolean);
                    const hit = candidates.find(el => {
                        const txt = norm(el.textContent);
                        if (strict) return txt === t;
                        return txt === t || txt.includes(t) || t.includes(txt);
                    });
                        if (!hit) return { ok: false, reason: 'option_not_found', options: options.slice(0, 20) };
                        hit.scrollIntoView({ block: 'center' });
                        hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        hit.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        hit.click();
                        return { ok: true, reason: 'clicked', options: options.slice(0, 20) };
                    }""",
                {"target": target, "strict": strict_exact},
            )
                if js_res and js_res.get("ok"):
                    await asyncio.sleep(0.2)
                    return True
                if DEBUG_DROPDOWN_OPTIONS and js_res and js_res.get("options"):
                    print(f"      🧪 {label}下拉可见项: {js_res.get('options')}")
            except Exception:
                pass

            # 兜底2：滚动下拉列表查找目标项（双向：先向上再向下，避免只向下漏选）
            try:
                js_scroll_res = await page.evaluate(
                    """({target, strict}) => {
                        const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                        const t = norm(target);
                        const dropdown = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                        if (!dropdown) return { ok: false, reason: 'dropdown_not_found' };
                        const wrap = dropdown.querySelector('.el-scrollbar__wrap, .rc-virtual-list-holder, .ant-select-dropdown .rc-virtual-list-holder, .ant-select-dropdown .rc-virtual-list-holder-inner') || dropdown;

                        const findAndClick = () => {
                            const nodes = Array.from(dropdown.querySelectorAll('.el-select-dropdown__item, .ant-select-item-option, .ant-select-item'));
                            const hit = nodes.find(el => {
                                const txt = norm(el.textContent);
                                if (strict) return txt === t;
                                return txt === t || txt.includes(t) || t.includes(txt);
                            });
                            if (!hit) return false;
                            hit.scrollIntoView({ block: 'center' });
                            hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            hit.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            hit.click();
                            return true;
                        };

                        if (findAndClick()) return { ok: true, reason: 'found_without_scroll' };

                        const canScroll = (typeof wrap.scrollTop === 'number');
                        if (!canScroll) return { ok: false, reason: 'option_not_found_after_scroll' };

                        const maxTop = Math.max(0, (wrap.scrollHeight || 0) - (wrap.clientHeight || 0));
                        const step = 120;

                        // 1) 先回到顶部再向下搜，覆盖“当前滚动位置在中下部导致漏掉上方项”
                        wrap.scrollTop = 0;
                        if (findAndClick()) return { ok: true, reason: 'found_from_top' };
                        let lastTop = -1;
                        for (let i = 0; i < 80; i++) {
                            const nextTop = Math.min(maxTop, (wrap.scrollTop || 0) + step);
                            wrap.scrollTop = nextTop;
                            if (wrap.scrollTop === lastTop) break;
                            lastTop = wrap.scrollTop;
                            if (findAndClick()) return { ok: true, reason: 'found_after_scroll_down' };
                        }

                        // 2) 再从底部向上搜，覆盖虚拟列表渲染异常/反向懒加载
                        wrap.scrollTop = maxTop;
                        if (findAndClick()) return { ok: true, reason: 'found_from_bottom' };
                        lastTop = -1;
                        for (let i = 0; i < 80; i++) {
                            const nextTop = Math.max(0, (wrap.scrollTop || 0) - step);
                            wrap.scrollTop = nextTop;
                            if (wrap.scrollTop === lastTop) break;
                            lastTop = wrap.scrollTop;
                            if (findAndClick()) return { ok: true, reason: 'found_after_scroll_up' };
                        }
                        return { ok: false, reason: 'option_not_found_after_scroll' };
                    }""",
                    {"target": target, "strict": strict_exact},
                )
                if js_scroll_res and js_scroll_res.get("ok"):
                    await asyncio.sleep(0.2)
                    return True
            except Exception:
                pass
            return False

        async def attempt_pick_by_bound_dropdown() -> bool:
            if item_locator is None:
                return False
            try:
                js_res = await item_locator.evaluate(
                    """(root, payload) => {
                        const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                        const target = norm(payload.target);
                        const strict = !!payload.strict;
                        const input = root.querySelector('input[aria-owns], input[aria-controls], .el-input__inner, .ant-select-selection-search-input');
                        let dropdown = null;
                        const getById = (id) => {
                            if (!id) return null;
                            return document.getElementById(id) || document.querySelector(`#${CSS.escape(id)}`);
                        };
                        if (input) {
                            const own = input.getAttribute('aria-owns') || input.getAttribute('aria-controls') || '';
                            dropdown = getById(own);
                        }
                        if (!dropdown) {
                            dropdown = document.querySelector('.el-select-dropdown:not([style*="display: none"]), .ant-select-dropdown:not([style*="display: none"])');
                        }
                        if (!dropdown) return { ok: false, reason: 'dropdown_not_found' };
                        const options = Array.from(dropdown.querySelectorAll('.el-select-dropdown__item, .ant-select-item-option, .ant-select-item'));
                        const hit = options.find(el => {
                            const txt = norm(el.textContent);
                            if (strict) return txt === target;
                            return txt === target || txt.includes(target) || target.includes(txt);
                        });
                        if (!hit) return { ok: false, reason: 'option_not_found' };
                        hit.scrollIntoView({ block: 'center' });
                        hit.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                        hit.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                        hit.click();
                        return { ok: true, reason: 'clicked' };
                    }""",
                    {"target": target, "strict": strict_exact},
                )
                if js_res and js_res.get("ok"):
                    await asyncio.sleep(0.15)
                    return True
            except Exception:
                pass
            return False

        # 第1轮
        if item_locator is not None:
            try:
                await click_field(item_locator)
            except Exception:
                pass
        if await attempt_pick_by_bound_dropdown():
            return True
        if await attempt_pick_from_open_dropdown():
            return True

        # 第2轮：重开下拉再试一次，解决“下拉已收起/未真正展开”的偶发问题
        if item_locator is not None:
            try:
                await click_field(item_locator)
                if await attempt_pick_by_bound_dropdown():
                    return True
                if await attempt_pick_from_open_dropdown():
                    return True
            except Exception:
                pass
        return False

    item = await get_form_item_by_label(page, label)
    if item:
        # 已是目标值时快速放行（尤其是“计划区域”在模板里常有默认值，避免无意义重试导致长停顿）
        if (not is_multi) and targets:
            try:
                selected_text = await read_selected_text(item)
                target0 = (targets[0] or "").strip()
                if selected_text and target0 and (selected_text == target0 or target0 in selected_text):
                    print(f"      ✅ 已选择: {target0}")
                    print(f"      🧪 当前已选: {selected_text}")
                    return True
            except Exception:
                pass

        if is_multi and strict_label:
            # 仅取消非目标项，避免“全清空→重选”导致反复反选
            removed_by_tag = await clear_tags_except_targets(item, targets)
            selected_opts = await read_selected_options_from_dropdown(item)
            extras = [x for x in selected_opts if x not in targets]
            cleared_n = 0
            if extras:
                cleared_n = await unselect_extra_options(item, targets)
            total_cleared = (removed_by_tag or 0) + (cleared_n or 0)
            if total_cleared > 0:
                await asyncio.sleep(0.15)
                print(f"      🧪 已清理非目标主题: {total_cleared}项")
        ok_count = 0
        selected_text = await read_selected_text(item)
        for t in targets:
            # 已选则跳过，避免重复点击导致反选
            if is_multi and selected_text and (t in selected_text):
                print(f"      ✅ 已存在: {t}")
                ok_count += 1
                continue
            picked = False
            matched = False
            retry_rounds = 1 if (is_multi and strict_label) else 3
            for _ in range(retry_rounds):
                picked = await pick_one(t, item)
                selected_text = await read_selected_text(item)
                # 多选营销主题：点击命中即视为该项成功，避免重复点击触发反选
                if is_multi and strict_label and picked:
                    matched = True
                    break
                if picked and (t in selected_text):
                    matched = True
                    break
                await asyncio.sleep(0.15)
            # 单选/普通多选必须回读命中，防止“点击到了但值未变”的假成功
            if (not is_multi and not matched):
                selected_text = await read_selected_text(item)
                if t in selected_text:
                    matched = True
            if matched:
                ok_count += 1
                print(f"      ✅ 已选择: {t}")
            else:
                print(f"      ⚠️ 未找到选项: {t}")

        # 营销主题强校验：读取下拉内“已勾选项”验证目标是否都命中（避免 +N 摘要误导）
        if is_multi and strict_label:
            selected_opts = await read_selected_options_from_dropdown(item)
            missing = [t for t in targets if t not in selected_opts]
            if missing:
                # 再做一轮“只清非目标+补选缺失”兜底，避免重复反选
                _ = await unselect_extra_options(item, targets)
                await asyncio.sleep(0.1)
                for t in targets:
                    if t not in selected_opts:
                        _ = await pick_one(t, item)
                    await asyncio.sleep(0.08)
                selected_opts = await read_selected_options_from_dropdown(item)
                missing = [t for t in targets if t not in selected_opts]
            if missing:
                print(f"      ⚠️ 营销主题回读缺失: {missing}")
                selected_text = await read_selected_text(item)
                if selected_text:
                    print(f"      🧪 当前已选: {selected_text}")
                return False
            if selected_opts:
                print(f"      🧪 当前已选: {'、'.join(selected_opts)}")
                return ok_count == len(targets)
        selected_text = await read_selected_text(item)
        if selected_text:
            print(f"      🧪 当前已选: {selected_text}")
        return ok_count == len(targets)

    # 标签块没命中时，仍尝试直接在当前下拉上选（用于兜底）
    ok_count = 0
    for t in targets:
        picked = await pick_one(t, None)
        if picked:
            ok_count += 1
            print(f"      ✅ 已选择: {t}")
        else:
            print(f"      ⚠️ 未找到字段: {label} / 选项: {t}")
    return ok_count == len(targets)

async def fill_input(page, label: str, value: str):
    """填充文本输入框"""
    print(f"   📝 {label}: {value}")

    # 优先 placeholder 定位，抗样式改动
    placeholder_candidates = [
        f"请输入{label}",
        label,
        f"选择{label}",
    ]
    for placeholder in placeholder_candidates:
        try:
            input_el = page.get_by_placeholder(placeholder).first
            if await input_el.count() > 0:
                await fill_with_retry(input_el, value)
                print("      ✅ 已填充")
                return
        except:
            continue

    item = await get_form_item_by_label(page, label)
    if item:
        try:
            input_el = item.locator('input[type="text"], input:not([type]), textarea').first
            await fill_with_retry(input_el, value)
            print("      ✅ 已填充")
            return
        except:
            pass

    print(f"      ⚠️ 未找到字段: {label}")

async def read_select_state_and_value(page, label: str):
    """读取下拉控件状态与当前值：用于禁用字段快速跳过。"""
    item = await get_form_item_by_label(page, label)
    if not item:
        return {"found": False, "locked": False, "value": "", "full_text": ""}
    try:
        state = await item.evaluate("""(root) => {
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const lockedByClass = !!root.querySelector(
                '.el-select.is-disabled, .el-input.is-disabled, .ant-select-disabled, .el-date-editor.is-disabled'
            );
            const lockedByInput = !!Array.from(root.querySelectorAll('input, textarea, select'))
                .find(el => el.disabled || el.readOnly);
            const locked = lockedByClass || lockedByInput;
            const cands = [
                '.el-select__tags-text',
                '.el-input__inner',
                '.ant-select-selection-item',
                '.el-select .el-input__inner',
            ];
            let val = '';
            for (const sel of cands) {
                const nodes = Array.from(root.querySelectorAll(sel));
                for (const n of nodes) {
                    const v = norm((n.value || n.textContent || ''));
                    if (!v) continue;
                    if (/^\\+\\s*\\d+$/.test(v)) continue;
                    if (!val) val = v;
                }
                if (val) break;
            }
            const fullText = norm(root.textContent || '');
            return { found: true, locked, value: val, full_text: fullText };
        }""")
        return state or {"found": True, "locked": False, "value": "", "full_text": ""}
    except Exception:
        return {"found": True, "locked": False, "value": "", "full_text": ""}

async def select_radio(page, label: str, value: str):
    """选择单选项"""
    print(f"   ⚪ {label}: {value}")
    
    radio_groups = page.locator('.el-radio-group, .ant-radio-group')
    count = await radio_groups.count()
    
    for i in range(count):
        group = radio_groups.nth(i)
        try:
            parent = group.locator('xpath=..')
            parent_text = await parent.text_content()
            if label in parent_text:
                await group.click(f'text={value}')
                print(f"      ✅ 已选择")
                return
        except:
            continue

def split_datetime(raw: str, default_time: str = "00:00:00"):
    """将 YYYY-MM-DD HH:MM[:SS] 拆分为 (date, time) 并标准化为 HH:MM:SS。"""
    raw = (raw or "").strip()
    if " " in raw:
        date_part, time_part = raw.split(" ", 1)
    else:
        date_part, time_part = raw, default_time
    if len(time_part.split(":")) == 2:
        time_part = f"{time_part}:00"
    return date_part, time_part

def normalize_time_text(value: str) -> str:
    """标准化时间字符串用于比对。"""
    value = (value or "").strip().replace("T", " ").replace("/", "-")
    parts = value.split(" ")
    if len(parts) >= 2:
        date_part = parts[0]
        time_part = parts[1]
        if len(time_part.split(":")) == 2:
            time_part = f"{time_part}:00"
        return f"{date_part} {time_part}"
    return value

def datetime_equals(actual: str, expected: str) -> bool:
    """时间字符串严格等价比较（允许秒位缺省）。"""
    a = normalize_time_text(actual)
    e = normalize_time_text(expected)
    if a == e:
        return True
    if len(a.split(":")) == 3 and a.endswith(":00") and e == a[:-3]:
        return True
    if len(e.split(":")) == 3 and e.endswith(":00") and a == e[:-3]:
        return True
    return False

def values_include_datetime(values: list, date_part: str, time_part: str) -> bool:
    """检查一组输入值是否包含期望日期+时间。"""
    normalized_values = [normalize_time_text(v) for v in values if v]
    time_hm = ":".join(time_part.split(":")[:2])
    for val in normalized_values:
        if date_part in val and (time_part in val or time_hm in val):
            return True
    return False

async def click_picker_confirm_if_visible(page):
    """点击可见日期/时间面板的确定按钮。"""
    confirm_btn = page.locator(
        '.el-picker-panel__footer button:has-text("确定"), '
        '.el-time-panel__footer button.confirm, '
        '.el-time-panel__btn.confirm'
    ).first
    if await confirm_btn.count() > 0 and await confirm_btn.is_visible():
        await confirm_btn.click(force=True)
        await asyncio.sleep(0.2)
        return True
    return False

async def read_item_input_values(item) -> list:
    """读取表单项中所有 input 的 value。"""
    return await item.evaluate("""(node) => {
        const inputs = node.querySelectorAll('input');
        return Array.from(inputs).map(i => (i.value || '').trim()).filter(Boolean);
    }""")

async def click_button_with_text(page, include_text: str, exclude_text: str = "") -> bool:
    """点击按钮文本，返回是否点击成功。"""
    try:
        btn = page.locator("button").filter(has_text=include_text).first
        if await btn.count() > 0 and await btn.is_visible():
            txt = (await btn.text_content() or "").strip()
            if exclude_text and exclude_text in txt:
                pass
            else:
                await btn.click(force=True)
                return True
    except:
        pass

async def click_step2_next_button(page) -> bool:
    """第2步完成后，优先点击主页面底部“下一步”，避免点中弹窗内无效按钮。"""
    selectors = [
        'button:has-text("下一步")',
        '.el-button:has-text("下一步")',
        '.ant-btn:has-text("下一步")',
    ]
    for sel in selectors:
        try:
            btns = page.locator(sel)
            count = await btns.count()
            for i in range(count):
                btn = btns.nth(i)
                if not await btn.is_visible():
                    continue
                txt = ((await btn.text_content()) or "").strip()
                if "下一步" not in txt:
                    continue
                try:
                    await btn.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    await btn.click(force=True)
                    await asyncio.sleep(0.5)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    # 兜底：选取页面中最靠下的“下一步”按钮，通常是主页面底部按钮
    try:
        clicked = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const btns = Array.from(document.querySelectorAll('button')).filter(isVisible)
                .filter(btn => ((btn.textContent || '').trim()).includes('下一步'))
                .sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
            const btn = btns[0];
            if (!btn) return false;
            btn.click();
            return true;
        }""")
        if clicked:
            await asyncio.sleep(0.5)
            return True
    except Exception:
        pass
    return False

async def read_visible_error_hint(page) -> str:
    """读取页面当前可见的错误提示，优先抓 toast / 表单校验文本。"""
    try:
        msg = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const selectors = [
                '.el-message__content',
                '.ant-message-custom-content',
                '.el-form-item__error',
                '.ant-form-item-explain-error',
                '.el-alert__content'
            ];
            for (const sel of selectors) {
                const nodes = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                for (const node of nodes) {
                    const text = (node.textContent || '').trim();
                    if (text) return text;
                }
            }
            const bodyText = (document.body?.innerText || '');
            const known = [
                '发送时间不能选历史时间',
                '计划时间不能选历史时间',
                '不能为空',
                '请选择发送时间'
            ];
            for (const k of known) {
                if (bodyText.includes(k)) return k;
            }
            return '';
        }""")
        return (msg or "").strip()
    except Exception:
        return ""

    try:
        return await page.evaluate(
            """({includeText, excludeText}) => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const text = (btn.textContent || '').trim();
                    if (text.includes(includeText) && (!excludeText || !text.includes(excludeText))) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""",
            {"includeText": include_text, "excludeText": exclude_text}
        )
    except:
        return False

def split_multi_values(raw: str) -> list:
    """将多选值按中文顿号/逗号/斜杠拆分。"""
    if not raw:
        return []
    vals = [v.strip() for v in re.split(r"[、,，/]", raw) if v.strip()]
    return vals


def normalize_area_alias(area: str) -> str:
    """区域名称别名标准化（业务常用简称 -> 系统节点名）。"""
    a = (area or "").strip()
    if not a:
        return a
    # 先处理“xx加盟”后缀，标准化后再补回。
    is_join = a.endswith("加盟")
    base = a[:-2] if is_join else a
    alias_map = {
        "郑州": "大郑州营运区",
        "郑州加盟": "大郑州营运区加盟",
        "武汉": "武汉营运区",
        "武汉加盟": "武汉营运区加盟",
    }
    hit = alias_map.get(a)
    if hit:
        return hit

    # 业务侧常直接给“广州一/广州二/花都/番禺/佛山...”等营运区简称。
    # 规则：若不包含层级关键词，则按营运区简称补全为“xx营运区”。
    if not any(k in base for k in ("全国", "大区", "省区", "营运区", "片区", "门店", "店")):
        base = f"{base}营运区"

    return f"{base}加盟" if is_join else base


def normalize_area_for_step2(area: str) -> str:
    """第2步主消费营运区名称标准化。

    规则：
    - 保持“郑州”原值（业务要求第2步按页面原文匹配，不强制映射到“大郑州营运区”）。
    - 已包含层级关键词（大区/省区/营运区/片区/门店等）时不改写。
    - 纯简称（如“肇庆/云浮/南昌”）自动补全为“xx营运区”，提升匹配成功率。
    """
    a = (area or "").strip()
    if not a:
        return a
    if a == "郑州":
        return a
    if any(k in a for k in ("全国", "大区", "省区", "营运区", "片区", "门店", "店")):
        return a
    if a.endswith("加盟"):
        a = a[:-2]
    return f"{a}营运区"


def parse_step3_channels(raw: str) -> list:
    """解析第3步渠道多选字符串。支持 、 , ， / | 分隔。"""
    if not raw:
        return []
    vals = [v.strip() for v in re.split(r"[、,，/|]", raw) if v.strip()]
    # 去重并保序
    out = []
    seen = set()
    for v in vals:
        if v in seen:
            continue
        out.append(v)
        seen.add(v)
    return out

def resolve_channels_for_plan(plan: dict, step3_channels_override: str = "") -> list:
    """解析当前计划生效渠道：优先使用计划行 channels；为空才使用全局覆盖。"""
    plan_channels = parse_step3_channels(str(plan.get("channels", "") or ""))
    if plan_channels:
        return plan_channels
    return parse_step3_channels(step3_channels_override)


def infer_channels_from_create_url(url: str) -> list:
    """当计划行未写 channels 时，按创建链接反推渠道，避免被全局覆盖误伤。"""
    u = (url or "").strip()
    if not u:
        return []
    if "addcommunityPlan" in u:
        return ["会员通-发送社群"]
    for ch, cu in CHANNEL_CREATE_URLS.items():
        if cu and cu in u:
            return [ch]
    for combo, cu in CHANNEL_COMBO_CREATE_URLS.items():
        if cu and cu in u:
            return list(combo)
    return []


def resolve_base_url_by_channel(
    plan: dict,
    step3_channels_override: str = "",
    create_url_override: str = "",
) -> tuple[str, str]:
    """根据渠道选择创建链接。
    优先级：手动创建链接 > CSV create_url > 组合渠道规则 > 单渠道规则 > 默认链接。
    """
    manual_url = (create_url_override or "").strip()
    if manual_url:
        return manual_url, "手动创建链接"

    csv_url = str(plan.get("create_url", "") or "").strip()
    # 社群链接统一使用 checkType=add，避免旧表里残留 edit 导致行为不一致
    if "addcommunityPlan" in csv_url:
        if "checkType=edit" in csv_url:
            csv_url = re.sub(r"checkType=edit", "checkType=add", csv_url)
        elif "checkType=add" not in csv_url:
            csv_url = f"{csv_url}&checkType=add" if "?" in csv_url else f"{csv_url}?checkType=add"
    if csv_url:
        return csv_url, "CSV创建链接"

    channels = resolve_channels_for_plan(plan, step3_channels_override)
    if not channels:
        return BASE_URL, ""

    combo_url = CHANNEL_COMBO_CREATE_URLS.get(frozenset(channels))
    if combo_url:
        return combo_url, "短信+会员通-发客户消息"

    primary = channels[0]
    return CHANNEL_CREATE_URLS.get(primary, BASE_URL), primary


def parse_bool_flag(raw: str, default: bool = False) -> bool:
    """解析业务布尔值：是/否、true/false、1/0、y/n。"""
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if not v:
        return default
    if v in {"1", "true", "yes", "y", "on", "是", "需", "需要"}:
        return True
    if v in {"0", "false", "no", "n", "off", "否", "不", "不需要"}:
        return False
    return default


def parse_file_list(raw: str) -> list:
    """解析文件路径列表（支持 | 、 , ， ; ； 换行 分隔）。"""
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[|,，;；、\n\r]", str(raw)) if p.strip()]
    out = []
    seen = set()
    for p in parts:
        if p in seen:
            continue
        out.append(p)
        seen.add(p)
    return out

def is_valid_jpeg_png_file(path: str) -> bool:
    """校验文件真实格式，避免后缀对但内容非法。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if not data or len(data) < 16:
            return False
        # JPEG: starts with SOI(FFD8), and contains EOI(FFD9) later.
        # 不强制 EOI 在文件末尾，避免被尾部扩展数据误判。
        if data.startswith(b"\xff\xd8") and (b"\xff\xd9" in data[2:]):
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n") and (b"IEND" in data[-128:]):
            return True
        return False
    except Exception:
        return False

def sanitize_sms_content(content: str) -> str:
    """清洗短信内容中的高风险非法字符（按 P1106 场景）。"""
    if not content:
        return content
    sanitized = content
    # 系统明确报错包含【】；顺带处理常见全角装饰符，避免再次命中。
    replacements = {
        "【": "",
        "】": "",
        "『": "",
        "』": "",
        "「": "",
        "」": "",
    }
    for k, v in replacements.items():
        sanitized = sanitized.replace(k, v)
    return sanitized.strip()

async def fill_step3_end_time(page, end_time: str, section_hint: str = "") -> bool:
    """第3步结束时间：填入并确认日期面板。"""
    date_part, _ = split_datetime(end_time)
    ok = await page.evaluate("""(hint) => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const norm = (s) => (s || '').replace(/\\s+/g, '');
        const preferCommunity = norm(hint).includes('社群');
        const phHit = (i) => {
            const ph = (i.getAttribute('placeholder') || '').trim();
            return ['请选择结束日期', '结束日期', '结束时间', '选择日期', '选择时间'].some(x => ph.includes(x));
        };
        const markInput = (inp) => {
            if (!inp || !isVisible(inp)) return false;
            try { inp.removeAttribute('data-step3-endtime-target'); } catch(e) {}
            inp.setAttribute('data-step3-endtime-target', '1');
            return true;
        };
        if (preferCommunity) {
            const titles = Array.from(document.querySelectorAll('div,span,h1,h2,h3,h4,p,label'))
                .filter(n => isVisible(n) && norm(n.textContent || '') === '社群群发');
            let scope = null;
            const hasEndInput = (root) => {
                if (!root) return false;
                return Array.from(root.querySelectorAll('input')).some(i => isVisible(i) && phHit(i));
            };
            for (const t of titles) {
                let p = t;
                for (let i = 0; i < 10 && p; i++) {
                    if (hasEndInput(p)) {
                        scope = p;
                        break;
                    }
                    p = p.parentElement;
                }
                if (scope) break;
            }
            if (scope) {
                const rows = Array.from(scope.querySelectorAll('.item, .el-form-item, .ant-form-item, div')).filter(isVisible);
                for (const r of rows) {
                    const labels = Array.from(r.querySelectorAll('.label, label, span'))
                        .map(n => norm(n.textContent || ''))
                        .filter(Boolean);
                    const isEndRow = labels.some(t => t.includes('结束时间')) || norm(r.textContent || '').includes('结束时间');
                    if (!isEndRow) continue;
                    const inp = Array.from(r.querySelectorAll('input'))
                        .find(i => isVisible(i) && (phHit(i) || (i.className || '').includes('el-input__inner')));
                    if (markInput(inp)) return true;
                }
                const inp2 = Array.from(scope.querySelectorAll('input')).find(i => isVisible(i) && phHit(i));
                if (markInput(inp2)) {
                    return true;
                }
            }
        }
        const direct = Array.from(document.querySelectorAll('input')).find(inp => {
            if (!isVisible(inp)) return false;
            return phHit(inp);
        });
        if (markInput(direct)) {
            return true;
        }
        const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('结束时间')) continue;
            const inp = Array.from(it.querySelectorAll('input'))
                .find(i => isVisible(i) && /结束|日期/.test((i.getAttribute('placeholder') || '') + ' ' + (i.className || '')));
            if (markInput(inp)) return true;
        }
        return false;
    }""", section_hint)
    input_el = page.locator('input[data-step3-endtime-target="1"]').first if ok else None

    if input_el is None:
        debug = await page.evaluate("""() => {
            const labels = Array.from(document.querySelectorAll('span,label,div'))
              .map(n => (n.textContent || '').trim())
              .filter(t => t.includes('结束时间'))
              .slice(0, 5);
            const placeholders = Array.from(document.querySelectorAll('input'))
              .map(i => i.getAttribute('placeholder') || '')
              .filter(Boolean)
              .slice(0, 20);
            return {labels, placeholders};
        }""")
        print(f"      ⚠️ 结束时间定位诊断: {debug}")
        return False

    # 优先走组件面板路径，确保 ElementUI 内部值同步。
    try:
        await input_el.scroll_into_view_if_needed()
        await input_el.click(force=True)
        panel = page.locator('.el-picker-panel.el-date-picker:visible').first
        await panel.wait_for(timeout=2500)
        date_input = panel.get_by_placeholder("选择日期").first
        if await date_input.count() > 0:
            await fill_with_retry(date_input, date_part)
            await date_input.press("Enter")
        panel_confirm = panel.locator('.el-picker-panel__footer button:has-text("确定")').first
        if await panel_confirm.count() > 0 and await panel_confirm.is_visible():
            await panel_confirm.click(force=True)
        else:
            await click_button_with_text(page, "确定")
    except Exception:
        # 兜底：直接在字段输入并触发 Enter/blur/change
        await fill_with_retry(input_el, date_part)
        await input_el.press("Enter")
        await input_el.blur()
        await input_el.evaluate("""(input) => {
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.dispatchEvent(new Event('blur', { bubbles: true }));
        }""")

    await asyncio.sleep(0.3)
    # 再次触发失焦，避免“显示有值但模型为空”。
    await input_el.click(force=True)
    await page.keyboard.press("Tab")
    await asyncio.sleep(0.2)
    val = (await input_el.input_value()).strip()
    if date_part in val:
        if (section_hint or "").strip():
            sec_ok = await page.evaluate("""({dateText, hint}) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                if (!norm(hint).includes('社群')) return true;
                const titles = Array.from(document.querySelectorAll('div,span,h1,h2,h3,h4,p,label'))
                    .filter(n => isVisible(n) && norm(n.textContent || '') === '社群群发');
                const phHit = (i) => {
                    const ph = (i.getAttribute('placeholder') || '').trim();
                    return ['请选择结束日期', '结束日期', '结束时间', '选择日期', '选择时间'].some(x => ph.includes(x));
                };
                for (const t of titles) {
                    let p = t;
                    for (let i = 0; i < 10 && p; i++) {
                        const inp = Array.from(p.querySelectorAll('input')).find(x => isVisible(x) && phHit(x));
                        if (inp) {
                            return ((inp.value || '').trim().includes(dateText));
                        }
                        p = p.parentElement;
                    }
                }
                return false;
            }""", {"dateText": date_part, "hint": section_hint})
            if not sec_ok:
                print(f"      ⚠️ 结束时间社群板块回读失败，期望包含={date_part}")
                return False
        return True

    # 最终兜底：JS 强制写入可见“结束时间”字段（兼容 readonly 输入）
    hard_ok = await page.evaluate("""(dateText) => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const write = (inp) => {
            if (!inp || !isVisible(inp)) return false;
            inp.focus();
            inp.value = dateText;
            inp.setAttribute('value', dateText);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            inp.dispatchEvent(new Event('blur', { bubbles: true }));
            inp.blur();
            return true;
        };
        const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item'));
        for (const it of items) {
            const t = (it.textContent || '').replace(/\\s+/g, '');
            if (!t.includes('结束时间')) continue;
            const inp = it.querySelector('input[placeholder*="结束"], input[placeholder*="日期"], input.el-input__inner, input');
            if (write(inp)) return true;
        }
        const fallback = document.querySelector('input[placeholder*="请选择结束日期"], input[placeholder*="结束日期"], input[placeholder*="请选择结束"]');
        return write(fallback);
    }""", date_part)
    await asyncio.sleep(0.2)
    val = (await input_el.input_value()).strip()
    if hard_ok and date_part in val:
        return True
    print(f"      ⚠️ 结束时间回读失败，当前值={val}, 期望包含={date_part}")
    return False


async def fill_step3_group_name(page, group_name: str, section_hint: str = "") -> bool:
    """第3步下发群名（社群）。"""
    name = (group_name or "").strip()
    if not name:
        return False
    ok = await page.evaluate("""({name, hint}) => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const norm = (s) => (s || '').replace(/\\s+/g, '');
        const write = (el, v) => {
            if (!el || !isVisible(el)) return false;
            try { el.scrollIntoView({ block: 'center' }); } catch(e) {}
            el.focus();
            if ('value' in el) el.value = v;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            el.blur();
            return true;
        };
        const roots = [];
        if (norm(hint).includes('社群')) {
            const sec = Array.from(document.querySelectorAll('div,section,.item,.el-form-item,.ant-form-item'))
                .find(n => isVisible(n) && norm(n.textContent || '').includes('社群群发'));
            if (sec) roots.push(sec);
        }
        roots.push(document.body);
        for (const root of roots) {
            const rows = Array.from(root.querySelectorAll('.item, .el-form-item, .ant-form-item, div')).filter(isVisible);
            for (const r of rows) {
                const t = norm(r.textContent || '');
                if (!t.includes('下发群名')) continue;
                const ta = r.querySelector('textarea');
                if (write(ta, name)) {
                    ta.setAttribute('data-step3-groupname-target', '1');
                    return true;
                }
                const inp = r.querySelector('input[type="text"], input:not([type]), input');
                if (write(inp, name)) {
                    inp.setAttribute('data-step3-groupname-target', '1');
                    return true;
                }
            }
        }
        return false;
    }""", {"name": name, "hint": section_hint})
    if not ok:
        return False
    try:
        rb = await page.evaluate("""() => {
            const el = document.querySelector('[data-step3-groupname-target="1"]');
            if (!el) return '';
            return (el.value || el.textContent || '').trim();
        }""")
        return bool(rb and name in rb)
    except Exception:
        return True

async def fill_step3_send_content(page, content: str) -> bool:
    """第3步发送内容：固定写入“发送内容”对应编辑器，并清除默认值。"""
    ok = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const allEditable = Array.from(document.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]')).filter(isVisible);
        const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('发送内容')) continue;
            const ed = Array.from(it.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]'))
                .find(isVisible);
            if (ed) {
                ed.setAttribute('data-step3-send-target', '1');
                return true;
            }
        }
        // 兜底：优先取最后一个可见编辑器。短信/发送内容场景通常发送内容在后面。
        if (allEditable.length > 0) {
            allEditable[allEditable.length - 1].setAttribute('data-step3-send-target', '1');
            return true;
        }
        return false;
    }""")
    if not ok:
        return False
    editable = page.locator('[data-step3-send-target="1"]').first
    if await editable.count() == 0:
        return False
    try:
        await editable.scroll_into_view_if_needed()
        await editable.click(force=True)
    except:
        pass
    old_text = ((await editable.inner_text()) or "").strip()
    need_clear = len(old_text) > 0
    print(f"      🧪 发送内容旧值长度: {len(old_text)}")
    print(f"      🧪 发送内容是否执行清空: {'是' if need_clear else '否'}")

    ok = await editable.evaluate(
        """(el, text) => {
            const oldText = (el.innerText || el.textContent || '').trim();
            const needClear = oldText.length > 0;
            el.focus();
            if (needClear) {
                el.innerHTML = '';
                el.textContent = '';
            }
            const line = document.createElement('div');
            line.textContent = text;
            el.appendChild(line);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('keyup', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            el.blur();
            const rb = (el.innerText || el.textContent || '').trim();
            return rb.includes(text.slice(0, 4)) && rb.length > 0;
        }""",
        content
    )
    if not ok:
        return False
    rb = ((await editable.inner_text()) or "").strip()
    return len(rb) > 0 and (content[:4] in rb if len(content) >= 4 else content in rb)

async def fill_step3_sms_content(page, content: str) -> bool:
    """第3步短信内容：固定写入“短信内容(必填)”对应编辑器，并校验长度>0。"""
    ok = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('短信内容')) continue;
            const ed = Array.from(it.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]'))
                .find(isVisible);
            if (ed) {
                ed.setAttribute('data-step3-sms-target', '1');
                return true;
            }
        }
        return false;
    }""")
    if not ok:
        return False
    editable = page.locator('[data-step3-sms-target="1"]').first
    if await editable.count() == 0:
        return False
    try:
        await editable.scroll_into_view_if_needed()
        await editable.click(force=True)
    except:
        pass
    ok = await editable.evaluate(
        """(el, text) => {
            el.focus();
            el.innerHTML = '';
            el.textContent = '';
            const line = document.createElement('div');
            line.textContent = text;
            el.appendChild(line);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('keyup', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
            el.blur();
            const rb = (el.innerText || el.textContent || '').trim();
            return rb.includes(text.slice(0, 4)) && rb.length > 0;
        }""",
        content
    )
    if not ok:
        return False
    rb = ((await editable.inner_text()) or "").strip()
    if not rb:
        return False
    # 结合长度控件做二次校验（如果存在）
    try:
        length_el = page.locator('[data-step3-sms-target="1"]').locator('xpath=ancestor::*[contains(@class,"item")][1]').locator(".length").first
        if await length_el.count() > 0:
            length_text = ((await length_el.text_content()) or "").strip()
            m = re.search(r"(\\d+)\\s*/", length_text)
            if m and int(m.group(1)) <= 0:
                return False
    except:
        pass
    return True


async def upload_step3_moments_images(page, raw_paths: str):
    """第3步朋友圈图片上传（稳态）：优先批量上传，失败后慢速逐张上传。"""
    img_paths_raw = parse_file_list(raw_paths)
    if not img_paths_raw:
        return False, "未提供图片路径"

    if len(img_paths_raw) > 9:
        return False, f"图片数量超限：{len(img_paths_raw)}（最多9张）"

    resolved = []
    for p in img_paths_raw:
        path = Path(os.path.expanduser(p))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return False, f"图片不存在: {path}"
        ext = path.suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            return False, f"图片格式不支持: {path.name}（仅支持jpg/png）"
        size = path.stat().st_size
        if size >= 10 * 1024 * 1024:
            return False, f"图片超10MB: {path.name}"
        resolved.append(str(path))

    # 定位朋友圈“添加图片”区域（只做静默 set_input_files，避免弹系统文件夹）
    locate_info = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const normalize = (s) => (s || '').replace(/\\s+/g, '');

        const markInputNear = (node) => {
            const uploadWrap = node?.closest('.el-upload, .upload-btn, .avatar-uploader, .item, .el-form-item') || node;
            if (!uploadWrap) return false;
            let input = uploadWrap.querySelector('input[type="file"]');
            if (!input && uploadWrap.parentElement) input = uploadWrap.parentElement.querySelector('input[type="file"]');
            if (!input) return false;
            input.setAttribute('data-step3-image-input', '1');
            return true;
        };

        // 路径1：精准命中 upload-btn 内 text1=添加图片
        const uploadBtns = Array.from(document.querySelectorAll('.upload-btn')).filter(isVisible);
        for (const btn of uploadBtns) {
            const text1 = btn.querySelector('.text1');
            const t = normalize(text1 ? text1.textContent : btn.textContent);
            if (!t.includes('添加图片')) continue;
            btn.setAttribute('data-step3-image-trigger', '1');
            const root = btn.closest('.item, .el-form-item, .ant-form-item, .channel, .module, .card') || btn.parentElement || btn;
            if (root) root.setAttribute('data-step3-image-root', '1');
            const hasInput = markInputNear(btn);
            return { ok: true, mode: 'upload-btn', hasInput };
        }

        // 路径2：全局文本命中“添加图片”，回溯到可点击容器
        const textNodes = Array.from(document.querySelectorAll('.text1, span, div, button, a')).filter(isVisible);
        for (const n of textNodes) {
            const t = normalize(n.textContent || '');
            if (!t.includes('添加图片')) continue;
            const clickable = n.closest('.upload-btn, .el-upload, button, a, div, span') || n;
            clickable.setAttribute('data-step3-image-trigger', '1');
            const root = clickable.closest('.item, .el-form-item, .ant-form-item, .channel, .module, .card') || clickable.parentElement || clickable;
            if (root) root.setAttribute('data-step3-image-root', '1');
            const hasInput = markInputNear(clickable);
            return { ok: true, mode: 'text-fallback', hasInput };
        }
        return { ok: false, mode: 'not-found' };
    }""")
    if not locate_info or (not locate_info.get("ok")):
        return False, f"未找到“添加图片”上传入口（mode={locate_info.get('mode','unknown') if locate_info else 'unknown'}）"

    print(f"      🧪 图片入口定位: {locate_info.get('mode', 'unknown')}")

    async def _locate_image_input():
        marked_input = page.locator('input[type="file"][data-step3-image-input="1"]').last
        if await marked_input.count() > 0:
            return marked_input
        scoped_input = page.locator('[data-step3-image-root="1"] input[type="file"]').last
        if await scoped_input.count() > 0:
            return scoped_input
        img_accept_input = page.locator('input[type="file"][accept*="image"], input[type="file"][accept*=".jpg"], input[type="file"][accept*=".png"]').last
        if await img_accept_input.count() > 0:
            return img_accept_input
        file_input = page.locator('input[type="file"]').last
        if await file_input.count() > 0:
            return file_input
        return None

    async def _read_upload_state(file_name: str = ""):
        return await page.evaluate(
            """(fn) => {
                const root = document.querySelector('[data-step3-image-root="1"]') || document;
                const txt = (root.textContent || '').replace(/\\s+/g, '');
                const listCount =
                    root.querySelectorAll('.el-upload-list__item').length ||
                    root.querySelectorAll('[class*="upload-list"] [class*="item"]').length ||
                    root.querySelectorAll('.name').length;
                const uploadingCount =
                    root.querySelectorAll('.el-upload-list__item.is-uploading, .el-upload-list__item .el-icon-loading').length ||
                    root.querySelectorAll('[class*="upload-list"] [class*="uploading"], [class*="upload-list"] .loading').length;
                const hasName = fn ? txt.includes((fn || '').replace(/\\s+/g, '')) : false;
                return { listCount, hasName, uploadingCount };
            }""",
            file_name or "",
        )

    async def _wait_uploaded(file_name: str, before_count: int):
        rounds = max(1, int(MOMENTS_UPLOAD_WAIT_SECONDS / 0.4))
        for _ in range(rounds):
            st = await _read_upload_state(file_name)
            if (st.get("listCount", 0) > before_count) or st.get("hasName"):
                return True, st
            await asyncio.sleep(0.4)
        st = await _read_upload_state(file_name)
        return False, st

    async def _wait_upload_quiet(expected_count: int):
        rounds = max(4, int(MOMENTS_UPLOAD_WAIT_SECONDS / 0.4))
        stable_hits = 0
        for _ in range(rounds):
            st = await _read_upload_state("")
            list_ok = int(st.get("listCount", 0)) >= int(expected_count)
            uploading = int(st.get("uploadingCount", 0))
            if list_ok and uploading == 0:
                stable_hits += 1
                if stable_hits >= 3:
                    return True, st
            else:
                stable_hits = 0
            await asyncio.sleep(0.4)
        st = await _read_upload_state("")
        return False, st

    async def _all_names_present(paths: list[str]) -> bool:
        names = [Path(p).name for p in paths]
        return await page.evaluate(
            """(arr) => {
                const txt = (document.body?.innerText || document.body?.textContent || '').replace(/\\s+/g, '');
                return (arr || []).every(n => txt.includes((n || '').replace(/\\s+/g, '')));
            }""",
            names,
        )

    async def _name_present(path: str) -> bool:
        name = Path(path).name
        return await page.evaluate(
            """(n) => {
                const txt = (document.body?.innerText || document.body?.textContent || '').replace(/\\s+/g, '');
                return txt.includes((n || '').replace(/\\s+/g, ''));
            }""",
            name,
        )

    # 方案A：批量上传（静默 set_input_files，不触发 filechooser）
    batch_ok = False
    if MOMENTS_UPLOAD_MODE in ("batch_then_slow", "batch", "auto"):
        try:
            before = await _read_upload_state("")
            input_el = await _locate_image_input()
            if input_el is not None:
                await input_el.set_input_files(resolved)
            else:
                raise RuntimeError("未找到图片上传input")

            ok, st = await _wait_uploaded("", before.get("listCount", 0))
            if ok:
                quiet_ok, quiet_st = await _wait_upload_quiet(min(len(resolved), 9))
                if not quiet_ok:
                    print(f"      ⚠️ 批量上传稳态等待未完成，继续按文件名校验: {quiet_st}")
                batch_ok = True
                print(f"      ✅ 批量上传图片成功: {len(resolved)}张")
            else:
                # 回读不稳定时，再用“全页面文件名命中”做二次确认，避免重复上传超9张
                by_name_ok = await _all_names_present(resolved)
                if by_name_ok:
                    batch_ok = True
                    print(f"      ✅ 批量上传按文件名校验通过: {len(resolved)}张")
                else:
                    print(f"      ⚠️ 批量上传回读未确认，切换慢速逐张上传: {st}")
        except Exception as e:
            print(f"      ⚠️ 批量上传失败，切换慢速逐张上传: {e}")

    if not batch_ok:
        # 方案B：慢速逐张上传（默认节奏更慢，降低限流概率）
        weak_pass = 0
        for idx, file_path in enumerate(resolved, 1):
            # 已存在则不重复上传，防止超过“最多9张”
            if await _name_present(file_path):
                print(f"      ⏭️ 第{idx}张已存在，跳过重复上传: {Path(file_path).name}")
                await asyncio.sleep(0.2)
                continue
            before = await _read_upload_state(Path(file_path).name)
            input_el = await _locate_image_input()
            if input_el is None:
                return False, f"第{idx}张上传失败: 未找到图片上传input"
            try:
                await input_el.set_input_files(file_path)
            except Exception as e:
                return False, f"第{idx}张上传失败: {Path(file_path).name} ({e})"

            ok, st = await _wait_uploaded(Path(file_path).name, before.get("listCount", 0))
            if not ok:
                weak_pass += 1
                print(f"      ⚠️ 第{idx}张上传回读弱校验未命中，按已提交继续: {Path(file_path).name} (state={st})")
            else:
                print(f"      ✅ 已上传图片({idx}/{len(resolved)}): {Path(file_path).name}")

            # 后几张更容易触发后端上传并发限流，追加稳态等待
            extra_wait = 0.0
            if idx >= 7:
                extra_wait = 0.8
            await asyncio.sleep(max(0.8, MOMENTS_UPLOAD_DELAY_SECONDS) + extra_wait)

        quiet_ok, quiet_st = await _wait_upload_quiet(min(len(resolved), 9))
        if not quiet_ok:
            print(f"      ⚠️ 慢速上传后稳态等待未完全命中: {quiet_st}")

        if weak_pass == len(resolved):
            return True, f"已提交上传{len(resolved)}张（回读弱校验）"

    return True, f"已上传{len(resolved)}张"


async def fill_step3_message_mini_program(
    page,
    program_name: str,
    program_title: str,
    cover_path: str,
    page_path: str,
):
    """第3步（会员通-发客户消息）添加小程序。"""
    raw_program_name = (program_name or "大参林健康").strip()
    _program_candidates = [x.strip() for x in re.split(r"[、,，/|]", raw_program_name) if x.strip()]
    program_name = (_program_candidates[0] if _program_candidates else "大参林健康").strip()
    program_title = (program_title or "").strip()
    page_path = (page_path or "").strip()
    cover_path = os.path.expanduser((cover_path or "").strip())

    errors = []
    if not program_title:
        errors.append("小程序标题为空")
    if not page_path:
        errors.append("小程序功能页面为空")
    if not cover_path:
        errors.append("小程序封面路径为空")
    elif not os.path.exists(cover_path):
        errors.append(f"小程序封面不存在: {cover_path}")
    else:
        ext = Path(cover_path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            errors.append(f"小程序封面后缀非法: {Path(cover_path).name}（仅支持jpg/png）")
    if errors:
        return False, " / ".join(errors)

    clicked = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const norm = (s) => (s || '').replace(/\\s+/g, '');
        const fireClick = (el) => {
            if (!el) return false;
            try { el.scrollIntoView({ block: 'center' }); } catch(e) {}
            try { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); } catch(e) {}
            try { el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); } catch(e) {}
            try { el.click(); } catch(e) { return false; }
            return true;
        };

        // 优先：精确命中“添加小程序”
        const uploadBtns = Array.from(document.querySelectorAll('.upload-btn')).filter(isVisible);
        for (const btn of uploadBtns) {
            const t = norm(btn.textContent || '');
            if (t.includes('添加小程序')) {
                return fireClick(btn);
            }
        }

        // 兜底：全局文本节点
        const nodes = Array.from(document.querySelectorAll('button, a, span, div')).filter(isVisible);
        const hit = nodes.find(n => {
            const t = norm(n.textContent || '');
            return t.includes('添加小程序');
        });
        if (!hit) return false;
        return fireClick(hit.closest('button,a,div,span,.el-upload,.upload-btn') || hit);
    }""")
    if not clicked:
        clicked = await click_button_with_text(page, "添加小程序")
    if not clicked:
        return False, "未找到“添加小程序/添加文件视频”入口"

    # 以“配置小程序”字段出现作为弹窗成功标准，避免仅靠 wrapper 判断误差
    modal_ready = False
    for _ in range(20):
        has_cfg = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const labels = Array.from(document.querySelectorAll('.el-dialog__wrapper .el-form-item__label, .el-dialog .el-form-item__label, .el-form-item__label'))
                .filter(isVisible)
                .map(n => (n.textContent || '').replace(/\\s+/g, ''));
            return labels.some(t => t.includes('配置小程序'));
        }""")
        if has_cfg:
            modal_ready = True
            break
        await asyncio.sleep(0.25)
    if not modal_ready:
        return False, "未弹出小程序配置弹窗"

    has_visible_dialog = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        return Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).some(isVisible);
    }""")
    inline_mode = not bool(has_visible_dialog)
    modal = page.locator('.el-dialog__wrapper:visible, .el-dialog:visible').last if has_visible_dialog else page.locator('body')

    select_marked = await modal.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const items = Array.from(document.querySelectorAll('.el-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('配置小程序')) continue;
            const inp = it.querySelector('input.el-input__inner[placeholder*="请选择"], input[placeholder*="请选择"]');
            if (!inp) continue;
            inp.setAttribute('data-step3-mini-program-select', '1');
            return true;
        }
        return false;
    }""")
    selected_ok = False
    option_diag = []
    # 先按社群弹窗的真实交互走一遍：
    # 点击“配置小程序”输入框 -> 选择“大参林健康”
    try:
        deterministic_ok = await page.evaluate("""(name) => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const dialogs = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
            const dlg = dialogs.find(d => norm(d.textContent || '').includes('添加小程序消息')) || dialogs[dialogs.length - 1];
            if (!dlg) return false;
            const rows = Array.from(dlg.querySelectorAll('.el-form-item')).filter(isVisible);
            const cfgRow = rows.find(r => norm(r.textContent || '').includes('配置小程序'));
            if (!cfgRow) return false;
            const input = cfgRow.querySelector('.el-select .el-input__inner');
            if (!input) return false;
            try { input.scrollIntoView({ block: 'center' }); } catch(e) {}
            try { input.click(); } catch(e) { return false; }
            return true;
        }""", program_name)
        if deterministic_ok:
            await asyncio.sleep(0.25)
            picked = await page.evaluate("""(name) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const expect = norm(name);
                const items = Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item')).filter(isVisible);
                // 精确优先：大参林健康
                let hit = items.find(i => norm(i.textContent || '') === expect || norm(i.textContent || '').includes(expect));
                // 兜底：如果 name 不可用，优先“健康”而不是“国际”
                if (!hit) {
                    hit = items.find(i => norm(i.textContent || '').includes('大参林健康')) || null;
                }
                if (!hit) return false;
                try { hit.click(); } catch(e) { return false; }
                return true;
            }""", program_name)
            if picked:
                await asyncio.sleep(0.2)
                selected_ok = await page.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const norm = (s) => (s || '').replace(/\\s+/g, '');
                    const dialogs = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                    const dlg = dialogs.find(d => norm(d.textContent || '').includes('添加小程序消息')) || dialogs[dialogs.length - 1];
                    if (!dlg) return false;
                    const rows = Array.from(dlg.querySelectorAll('.el-form-item')).filter(isVisible);
                    const cfgRow = rows.find(r => norm(r.textContent || '').includes('配置小程序'));
                    if (!cfgRow) return false;
                    const input = cfgRow.querySelector('.el-select .el-input__inner');
                    const v = norm((input && input.value) || '');
                    return !!v && !v.includes('请选择');
                }""")
    except Exception:
        selected_ok = False
    try:
        await modal.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const items = Array.from(document.querySelectorAll('.el-form-item')).filter(isVisible);
            for (const it of items) {
                const txt = (it.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('配置小程序')) continue;
                const sel = it.querySelector('.el-select');
                if (sel) sel.setAttribute('data-step3-mini-select-root', '1');
            }
        }""")
        for _ in range(3):
            select_input = None
            select_root = None
            croot = modal.locator('[data-step3-mini-select-root="1"]').first
            if await croot.count() > 0:
                select_root = croot
            if select_marked:
                cand = modal.locator('input[data-step3-mini-program-select="1"]').first
                if await cand.count() > 0:
                    select_input = cand
            if select_input is None:
                cand = modal.locator('.el-select input.el-input__inner[placeholder*="请选择"], .el-select input[placeholder*="请选择"]').first
                if await cand.count() > 0:
                    select_input = cand
            if select_input is None:
                break

            # 先点击 select root/caret，再点击 input，确保下拉真实展开
            if select_root is not None:
                try:
                    caret = select_root.locator('.el-input__suffix, .el-select__caret, .el-input__inner').first
                    if await caret.count() > 0:
                        await caret.click(force=True)
                        await asyncio.sleep(0.1)
                except Exception:
                    pass
            await select_input.click(force=True)
            await asyncio.sleep(0.2)

            # 仅在当前可见下拉中精确选择，避免误点页面其它链接（例如下载模板）
            option_texts = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                return Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item'))
                    .filter(isVisible)
                    .map(n => (n.textContent || '').replace(/\\s+/g, ''))
                    .filter(Boolean);
            }""")
            option_diag = option_texts or []
            option = page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter(has_text=program_name).first
            if await option.count() > 0:
                await option.click(force=True)
            else:
                clicked_in_modal = await page.evaluate("""(name) => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const norm = (s) => (s || '').replace(/\\s+/g, '');
                    const expect = norm(name);
                    const items = Array.from(document.querySelectorAll('.el-select-dropdown:not([style*="display: none"]) .el-select-dropdown__item, .el-select-dropdown:visible .el-select-dropdown__item'))
                        .filter(isVisible);
                    const exact = items.find(it => norm(it.textContent || '') === expect || norm(it.textContent || '').includes(expect));
                    if (!exact) return false;
                    try { exact.scrollIntoView({ block: 'nearest' }); } catch(e) {}
                    try { exact.click(); } catch(e) { return false; }
                    return true;
                }""", program_name)
                if not clicked_in_modal:
                    # 不再盲选第一项，避免误选导致看似提交成功但实际配置错误
                    pass
            # 键盘兜底：Element 下拉在某些页面仅键盘可稳定落选
            try:
                await select_input.press("ArrowDown")
                await asyncio.sleep(0.08)
                await page.keyboard.press("Enter")
            except Exception:
                pass

            await asyncio.sleep(0.25)
            selected_ok = await modal.evaluate("""(name) => {
                const normalize = (s) => (s || '').replace(/\\s+/g, '');
                const expect = normalize(name);
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };

                const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                const root = wrappers.length ? wrappers[wrappers.length - 1] : document;
                const item = Array.from(root.querySelectorAll('.el-form-item')).find(it =>
                    normalize(it.textContent || '').includes('配置小程序')
                );
                const scope = item || root;

                const inp = scope.querySelector('input[data-step3-mini-program-select="1"]')
                    || scope.querySelector('.el-select input.el-input__inner')
                    || scope.querySelector('input.el-input__inner[placeholder*="请选择"]');
                const v = normalize(inp ? (inp.value || '') : '');
                if (v.includes(expect)) return true;

                const selectedNodeText = normalize(scope.textContent || '');
                if (selectedNodeText.includes(expect)) return true;

                const selectedDropdownItem = Array.from(document.querySelectorAll('.el-select-dropdown__item.selected, .el-select-dropdown__item.is-selected'))
                    .map(n => normalize(n.textContent || ''))
                    .join(' ');
                if (selectedDropdownItem.includes(expect)) return true;
                return false;
            }""", program_name)
            if selected_ok:
                break
        if not selected_ok:
            # 兜底：只在“添加小程序消息”弹窗内精确点选目标项
            forced_click = await page.evaluate("""(name) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const dialogs = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                const dlg = dialogs.find(d => norm(d.textContent || '').includes('添加小程序消息')) || dialogs[dialogs.length - 1];
                if (!dlg) return false;
                const rows = Array.from(dlg.querySelectorAll('.el-form-item')).filter(isVisible);
                const cfgRow = rows.find(r => norm(r.textContent || '').includes('配置小程序'));
                if (!cfgRow) return false;
                const trigger =
                    cfgRow.querySelector('.el-select .el-input__inner') ||
                    cfgRow.querySelector('.el-select .el-input__suffix') ||
                    cfgRow.querySelector('.el-select');
                if (!trigger) return false;
                try { trigger.scrollIntoView({ block: 'center' }); } catch(e) {}
                try { trigger.click(); } catch(e) { return false; }
                const items = Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item')).filter(isVisible);
                const hit = items.find(i => norm(i.textContent || '').includes(norm(name)));
                if (!hit) return false;
                try { hit.click(); } catch(e) { return false; }
                return true;
            }""", program_name)
            if forced_click:
                await asyncio.sleep(0.3)
                selected_ok = await modal.evaluate("""(name) => {
                    const normalize = (s) => (s || '').replace(/\\s+/g, '');
                    const expect = normalize(name);
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                    const root = wrappers.find(w => normalize(w.textContent || '').includes('添加小程序消息')) || (wrappers.length ? wrappers[wrappers.length - 1] : document);
                    const item = Array.from(root.querySelectorAll('.el-form-item')).find(it => normalize(it.textContent || '').includes('配置小程序'));
                    const scope = item || root;
                    const inp = scope.querySelector('input.el-input__inner');
                    const v = normalize(inp ? (inp.value || '') : '');
                    return !!v && !v.includes('请选择') && (expect ? v.includes(expect) : true);
                }""", program_name)
        if not selected_ok:
            # 最后兜底：选第一个可见选项，避免空值阻断
            pick_first = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const dialogs = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                const dlg = dialogs.find(d => norm(d.textContent || '').includes('添加小程序消息')) || dialogs[dialogs.length - 1];
                if (!dlg) return false;
                const rows = Array.from(dlg.querySelectorAll('.el-form-item')).filter(isVisible);
                const cfgRow = rows.find(r => norm(r.textContent || '').includes('配置小程序'));
                if (!cfgRow) return false;
                const trigger =
                    cfgRow.querySelector('.el-select .el-input__inner') ||
                    cfgRow.querySelector('.el-select .el-input__suffix') ||
                    cfgRow.querySelector('.el-select');
                if (!trigger) return false;
                try { trigger.click(); } catch(e) { return false; }
                const items = Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item, .el-scrollbar__view .el-select-dropdown__item, .el-scrollbar__view li'))
                    .filter(isVisible);
                if (!items.length) return false;
                try { items[0].click(); } catch(e) { return false; }
                return true;
            }""")
            if pick_first:
                await asyncio.sleep(0.3)
                selected_ok = await modal.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const labels = Array.from(document.querySelectorAll('.el-form-item__label')).filter(isVisible);
                    for (const lb of labels) {
                        const t = (lb.textContent || '').replace(/\\s+/g, '');
                        if (!t.includes('配置小程序')) continue;
                        const row = lb.closest('.el-form-item') || lb.parentElement;
                        const inp = (row && row.querySelector('input.el-input__inner')) || null;
                        const v = (inp && inp.value ? inp.value : '').replace(/\\s+/g, '');
                        if (v && !v.includes('请选择')) return true;
                    }
                    return false;
                }""")
    except Exception:
        selected_ok = False

    if (not selected_ok) and inline_mode:
        # 内联模式下，部分页面不会标准回显“选中项”，改为“有有效值”即可
        selected_ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const labels = Array.from(document.querySelectorAll('.el-form-item__label')).filter(isVisible);
            for (const lb of labels) {
                const t = (lb.textContent || '').replace(/\\s+/g, '');
                if (!t.includes('配置小程序')) continue;
                const row = lb.closest('.el-form-item') || lb.parentElement;
                const inp = (row && row.querySelector('input.el-input__inner')) || null;
                const v = (inp && inp.value ? inp.value : '').replace(/\\s+/g, '');
                if (v && !v.includes('请选择')) return true;
            }
            return false;
        }""")
    if not selected_ok:
        diag = {}
        try:
            diag = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const dialogs = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                const dlg = dialogs.find(d => norm(d.textContent || '').includes('添加小程序消息')) || dialogs[dialogs.length - 1];
                if (!dlg) return { hasDialog: false, curr: '', opts: [] };
                const rows = Array.from(dlg.querySelectorAll('.el-form-item')).filter(isVisible);
                const cfgRow = rows.find(r => norm(r.textContent || '').includes('配置小程序'));
                const curr = cfgRow ? (cfgRow.querySelector('input.el-input__inner')?.value || '') : '';
                const opts = Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item'))
                    .filter(isVisible)
                    .map(n => (n.textContent || '').trim())
                    .filter(Boolean)
                    .slice(0, 8);
                return { hasDialog: true, curr, opts };
            }""")
        except Exception:
            diag = {}
        if diag:
            print(f"      🧪 小程序下拉诊断: curr={diag.get('curr','')}, opts={diag.get('opts',[])}")
            curr = str(diag.get("curr", "") or "").replace(" ", "")
            expect = str(program_name or "").replace(" ", "")
            if curr and ("请选择" not in curr) and ((expect and expect in curr) or ("大参林" in curr)):
                selected_ok = True
        if not option_diag:
            try:
                option_diag = await page.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    return Array.from(document.querySelectorAll('.el-select-dropdown .el-select-dropdown__item'))
                        .filter(isVisible)
                        .map(n => (n.textContent || '').replace(/\\s+/g, ''))
                        .filter(Boolean)
                        .slice(0, 8);
                }""")
            except Exception:
                option_diag = []
        if not selected_ok:
            d = (" / 可见选项=" + "、".join(option_diag[:6])) if option_diag else ""
            errors.append(f"配置小程序未选中: {program_name}{d}")

    try:
        title_input = None
        c1 = modal.get_by_placeholder("请输入小程序标题").first
        if await c1.count() > 0:
            title_input = c1
        if title_input is None:
            c2 = page.get_by_placeholder("请输入小程序标题").last
            if await c2.count() > 0:
                title_input = c2
        if title_input is None:
            c3 = page.locator('input.el-input__inner[placeholder*="小程序标题"]:visible').last
            if await c3.count() > 0:
                title_input = c3
        if title_input is None:
            errors.append("未找到小程序标题输入框")
        else:
            await fill_with_retry(title_input, program_title)
    except Exception:
        errors.append("填写小程序标题失败")

    try:
        page_input = None
        for ph in ["请输入页面路径", "请输入小程序链接", "请输入链接"]:
            c = modal.get_by_placeholder(ph).first
            if await c.count() > 0:
                page_input = c
                break
        if page_input is None:
            for ph in ["请输入页面路径", "请输入小程序链接", "请输入链接"]:
                c = page.get_by_placeholder(ph).last
                if await c.count() > 0:
                    page_input = c
                    break
        if page_input is None:
            c3 = page.locator('input.el-input__inner[placeholder*="页面路径"], input.el-input__inner[placeholder*="链接"]:visible').last
            if await c3.count() > 0:
                page_input = c3
        if page_input is None:
            errors.append("未找到页面路径输入框")
        else:
            await fill_with_retry(page_input, page_path)
    except Exception:
        errors.append("填写页面路径失败")

    cover_marked = await modal.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const items = Array.from(document.querySelectorAll('.el-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('小程序封面')) continue;
            const input = it.querySelector('input[type="file"]');
            if (!input) continue;
            input.setAttribute('data-step3-mini-cover-input', '1');
            return true;
        }
        return false;
    }""")
    if not cover_marked:
        errors.append("未找到小程序封面上传控件")
    try:
        if cover_marked:
            cover_input = modal.locator('input[data-step3-mini-cover-input="1"]').first
            if await cover_input.count() > 0:
                await cover_input.set_input_files(cover_path)
            else:
                fallback_cover = page.locator('input[data-step3-mini-cover-input="1"]').first
                if await fallback_cover.count() == 0:
                    errors.append("未找到小程序封面上传input")
                else:
                    await fallback_cover.set_input_files(cover_path)
            await asyncio.sleep(0.6)
    except Exception:
        errors.append(f"上传小程序封面失败: {Path(cover_path).name}")

    confirm_clicked = False
    for _ in range(3):
        try:
            confirm_btn = modal.locator('button.el-button--primary:visible').filter(has_text='确定').first
            if await confirm_btn.count() > 0:
                await confirm_btn.click(force=True)
                confirm_clicked = True
            else:
                save_btn = modal.locator('button.el-button--primary:visible').filter(has_text='保存').first
                if await save_btn.count() > 0:
                    await save_btn.click(force=True)
                    confirm_clicked = True
        except Exception:
            confirm_clicked = False
        await asyncio.sleep(0.35)
        still_open = await modal.count() > 0 and await modal.is_visible()
        if confirm_clicked and (not still_open):
            break
        # 兜底：直接在最上层可见弹窗 footer 再点一次主按钮
        try:
            clicked_footer = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper, .el-dialog')).filter(isVisible);
                if (!wrappers.length) return false;
                const current = wrappers[wrappers.length - 1];
                const btns = Array.from(current.querySelectorAll('.el-dialog__footer button')).filter(isVisible);
                const primary = btns.find(b => (b.textContent || '').replace(/\\s+/g, '').includes('确定'))
                    || btns.find(b => (b.textContent || '').replace(/\\s+/g, '').includes('保存'))
                    || btns.find(b => b.className.includes('el-button--primary'));
                if (!primary) return false;
                ['pointerdown','mousedown','mouseup','click'].forEach(t => {
                    primary.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof primary.click === 'function') primary.click();
                return true;
            }""")
            if clicked_footer:
                confirm_clicked = True
                await asyncio.sleep(0.3)
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
        except Exception:
            pass

    if not confirm_clicked:
        try:
            global_ok = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const btns = Array.from(document.querySelectorAll('button.el-button--primary, button')).filter(isVisible);
                const hit = btns.find(b => {
                    const t = norm(b.textContent || '');
                    return t === '确定' || t === '保存' || t.includes('确定') || t.includes('保存');
                });
                if (!hit) return false;
                try { hit.scrollIntoView({ block: 'center' }); } catch(e) {}
                try { hit.click(); } catch(e) { return false; }
                return true;
            }""")
            if global_ok:
                confirm_clicked = True
        except Exception:
            pass
    if not confirm_clicked:
        errors.append("未找到小程序弹窗确认按钮")

    await asyncio.sleep(0.4)
    still_open_after = False
    if not inline_mode:
        still_open_after = await modal.count() > 0 and await modal.is_visible()
    if (not inline_mode) and still_open_after:
        errors.append("小程序弹窗未关闭（确认可能未生效）")

    # 最终成功判定：以主页面出现“小程序”素材名称为准（例如：`（小程序）测试`）
    # 这是业务侧真实成功信号，优先级高于下拉回读。
    mini_created = await page.evaluate("""(titleText) => {
        const normalize = (s) => (s || '').replace(/\\s+/g, '');
        const t = normalize(titleText);
        const nodes = Array.from(document.querySelectorAll('span,div,a'));
        const texts = nodes.map(n => normalize(n.textContent || '')).filter(Boolean);
        const hasMiniPrefix = texts.some(x => x.includes('（小程序）') || x.includes('(小程序)'));
        if (!hasMiniPrefix) return false;
        if (!t) return true;
        return texts.some(x => (x.includes('（小程序）') || x.includes('(小程序)')) && x.includes(t));
    }""", program_title)

    if mini_created:
        return True, f"小程序已配置: {program_name} / {Path(cover_path).name}"

    if errors:
        return False, " / ".join(errors)
    return False, f"小程序主页面未生成素材卡片: {program_title}"


async def upload_step3_store_file(page, raw_path: str):
    """第3步上传门店：可选上传本地 xlsx/xls 文件。"""
    p = (raw_path or "").strip()
    if not p:
        return False, "未提供门店文件路径"
    path = Path(os.path.expanduser(p))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return False, f"门店文件不存在: {path}"
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return False, f"门店文件格式仅支持 xlsx/xls: {path.name}"

    locate_info = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const norm = (s) => (s || '').replace(/\\s+/g, '');
        const isUploadStoreText = (el) => {
            const t = norm((el && el.textContent) || '');
            return t === '上传门店' || t.includes('上传门店');
        };
        const markOnly = (el) => {
            if (!el) return false;
            el.setAttribute('data-step3-store-trigger', '1');
            const root = el.closest('.item, .el-form-item, .ant-form-item, .channel, .module, .card') || el.parentElement || el;
            if (root) root.setAttribute('data-step3-store-root', '1');
            // 就近定位与“上传门店”按钮关联的 file input，避免误命中小程序/图片上传控件
            let input =
                el.parentElement?.querySelector('input[type="file"]') ||
                el.closest('.item, .el-form-item, .ant-form-item, .channel, .module, .card')?.querySelector('input[type="file"]');
            if (!input && el.nextElementSibling && el.nextElementSibling.matches && el.nextElementSibling.matches('input[type="file"]')) {
                input = el.nextElementSibling;
            }
            if (!input && root) {
                input = root.querySelector('input[type="file"]');
            }
            if (input) {
                input.setAttribute('data-step3-store-input', '1');
                return true;
            }
            return true;
        };
        // 精确优先：命中第3步“上传门店”按钮样式
        const exactBtn = Array.from(document.querySelectorAll('button.el-button.el-button--primary.el-button--small.is-plain'))
            .find(b => isVisible(b) && norm(b.textContent || '').includes('上传门店'));
        if (exactBtn) {
            markOnly(exactBtn);
            return { ok: true, mode: 'exact_upload_store_button' };
        }
        // 优先：定位“分配方式/执行员工”字段附近的上传按钮（门店/员工），避免误点到其它上传入口。
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label')).filter(isVisible);
        for (const lb of labels) {
            const lt = norm(lb.textContent || '');
            if (!lt.includes('执行员工') && !lt.includes('分配方式')) continue;
            const item = lb.closest('.item, .el-form-item, .ant-form-item') || lb.parentElement;
            if (!item) continue;
            const container = item.parentElement || item;
            const candidates = Array.from(container.querySelectorAll('button.el-button, button, .el-button')).filter(isVisible);
            const btn = candidates.find(isUploadStoreText);
            if (!btn) continue;
            markOnly(btn);
            return { ok: true, mode: 'near_executor' };
        }

        // 社群页兜底：在“社群群发”区块内寻找上传门店按钮
        const roots = Array.from(document.querySelectorAll('div,section,.item,.el-form-item,.ant-form-item')).filter(isVisible);
        const sec = roots.find(n => norm(n.textContent || '').includes('社群群发'));
        if (sec) {
            const btn = Array.from(sec.querySelectorAll('button.el-button, button, .el-button')).filter(isVisible).find(isUploadStoreText);
            if (btn) {
                markOnly(btn);
                return { ok: true, mode: 'community_section' };
            }
        }

        // 兜底：全局命中上传门店按钮（不再扫 span/div 文本，避免误命中）
        const btns = Array.from(document.querySelectorAll('button.el-button, button')).filter(isVisible);
        const hit = btns.find(isUploadStoreText);
        if (!hit) return { ok: false, mode: 'not_found' };
        markOnly(hit);
        return { ok: true, mode: 'global_button' };
    }""")
    # 社群新页面兜底：即使找不到上传按钮，也可直接定位 file input 上传。
    if not locate_info:
        locate_info = {"ok": False, "mode": "unknown"}

    uploaded = False

    # 不点击上传按钮，避免弹系统文件选择器；直接走 file input 静默上传。

    # 优先：使用“上传门店”按钮关联的 file input
    try:
        if not uploaded:
            marked_input = page.locator('input[type="file"][data-step3-store-input="1"]').last
            if await marked_input.count() > 0:
                await marked_input.set_input_files(str(path))
                uploaded = True
    except Exception:
        uploaded = False

    try:
        if not uploaded:
            scoped_input = page.locator('[data-step3-store-root="1"] input[type="file"]').last
            if await scoped_input.count() > 0:
                await scoped_input.set_input_files(str(path))
                uploaded = True
    except Exception:
        uploaded = False

    if not uploaded:
        try:
            # 社群兜底：仅在“社群群发”区域内找 file input，避免误上传到小程序封面/图片
            scoped_input2 = page.locator(
                'xpath=//*[contains(normalize-space(.),"社群群发")]//input[@type="file"]'
            ).last
            if await scoped_input2.count() > 0:
                await scoped_input2.set_input_files(str(path))
                uploaded = True
        except Exception:
            uploaded = False

    if not uploaded:
        try:
            # 最后兜底：只接受可上传 Excel 的 input（accept 包含 xls/xlsx 或 accept 为空）
            scoped_input3 = page.locator(
                'input[type="file"][accept*="xls"], input[type="file"][accept*="xlsx"], input[type="file"]:not([accept])'
            ).last
            if await scoped_input3.count() > 0:
                await scoped_input3.set_input_files(str(path))
                uploaded = True
        except Exception:
            uploaded = False

    if not uploaded:
        return False, f"上传门店失败: {path.name}（入口模式={locate_info.get('mode','not_found')}）"

    # 第3步上传门店成功判定（强校验）：
    # 必须回读到“已上传: N家(>0)”或页面出现已上传文件名；仅提示文案不再放行。
    before_exec = await page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            const tags = Array.from(item.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                .map(n => (n.textContent || '').trim()).filter(Boolean);
            return tags.join(' ');
        }
        return '';
    }""")
    await asyncio.sleep(0.8)
    status_info = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const nodes = Array.from(document.querySelectorAll('.el-message, .el-message__content, .ant-message, .ant-message-notice-content, .ant-notification-notice, [role=\"alert\"], .toast, .message'))
            .filter(isVisible);
        const msg = nodes.map(n => (n.textContent || '').trim()).join(' | ');
        const norm = msg.replace(/\\s+/g, '');
        const hasFail = /(失败|错误|异常|无效|不支持|格式|超限|不能为空|未找到|校验|请重试)/.test(norm);
        const hasSuccess = /(成功|已上传|导入成功|上传成功)/.test(norm);
        return { msg, hasFail, hasSuccess };
    }""")
    after_exec = await page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            const tags = Array.from(item.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                .map(n => (n.textContent || '').trim()).filter(Boolean);
            return tags.join(' ');
        }
        return '';
    }""")
    upload_read = await page.evaluate("""(fileName) => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const norm = (s) => (s || '').replace(/\\s+/g, '');
        const roots = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item, section, div')).filter(isVisible);
        const sec = roots.find(n => norm(n.textContent || '').includes('社群群发'));
        const txt = norm((sec ? sec.textContent : document.body.textContent) || '');
        const fn = norm(fileName || '');
        const m = txt.match(/已上传[:：]?\\s*(\\d+)家/);
        const uploadedN = m ? Number(m[1] || 0) : 0;
        return {
            hasCount: uploadedN > 0,
            count: uploadedN,
            hasFileName: !!(fn && txt.includes(fn)),
            hasUploadedWord: txt.includes('已上传'),
        };
    }""", path.name)
    # 异步回写等待：最多约6秒
    for _ in range(20):
        if upload_read.get("hasCount") or upload_read.get("hasFileName"):
            break
        await asyncio.sleep(0.3)
        upload_read = await page.evaluate("""(fileName) => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const roots = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item, section, div')).filter(isVisible);
            const sec = roots.find(n => norm(n.textContent || '').includes('社群群发'));
            const txt = norm((sec ? sec.textContent : document.body.textContent) || '');
            const fn = norm(fileName || '');
            const m = txt.match(/已上传[:：]?\\s*(\\d+)家/);
            const uploadedN = m ? Number(m[1] || 0) : 0;
            return {
                hasCount: uploadedN > 0,
                count: uploadedN,
                hasFileName: !!(fn && txt.includes(fn)),
                hasUploadedWord: txt.includes('已上传'),
            };
        }""", path.name)
    changed = (before_exec or "").strip() != (after_exec or "").strip()
    if changed:
        print("      🧪 上传门店回读: 执行员工标签已变化")
    elif upload_read.get("hasCount"):
        print(f"      🧪 上传门店回读: 已上传 {upload_read.get('count', 0)} 家")
    elif upload_read.get("hasFileName"):
        print("      🧪 上传门店回读: 检测到上传文件名")
    elif (status_info or {}).get("hasSuccess"):
        print("      🧪 上传门店回读: 检测到成功提示")
    elif (status_info or {}).get("msg"):
        print(f"      🧪 上传门店消息: {(status_info or {}).get('msg','')}")
    if (status_info or {}).get("hasFail"):
        return False, f"上传门店失败提示: {(status_info or {}).get('msg','')}"
    # 会员通1对1/朋友圈页面经常不展示“已上传X家”或文件名，
    # 但上传成功后会直接反映到“执行员工”标签变化，视为成功。
    if not (upload_read.get("hasCount") or upload_read.get("hasFileName")):
        if changed:
            return True, f"门店文件已上传(执行员工标签变化): {path.name}"
        return False, "上传门店回读未命中（未检测到已上传家数或文件名）"
    return True, f"门店文件已上传: {path.name}"

def extract_api_code_message(text: str):
    """从接口响应体中提取 code/message。"""
    if not text:
        return "", ""
    try:
        data = json.loads(text)
    except Exception:
        return "", ""
    if isinstance(data, dict):
        code = data.get("code", data.get("status", ""))
        msg = data.get("msg", data.get("message", data.get("errorMsg", "")))
        return str(code), str(msg)
    return "", ""

def extract_review_link_from_text(text: str) -> str:
    """从文本中提取营销计划复核链接（优先 viewPlan，其次 editPlan）。"""
    if not text:
        return ""
    m_view = re.search(r"(https?://[^\s\"']+#/marketingPlan/viewPlan\?[^\s\"']+)", text)
    if m_view:
        return m_view.group(1).strip().rstrip(".,)")
    m_edit = re.search(r"(https?://[^\s\"']+#/marketingPlan/editPlan\?[^\s\"']+)", text)
    if m_edit:
        return m_edit.group(1).strip().rstrip(".,)")
    return ""

def summarize_content_fields_from_payload(post_data: str) -> str:
    """解析保存请求体，摘要短信/内容相关字段长度，便于定位长度=0原因。"""
    if not post_data:
        return ""
    try:
        obj = json.loads(post_data)
    except Exception:
        return ""

    def collect_strings(node, path=""):
        out = []
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                out.extend(collect_strings(v, p))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                p = f"{path}[{i}]"
                out.extend(collect_strings(v, p))
        elif isinstance(node, str):
            key = path.lower()
            if any(x in key for x in ["sms", "content", "message", "text", "msg"]):
                out.append((path, len(node.strip())))
        return out

    fields = collect_strings(obj)
    if not fields:
        return ""
    zero_fields = [f"{p}=0" for p, l in fields if l == 0][:8]
    non_zero_fields = [f"{p}={l}" for p, l in fields if l > 0][:8]
    req_items = obj.get("multiChannelItemReq", [])
    req_count = len(req_items) if isinstance(req_items, list) else 0
    return f"multiChannelItemReq={req_count}, zeroFields={zero_fields}, nonZeroSample={non_zero_fields}"

async def ensure_step3_saved(page, save_resp_task=None, before_url: str = "") -> bool:
    """确保第3步保存真正提交：处理确认弹窗并等待成功提示。"""
    async def _click_visible_confirm_once() -> bool:
        try:
            clicked = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const isConfirmText = (t) => {
                    const x = norm(t);
                    return (
                        x.includes('确定')
                        || x.includes('确 定')
                        || x.includes('提交')
                        || x === '是'
                    );
                };
                const modals = Array.from(document.querySelectorAll('.el-message-box, .el-message-box__wrapper, .el-dialog, .el-dialog__wrapper, .ant-modal, .ant-modal-wrap'))
                    .filter(isVisible);
                for (const m of modals) {
                    const btns = Array.from(m.querySelectorAll('button')).filter(isVisible);
                    // 优先主按钮
                    const primary = btns.find(b => /primary/.test((b.className || '').toLowerCase()) && isConfirmText(b.textContent || ''));
                    if (primary) { primary.click(); return true; }
                    const any = btns.find(b => isConfirmText(b.textContent || ''));
                    if (any) { any.click(); return true; }
                }
                return false;
            }""")
            return bool(clicked)
        except Exception:
            return False

    # 某些页面点击“保存”后会弹二次确认，先尝试确认。
    confirm_selectors = [
        '.el-message-box__btns button:has-text("确定")',
        '.el-message-box__btns button:has-text("确 定")',
        '.el-message-box__btns button:has-text("确认")',
        '.el-dialog__footer button:has-text("确定")',
        '.el-dialog__footer button:has-text("确 定")',
        '.el-dialog__footer button:has-text("确认")',
        '.el-dialog__footer button:has-text("提交")',
    ]
    for sel in confirm_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(force=True)
                await asyncio.sleep(0.2)
                break
        except:
            pass
    # 额外兜底：通用弹窗确认
    _ = await _click_visible_confirm_once()

    # 读取保存接口响应，输出 status/code/message 便于后端定位。
    api_diag = ""
    api_body = ""
    api_success = False
    api_hard_fail = False
    api_retryable_fail = False
    if save_resp_task is not None:
        try:
            resp = await asyncio.wait_for(save_resp_task, timeout=12)
            if resp is not None:
                status = 0
                try:
                    status = int(resp.status or 0)
                except Exception:
                    status = 0
                body = ""
                try:
                    body = await resp.text()
                except Exception:
                    body = ""
                api_body = body or ""
                code, msg = extract_api_code_message(api_body) if api_body else ("", "")
                post_data = ""
                try:
                    post_data = resp.request.post_data or ""
                except Exception:
                    try:
                        post_data = resp.request.post_data() or ""
                    except Exception:
                        post_data = ""
                post_excerpt = (post_data or "").replace("\n", " ").replace("\r", " ")
                if len(post_excerpt) > 220:
                    post_excerpt = post_excerpt[:220] + "..."
                api_diag = f"url={resp.url}, status={status}, code={code}, msg={msg}, reqLen={len(post_data or '')}, req={post_excerpt}"
                print(f"      🧪 保存接口响应: {api_diag}")
                # 仅作辅助：HTTP成功且未明确业务失败码，记为弱成功信号
                if 200 <= status < 300:
                    code_norm = str(code or "").strip().lower()
                    msg_norm = str(msg or "").strip().lower()
                    fail_hint = any(k in msg_norm for k in ["失败", "错误", "非法", "不能为空", "未通过", "重复"])
                    # 放宽：部分页面成功返回 code 非标准值，但只要 HTTP 2xx 且无失败语义即可视为保存成功信号
                    if not fail_hint:
                        api_success = True
                else:
                    api_hard_fail = True
                msg_norm = str(msg or "").strip().lower()
                if any(k in msg_norm for k in ["失败", "错误", "非法", "不能为空", "未通过", "重复"]):
                    api_hard_fail = True
                # 特例：朋友圈图片上传偶发接口并发限流（45033），可等待后重试保存一次
                if (
                    str(code or "").strip() == "45033"
                    or ("并发调用超过限制" in str(msg or ""))
                ):
                    api_retryable_fail = True
                    api_hard_fail = False
                content_diag = summarize_content_fields_from_payload(post_data)
                if content_diag:
                    print(f"      🧪 请求体内容字段诊断: {content_diag}")
        except asyncio.TimeoutError:
            pass
        except Exception:
            api_diag = ""

    # 等待成功提示；同屏失败提示也要拦截。
    # 兼容：成功提示很短暂，或仅有 success 类名无明确文案。
    for _ in range(40):  # 约 8s
        # 轮询期间持续处理可能延迟出现的确认弹窗
        _ = await _click_visible_confirm_once()
        try:
            toast_state = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const successNodes = Array.from(document.querySelectorAll(
                    '.el-message.el-message--success, .el-message--success, .ant-message-notice-success, [role="alert"].el-message--success'
                )).filter(isVisible);
                if (successNodes.length > 0) {
                    const txt = successNodes.map(n => norm(n.textContent)).filter(Boolean).join(' | ');
                    return { ok: true, err: false, msg: txt || '保存成功' };
                }

                const msgNodes = Array.from(document.querySelectorAll(
                    '.el-message__content, .ant-message-custom-content, .el-message-box__message, .ant-notification-notice-message, [role="alert"]'
                )).filter(isVisible);
                for (const n of msgNodes) {
                    const t = norm(n.textContent);
                    if (!t) continue;
                    if (/(成功|已保存|保存完成)/.test(t)) return { ok: true, err: false, msg: t };
                    if (/(失败|错误|重复|不能为空|请先|未通过)/.test(t)) return { ok: false, err: true, msg: t };
                }
                return { ok: false, err: false, msg: '' };
            }""")
            if toast_state and toast_state.get("ok"):
                msg = (toast_state.get("msg", "") or "").strip()
                if msg:
                    print(f"      ✅ 保存提示: {msg}")
                return True
            if toast_state and toast_state.get("err"):
                msg = (toast_state.get("msg", "") or "").strip()
                suffix = f" | {api_diag}" if api_diag else ""
                raise RuntimeError(f"保存失败提示: {msg}{suffix}")
        except RuntimeError:
            raise
        except Exception:
            pass
        await asyncio.sleep(0.2)

    # 接口已明确失败：直接中断（避免“页面无提示但后端返回失败”被误判成功）
    if api_hard_fail:
        suffix = f" | {api_diag}" if api_diag else ""
        raise RuntimeError(f"保存接口失败{suffix}")
    if api_retryable_fail:
        suffix = f" | {api_diag}" if api_diag else ""
        print(f"      ⚠️ 检测到可重试保存失败（上传并发限流）{suffix}")
        return False

    # 无 toast 时，回退到 URL / 接口判定：
    # 1) 优先识别真实跳转（viewPlan/editPlan/列表）
    # 2) 若URL未变，再参考接口弱成功信号
    try:
        current_url = page.url
    except Exception:
        current_url = ""
    moved_to_review = ("#/marketingPlan/editPlan?" in current_url) or ("#/marketingPlan/viewPlan?" in current_url)
    moved_to_list = ("limitList" in current_url) or ("marketingPlan/list" in current_url)
    moved = moved_to_review or moved_to_list
    # 兼容保存后标签页切换/当前页变 about:blank：扫描同一浏览器上下文的其它页URL
    context_urls = []
    try:
        for p in page.context.pages:
            try:
                u = p.url or ""
            except Exception:
                u = ""
            if u:
                context_urls.append(u)
    except Exception:
        context_urls = []
    if context_urls and ((not moved) or current_url.startswith("about:blank")):
        for u in context_urls:
            if ("#/marketingPlan/editPlan?" in u) or ("#/marketingPlan/viewPlan?" in u) or ("limitList" in u) or ("marketingPlan/list" in u):
                moved = True
                moved_to_review = ("#/marketingPlan/editPlan?" in u) or ("#/marketingPlan/viewPlan?" in u)
                moved_to_list = ("limitList" in u) or ("marketingPlan/list" in u)
                current_url = u
                print(f"      🧪 上下文页检测到已跳转URL: {u}")
                break
    if (not moved) and before_url:
        moved = current_url != before_url and (moved_to_review or moved_to_list)
    if (not moved) and api_success:
        moved = True
    if (not moved) and (api_diag or context_urls):
        if context_urls:
            print(f"      🧪 上下文页URL: {context_urls[:6]}")
    if (not moved) and api_diag:
        print(f"      ⚠️ 未检测到成功跳转，接口信息: {api_diag}")
    if not moved:
        await asyncio.sleep(0.6)
        try:
            save_btn_diag = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const inModal = (el) => !!el.closest('.el-dialog, .el-dialog__wrapper, .el-message-box, .ant-modal, .ant-modal-wrap');
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const out = [];
                const btns = Array.from(document.querySelectorAll('button')).filter(b => isVisible(b) && !inModal(b));
                for (const b of btns) {
                    const t = norm(b.textContent || '');
                    if (!t.includes('保存')) continue;
                    const r = b.getBoundingClientRect();
                    const p = b.parentElement || b.closest('div') || b;
                    const g = norm(p ? p.textContent || '' : '');
                    out.push({
                        text: t,
                        cls: (b.className || '').slice(0, 100),
                        top: Math.round(r.top),
                        left: Math.round(r.left),
                        groupHasCancel: g.includes('取消'),
                    });
                }
                return out.slice(0, 10);
            }""")
            if save_btn_diag:
                print(f"      🧪 保存按钮候选: {save_btn_diag}")
        except Exception:
            pass
        try:
            req_diag = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                const out = [];
                const labels = Array.from(document.querySelectorAll('label, .label, .el-form-item__label, .ant-form-item-label')).filter(isVisible);
                for (const lb of labels) {
                    const t = norm(lb.textContent || '');
                    if (!(t.includes('*') || t.includes('＊') || /required/i.test(lb.className || ''))) continue;
                    const item = lb.closest('.item, .el-form-item, .ant-form-item, .el-row, .ant-row') || lb.parentElement;
                    if (!item) continue;
                    const input = item.querySelector('input[type="text"], input:not([type]), textarea');
                    const ce = item.querySelector('[contenteditable="true"]');
                    let v = '';
                    if (input) v = (input.value || '').trim();
                    if (!v && ce) v = (ce.innerText || ce.textContent || '').trim();
                    out.push({ label: t.slice(0, 24), len: v.length, val: v.slice(0, 30) });
                }
                return out.slice(0, 20);
            }""")
            if req_diag:
                print(f"      🧪 必填字段回读: {req_diag}")
        except Exception:
            pass
        # 输出页面可见校验信息，帮助定位“为何点了保存但未提交”
        try:
            blockers = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                };
                const sels = [
                    '.el-form-item__error',
                    '.ant-form-item-explain-error',
                    '.el-message__content',
                    '.ant-message-custom-content',
                    '.el-message-box__message',
                    '.el-notification__content',
                    '.el-alert__content'
                ];
                const out = [];
                for (const s of sels) {
                    const nodes = document.querySelectorAll(s);
                    for (const n of nodes) {
                        const t = (n.textContent || '').trim();
                        if (t && isVisible(n)) out.push(t);
                    }
                }
                return Array.from(new Set(out)).slice(0, 5);
            }""")
            if blockers:
                raise RuntimeError(f"保存被页面校验拦截: {' | '.join(blockers)}")
        except RuntimeError:
            raise
        except Exception:
            pass

    # 社群页保存判定：不再无条件“弱成功放行”，避免后台未落库却误报成功。
    community_like = "addcommunityPlan" in (before_url or "")
    if (not moved) and community_like:
        # 仅输出诊断，不放行。必须命中：跳转 / 成功提示 / 接口成功。
        if str(current_url).startswith("about:blank"):
            print("      ⚠️ 社群页保存后URL异常切换为 about:blank，且未命中成功信号")
        else:
            print("      ⚠️ 社群页保存后未检测到跳转/成功提示/接口成功")
    if moved:
        # 优先从当前URL获取复核链接
        final_url = page.url
        if ("#/marketingPlan/editPlan?" in final_url) or ("#/marketingPlan/viewPlan?" in final_url):
            print(f"      🔗 复核链接: {final_url}")
        else:
            # 等待短暂跳转，兼容异步路由变更
            for _ in range(10):
                await asyncio.sleep(0.25)
                final_url = page.url
                if ("#/marketingPlan/editPlan?" in final_url) or ("#/marketingPlan/viewPlan?" in final_url):
                    print(f"      🔗 复核链接: {final_url}")
                    break
            else:
                # 再从接口响应体里兜底提取
                api_review_link = extract_review_link_from_text(api_body)
                if api_review_link:
                    print(f"      🔗 复核链接: {api_review_link}")
    return moved

async def click_step3_save_button(page) -> bool:
    """点击第3步主保存按钮（多策略兜底）。"""
    # 先尝试关闭可能遮挡按钮的浮层
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.1)
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.1)
    except:
        pass

    # 策略0：优先点击“取消 + 保存”同组按钮中的保存（底部主操作区）
    try:
        clicked_pair = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const inModal = (el) => !!el.closest('.el-dialog, .el-dialog__wrapper, .el-message-box, .ant-modal, .ant-modal-wrap');
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const btns = Array.from(document.querySelectorAll('button')).filter(b => isVisible(b) && !inModal(b));
            const cands = [];
            for (const b of btns) {
                const txt = norm(b.textContent || '');
                if (!txt.includes('保存')) continue;
                const parent = b.parentElement || b.closest('div') || b;
                const groupTxt = norm(parent ? parent.textContent || '' : '');
                if (!groupTxt.includes('取消') || !groupTxt.includes('保存')) continue;
                const r = b.getBoundingClientRect();
                cands.push({ btn: b, top: r.top, left: r.left });
            }
            if (!cands.length) return false;
            cands.sort((a, b) => b.top - a.top || b.left - a.left);
            const target = cands[0].btn;
            target.scrollIntoView({ block: 'center' });
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            target.click();
            return true;
        }""")
        if clicked_pair:
            print("      🧪 保存点击策略: js_cancel_save_pair")
            return True
    except Exception:
        pass

    # 策略1：优先点击页面中“最靠下、非弹窗”的保存按钮（最接近主操作区）
    try:
        clicked_bottom = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const inModal = (el) => !!el.closest('.el-dialog, .el-dialog__wrapper, .el-message-box, .ant-modal, .ant-modal-wrap');
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const btns = Array.from(document.querySelectorAll('button'))
                .filter(b => isVisible(b) && !inModal(b) && norm(b.textContent || '').includes('保存'));
            if (!btns.length) return false;
            btns.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
            const target = btns[0];
            target.scrollIntoView({ block: 'center' });
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            target.click();
            return true;
        }""")
        if clicked_bottom:
            print("      🧪 保存点击策略: js_bottom_non_modal_save")
            return True
    except Exception:
        pass

    # 策略2：Playwright 直接点击“最后一个可见主保存”
    try:
        save_btn = page.locator(
            "button.el-button.el-button--primary.el-button--small:visible"
        ).filter(has_text="保存").last
        if await save_btn.count() > 0:
            await save_btn.scroll_into_view_if_needed()
            await save_btn.click()
            print("      🧪 保存点击策略: playwright_last_primary_small")
            return True
    except Exception:
        pass

    # 策略3：JS 精准点击“页面主保存”（排除弹窗内按钮，优先含“取消+保存”组合）
    try:
        clicked_js = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const inModal = (el) => !!el.closest('.el-dialog, .el-dialog__wrapper, .el-message-box, .ant-modal, .ant-modal-wrap');
            const btns = Array.from(document.querySelectorAll('button.el-button.el-button--primary.el-button--small'));
            const candidates = [];
            for (const btn of btns) {
                const txt = (btn.textContent || '').trim();
                const rect = btn.getBoundingClientRect();
                if (!txt.includes('保存')) continue;
                if (!isVisible(btn)) continue;
                const group = btn.parentElement || btn.closest('div') || btn;
                const groupTxt = (group.textContent || '').replace(/\\s+/g, '');
                const hasCancelInGroup = groupTxt.includes('取消');
                const score =
                    (inModal(btn) ? -10000 : 0) +
                    (hasCancelInGroup ? 8000 : 0) +
                    rect.top + rect.left / 1000;
                candidates.push({ btn, score });
            }
            if (!candidates.length) return false;
            candidates.sort((a, b) => b.score - a.score);
            const target = candidates[0].btn;
            target.scrollIntoView({ block: 'center' });
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            target.click();
            return true;
        }""")
        if clicked_js:
            print("      🧪 保存点击策略: js_scored_primary_save")
            return True
    except Exception:
        pass

    # 策略4：兜底按文本点击最后一个“保存”
    try:
        btn = page.locator("button:visible").filter(has_text="保存").last
        if await btn.count() > 0:
            await btn.scroll_into_view_if_needed()
            await btn.click(force=True)
            print("      🧪 保存点击策略: playwright_last_text_save")
            return True
    except Exception:
        pass

    # 策略5：按文本兜底
    clicked = await click_button_with_text(page, "保存", exclude_text="取消")
    if clicked:
        print("      🧪 保存点击策略: generic_text_fallback")
    return clicked

async def copy_channel_info_if_available(page) -> bool:
    """若页面存在“渠道信息复制”入口，执行复制并确认。"""
    try:
        clicked = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const blocks = Array.from(document.querySelectorAll('div,section')).filter(n => (n.textContent || '').includes('渠道信息复制'));
            for (const b of blocks) {
                const btn = Array.from(b.querySelectorAll('button')).find(x => isVisible(x) && (x.textContent || '').includes('复制'));
                if (btn) { btn.click(); return true; }
            }
            return false;
        }""")
        if not clicked:
            return False
        await asyncio.sleep(0.4)
        await click_button_with_text(page, "确定")
        await asyncio.sleep(0.3)
        return True
    except Exception:
        return False

async def read_step3_sms_text(page) -> str:
    """读取第3步短信内容编辑器文本（用于保存前后回读）。"""
    try:
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
            for (const it of items) {
                const txt = (it.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('短信内容')) continue;
                const ed = Array.from(it.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]'))
                    .find(isVisible);
                if (ed) {
                    ed.setAttribute('data-step3-sms-target', '1');
                    return true;
                }
            }
            return false;
        }""")
        if not ok:
            return ""
        editable = page.locator('[data-step3-sms-target="1"]').first
        if await editable.count() == 0:
            return ""
        txt = (await editable.inner_text()) or ""
        return txt.strip()
    except Exception:
        return ""

async def read_step3_send_text(page) -> str:
    """读取第3步发送内容编辑器文本。"""
    try:
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
            for (const it of items) {
                const txt = (it.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('发送内容')) continue;
                const ed = Array.from(it.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]'))
                    .find(isVisible);
                if (ed) {
                    ed.setAttribute('data-step3-send-target', '1');
                    return true;
                }
            }
            return false;
        }""")
        if not ok:
            return ""
        editable = page.locator('[data-step3-send-target="1"]').first
        if await editable.count() == 0:
            return ""
        txt = (await editable.inner_text()) or ""
        return txt.strip()
    except Exception:
        return ""

async def set_step3_distribution_mode(page, mode_text: str = "指定门店分配", section_hint: str = "") -> bool:
    """第3步分配方式：点击单选文本。"""
    mode_text = (mode_text or "").strip()
    aliases = [mode_text] if mode_text else []
    if mode_text == "导入门店":
        aliases = ["导入门店", "选中门店"]
    elif mode_text == "选中门店":
        aliases = ["选中门店", "导入门店"]
    elif mode_text == "按条件筛选客户":
        aliases = ["按条件筛选客户", "按条件筛选客户群"]
    elif mode_text == "按条件筛选客户群":
        aliases = ["按条件筛选客户群", "按条件筛选客户"]

    # 先走 JS 精确命中分配方式组内 radio（避免点到同名文案/隐藏副本）
    clicked = await page.evaluate(
        """(payload) => {
            const modeTexts = payload?.modeTexts || [];
            const hint = (payload?.sectionHint || '').replace(/\\s+/g, '');
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const fire = (el) => {
                if (!el) return false;
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(t => {
                    el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            const targets = (modeTexts || []).map(x => (x || '').replace(/\\s+/g, ''));
            const groups = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item, .channel, section, div')).filter(isVisible);
            let group = null;
            if (hint) {
                group = groups.find(g => {
                    const t = (g.textContent || '').replace(/\\s+/g, '');
                    return t.includes(hint) && t.includes('分配方式');
                });
                if (!group) {
                    group = groups.find(g => {
                        const t = (g.textContent || '').replace(/\\s+/g, '');
                        return t.includes(hint) && t.includes('导入门店') && (t.includes('按条件筛选客户') || t.includes('按条件筛选客户群'));
                    });
                }
            }
            if (!group) {
                group = groups.find(g => ((g.textContent || '').replace(/\\s+/g, '')).includes('分配方式')) || document;
            }
            // ElementUI radio
            const radios = Array.from(group.querySelectorAll('label.el-radio, .ant-radio-wrapper')).filter(isVisible);
            for (const rb of radios) {
                const txt = (rb.textContent || '').replace(/\\s+/g, '');
                if (!txt) continue;
                for (const t of targets) {
                    if (!t) continue;
                    if (txt.includes(t)) {
                        const inner = rb.querySelector('.el-radio__inner, .ant-radio-input, .el-radio__label');
                        if (inner) fire(inner);
                        fire(rb);
                        return true;
                    }
                }
            }
            // 兜底：按文案命中可见 label/span
            const fallback = Array.from(group.querySelectorAll('label, span, div, button')).filter(isVisible);
            for (const el of fallback) {
                const txt = (el.textContent || '').replace(/\\s+/g, '');
                for (const t of targets) {
                    if (!t) continue;
                    if (txt.includes(t)) {
                        const lb = el.closest('label.el-radio, .ant-radio-wrapper, label') || el;
                        fire(lb);
                        return true;
                    }
                }
            }
            return false;
        }""",
        {"modeTexts": aliases, "sectionHint": section_hint or ""}
    )
    if not clicked:
        return False
    # 回读必须命中选中态，否则视为失败（不再放行）
    async def _read_selected():
        return await page.evaluate("""(hintRaw) => {
        const hint = (hintRaw || '').replace(/\\s+/g, '');
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const groups = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item, .channel, section, div')).filter(isVisible);
        let group = null;
        if (hint) {
            group = groups.find(g => {
                const t = (g.textContent || '').replace(/\\s+/g, '');
                return t.includes(hint) && t.includes('分配方式');
            });
            if (!group) {
                group = groups.find(g => {
                    const t = (g.textContent || '').replace(/\\s+/g, '');
                    return t.includes(hint) && t.includes('导入门店') && (t.includes('按条件筛选客户') || t.includes('按条件筛选客户群'));
                });
            }
        }
        if (!group) {
            group = groups.find(g => ((g.textContent || '').replace(/\\s+/g, '')).includes('分配方式')) || document;
        }
        const checkedEl = group.querySelector('.el-radio.is-checked, .ant-radio-wrapper-checked');
        if (checkedEl) return (checkedEl.textContent || '').replace(/\\s+/g, '');
        const radios = Array.from(group.querySelectorAll('label.el-radio, .ant-radio-wrapper')).filter(isVisible);
        for (const rb of radios) {
            const cls = rb.className || '';
            if (cls.includes('is-checked') || cls.includes('ant-radio-wrapper-checked')) {
                return (rb.textContent || '').replace(/\\s+/g, '');
            }
            const input = rb.querySelector('input[type="radio"]');
            if (input && input.checked) {
                return (rb.textContent || '').replace(/\\s+/g, '');
            }
        }
        return '';
    }""", section_hint or "")
    await asyncio.sleep(0.25)
    selected = await _read_selected()
    selected = (selected or "").strip()
    alias_norm = [(x or "").replace(" ", "") for x in aliases]
    if any(a and (a in selected) for a in alias_norm):
        return True
    # 一次重试点击
    retry_clicked = await page.evaluate("""(payload) => {
        const modeTexts = payload?.modeTexts || [];
        const hint = (payload?.sectionHint || '').replace(/\\s+/g, '');
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const targets = (modeTexts || []).map(x => (x || '').replace(/\\s+/g, ''));
        let root = document;
        if (hint) {
            const blocks = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item, .channel, section, div')).filter(isVisible);
            const hit = blocks.find(b => {
                const t = (b.textContent || '').replace(/\\s+/g, '');
                return t.includes(hint) && t.includes('分配方式');
            });
            if (hit) root = hit;
            if (!hit) {
                const hit2 = blocks.find(b => {
                    const t = (b.textContent || '').replace(/\\s+/g, '');
                    return t.includes(hint) && t.includes('导入门店') && (t.includes('按条件筛选客户') || t.includes('按条件筛选客户群'));
                });
                if (hit2) root = hit2;
            }
        }
        const radios = Array.from(root.querySelectorAll('label.el-radio, .ant-radio-wrapper')).filter(isVisible);
        for (const rb of radios) {
            const txt = (rb.textContent || '').replace(/\\s+/g, '');
            if (!txt) continue;
            for (const t of targets) {
                if (!t) continue;
                if (txt.includes(t)) {
                    const inner = rb.querySelector('.el-radio__inner, .ant-radio-input');
                    if (inner && typeof inner.click === 'function') inner.click();
                    if (typeof rb.click === 'function') rb.click();
                    return true;
                }
            }
        }
        return false;
    }""", {"modeTexts": aliases, "sectionHint": section_hint or ""})
    if retry_clicked:
        await asyncio.sleep(0.25)
        selected = (await _read_selected() or "").strip()
        if any(a and (a in selected) for a in alias_norm):
            return True
    # 全局兜底：若页面任一已选radio文本命中目标，也视为成功
    try:
        selected_global = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const checked = Array.from(document.querySelectorAll('.el-radio.is-checked, .ant-radio-wrapper-checked'))
                .filter(isVisible)
                .map(n => (n.textContent || '').replace(/\\s+/g, ''))
                .filter(Boolean);
            return checked.join(' ');
        }""")
        if any(a and (a in (selected_global or "")) for a in alias_norm):
            return True
    except Exception:
        pass
    return False

async def switch_step3_channel(page, channel_text: str) -> bool:
    """第3步切换渠道（如：会员通-发客户消息 / 会员通-发客户朋友圈）。"""
    switched = await page.evaluate(
        """(channelText) => {
            const normalize = (s) => (s || '').replace(/\\s+/g, '').replace(/[-—]/g, '');
            const target = normalize(channelText);
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const nodes = Array.from(document.querySelectorAll('button, a, span, div, li, label')).filter(isVisible);
            const fireClick = (el) => {
                if (!el) return false;
                ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(type => {
                    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            for (const n of nodes) {
                const t = normalize(n.textContent || '');
                if (!t) continue;
                if (t.includes(target)) {
                    const clickable = n.closest('button,a,[role="tab"],li,div,span') || n;
                    fireClick(clickable);
                    return true;
                }
            }
            return false;
        }""",
        channel_text
    )
    if switched:
        await asyncio.sleep(0.5)
    return bool(switched)

async def fill_step3_executor(page, raw_values: str, include_franchise: bool = False) -> bool:
    """第3步执行员工：按级联面板（全国->大区->省区/门店）多选。"""
    targets = [normalize_area_alias(x) for x in split_multi_values(raw_values)]
    if include_franchise:
        ext = []
        for t in targets:
            tt = (t or '').strip()
            if not tt:
                continue
            ext.append(tt)
            if '加盟' not in tt:
                ext.append(normalize_area_alias(f'{tt}加盟'))
        seen = set()
        targets = [x for x in ext if not (x in seen or seen.add(x))]
    if not targets:
        return True

    # 兼容小窗口/缩放导致的“元素在视口外”问题
    try:
        await page.set_viewport_size({"width": 1600, "height": 950})
    except Exception:
        pass
    try:
        await page.evaluate("""() => {
            try {
                document.documentElement.style.zoom = '100%';
                document.body.style.zoom = '100%';
            } catch (e) {}
            try { window.scrollTo(0, 0); } catch (e) {}
        }""")
    except Exception:
        pass

    opened = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            if (!isVisible(item)) continue;
            const input = item.querySelector('input.el-input__inner[placeholder*="请选择"], input[placeholder*="请选择"], .el-cascader input.el-input__inner');
            if (input && isVisible(input)) {
                input.click();
                return true;
            }
        }
        return false;
    }""")
    if not opened:
        return False
    await asyncio.sleep(0.3)

    # 先清空字段内已有标签，避免营销模板默认区域残留
    await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            if (!isVisible(item)) continue;
            const closes = Array.from(item.querySelectorAll('.el-tag__close'));
            for (const c of closes) c.click();
            const clearIcons = Array.from(item.querySelectorAll('.el-input__suffix .el-icon-circle-close, .el-input__icon.el-icon-circle-close'))
                .filter(isVisible);
            for (const ci of clearIcons) {
                if ((ci.getAttribute('class') || '').includes('is-show-close')) ci.click();
                else ci.click();
            }
            const input = item.querySelector('input.el-input__inner[placeholder*="请选择"], input[placeholder*="请选择"], .el-cascader input.el-input__inner');
            if (input && isVisible(input)) input.click();
            return;
        }
    }""")
    await asyncio.sleep(0.25)

    async def reopen_executor_panel():
        await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
            for (const label of labels) {
                const txt = (label.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('执行员工')) continue;
                const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
                if (!item) continue;
                if (!isVisible(item)) continue;
                const input = item.querySelector('input.el-input__inner[placeholder*="请选择"], input[placeholder*="请选择"], .el-cascader input.el-input__inner');
                if (input && isVisible(input)) {
                    input.click();
                    return;
                }
            }
        }""")
        await page.locator(".el-cascader-panel:visible").last.wait_for(timeout=5000)
        await asyncio.sleep(0.15)

    def area_name_match(txt: str, target: str) -> bool:
        a = (txt or "").strip()
        b = (target or "").strip()
        if not a or not b:
            return False
        if a == b or b in a or a in b:
            return True
        # 宽松匹配：去后缀后按核心地名匹配（兼容“肇庆一营运区”等变体）
        def simplify(s: str) -> str:
            return (
                (s or "")
                .replace("加盟", "")
                .replace("营运区", "")
                .replace("省区", "")
                .replace("大区", "")
                .replace("片区", "")
                .replace("门店", "")
                .replace("店", "")
                .replace(" ", "")
                .strip()
            )
        sa = simplify(a)
        sb = simplify(b)
        if not sa or not sb:
            return False
        return (sb in sa) or (sa in sb)

    async def expand_in_menu(menu_index: int, target: str) -> bool:
        menu = page.locator(".el-cascader-panel:visible").last.locator(".el-cascader-menu").nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        target_has_join = ("加盟" in (target or ""))
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            txt_has_join = ("加盟" in txt)
            if target_has_join != txt_has_join:
                continue
            # 兼容简称/全称（如 广州一 <-> 广州一营运区）双向匹配
            if not area_name_match(txt, target):
                continue
            try:
                await node.scroll_into_view_if_needed()
            except Exception:
                pass
            postfix = node.locator(".el-cascader-node__postfix").first
            if await postfix.count() > 0:
                await postfix.click(force=True)
            else:
                # 避免点击label触发勾选（尤其“全国”），没有展开箭头时不执行展开点击。
                return False
            await asyncio.sleep(0.1)
            return True
        return False

    async def get_menu_checked_state(menu_index: int, target: str) -> str:
        menu = page.locator(".el-cascader-panel:visible").last.locator(".el-cascader-menu").nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        if count == 0:
            return "panel_not_found"
        target_has_join = ("加盟" in (target or ""))
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            txt_has_join = ("加盟" in txt)
            if target_has_join != txt_has_join:
                continue
            if not area_name_match(txt, target):
                continue
            cb = node.locator(".el-checkbox__input").first
            cb_original = node.locator("input.el-checkbox__original").first
            if await cb.count() == 0 and await cb_original.count() == 0:
                return "missing"
            node_cls = (await node.get_attribute("class")) or ""
            cb_cls = (await cb.get_attribute("class")) if await cb.count() > 0 else ""
            checked = False
            if await cb_original.count() > 0:
                try:
                    checked = await cb_original.is_checked()
                except Exception:
                    checked = False
            if not checked:
                checked = ("in-checked-path" in node_cls) or ("is-checked" in (cb_cls or ""))
            return "checked" if checked else "unchecked"
        return "not_found"

    async def toggle_in_menu(menu_index: int, target: str) -> bool:
        menu = page.locator(".el-cascader-panel:visible").last.locator(".el-cascader-menu").nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        target_has_join = ("加盟" in (target or ""))
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            txt_has_join = ("加盟" in txt)
            if target_has_join != txt_has_join:
                continue
            if not area_name_match(txt, target):
                continue
            cb = node.locator(".el-checkbox__input").first
            cb_inner = node.locator(".el-checkbox__inner").first
            cb_original = node.locator("input.el-checkbox__original").first
            if await cb.count() == 0 and await cb_inner.count() == 0 and await cb_original.count() == 0:
                return False
            click_target = cb_inner if await cb_inner.count() > 0 else (cb_original if await cb_original.count() > 0 else cb)
            try:
                await click_target.scroll_into_view_if_needed()
            except Exception:
                pass
            await click_target.click(force=True)
            await asyncio.sleep(0.1)
            return True
        return False

    async def check_in_menu(menu_index: int, target: str) -> bool:
        menu = page.locator(".el-cascader-panel:visible").last.locator(".el-cascader-menu").nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        target_has_join = ("加盟" in (target or ""))
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            txt_has_join = ("加盟" in txt)
            if target_has_join != txt_has_join:
                continue
            if not area_name_match(txt, target):
                continue
            checkbox = node.locator(".el-checkbox__input").first
            cb_inner = node.locator(".el-checkbox__inner").first
            cb_original = node.locator("input.el-checkbox__original").first
            if await checkbox.count() == 0 and await cb_inner.count() == 0 and await cb_original.count() == 0:
                continue
            click_target = cb_inner if await cb_inner.count() > 0 else (cb_original if await cb_original.count() > 0 else checkbox)
            try:
                await click_target.scroll_into_view_if_needed()
            except Exception:
                pass
            node_cls = (await node.get_attribute("class")) or ""
            cb_cls = (await checkbox.get_attribute("class")) if await checkbox.count() > 0 else ""
            checked = False
            if await cb_original.count() > 0:
                try:
                    checked = await cb_original.is_checked()
                except Exception:
                    checked = False
            if not checked:
                checked = ("in-checked-path" in node_cls) or ("is-checked" in (cb_cls or ""))
            if not checked:
                await click_target.click(force=True)
                await asyncio.sleep(0.08)
            return True
        return False

    async def js_pick_target_by_path(path: list[str]) -> bool:
        """在页面内按路径展开并勾选末级节点（更稳定，避免 locator 误中/视口抖动）。"""
        if not path:
            return False
        try:
            return bool(await page.evaluate("""(path) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const fire = (el) => {
                    if (!el) return false;
                    ['pointerdown','mousedown','mouseup','click'].forEach(tp => {
                        el.dispatchEvent(new MouseEvent(tp, { bubbles: true, cancelable: true, view: window }));
                    });
                    if (typeof el.click === 'function') el.click();
                    return true;
                };
                const panel = Array.from(document.querySelectorAll('.el-cascader-panel')).filter(isVisible).pop();
                if (!panel) return false;
                const menus = Array.from(panel.querySelectorAll('.el-cascader-menu'));
                if (!menus.length) return false;

                const findNode = (menuIdx, target, preferJoin) => {
                    const menu = menus[menuIdx];
                    if (!menu) return null;
                    const nodes = Array.from(menu.querySelectorAll('.el-cascader-node')).filter(isVisible);
                    let best = null, score = -1;
                    const tgt = norm(target);
                    for (const n of nodes) {
                        const lb = n.querySelector('.el-cascader-node__label');
                        const txt = norm(lb ? lb.textContent : n.textContent || '');
                        if (!txt) continue;
                        const hasJoin = txt.includes('加盟');
                        if (preferJoin !== null && hasJoin !== preferJoin) continue;
                        let s = -1;
                        if (txt === tgt) s = 3;
                        else if (txt.includes(tgt)) s = 2;
                        else if (tgt.includes(txt)) s = 1;
                        if (s > score) { score = s; best = n; }
                    }
                    return score >= 0 ? best : null;
                };

                const ensureExpanded = (node) => {
                    if (!node) return false;
                    const exp = node.querySelector('.el-cascader-node__postfix');
                    if (!exp) return false;
                    return fire(exp);
                };

                const pathNorm = path.map(x => String(x || '').trim()).filter(Boolean);
                if (!pathNorm.length) return false;
                for (let i = 0; i < pathNorm.length; i++) {
                    const seg = pathNorm[i];
                    const preferJoin = seg.includes('加盟');
                    const menuIdx = i + 1; // 0 是“全国”
                    const node = findNode(menuIdx, seg, preferJoin);
                    if (!node) return false;
                    node.scrollIntoView({ block: 'center' });
                    if (i < pathNorm.length - 1) {
                        ensureExpanded(node);
                        continue;
                    }
                    // 末级：勾选
                    const input = node.querySelector('input.el-checkbox__original');
                    const inner = node.querySelector('.el-checkbox__inner');
                    const checked = !!(input && input.checked);
                    if (!checked) {
                        if (!(fire(inner) || fire(input) || fire(node))) return false;
                    }
                    return true;
                }
                return false;
            }""", path))
        except Exception:
            return False

    # 先按业务规则双击“全国”：第一次全选，第二次清空。
    await reopen_executor_panel()
    nation_before = await get_menu_checked_state(0, "全国")
    first_ok = await toggle_in_menu(0, "全国")
    nation_after_first = await get_menu_checked_state(0, "全国")
    second_ok = await toggle_in_menu(0, "全国")
    nation_after_second = await get_menu_checked_state(0, "全国")
    # 强校验：双击后若“全国”仍为选中，补点一次确保清空。
    if nation_after_second == "checked":
        _ = await toggle_in_menu(0, "全国")
        await asyncio.sleep(0.15)
        nation_after_second = await get_menu_checked_state(0, "全国")
    if nation_after_second != "unchecked":
        # DOM 兜底：直接对“全国”节点做最多3轮取消，避免残留全选污染后续选择。
        nation_after_second = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const panel = Array.from(document.querySelectorAll('.el-cascader-panel')).filter(isVisible).pop();
            if (!panel) return 'panel_not_found';
            const menu0 = panel.querySelector('.el-cascader-menu');
            if (!menu0) return 'panel_not_found';
            const rows = Array.from(menu0.querySelectorAll('.el-cascader-node')).filter(isVisible);
            const nation = rows.find(r => ((r.querySelector('.el-cascader-node__label')?.textContent || '').trim()) === '全国');
            if (!nation) return 'not_found';
            const input = nation.querySelector('input.el-checkbox__original');
            const inner = nation.querySelector('.el-checkbox__inner');
            const fire = (el) => {
                if (!el) return false;
                ['pointerdown','mousedown','mouseup','click'].forEach(tp => {
                    el.dispatchEvent(new MouseEvent(tp, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            const isChecked = () => {
                if (input) return !!input.checked;
                const nc = nation.getAttribute('class') || '';
                const cc = nation.querySelector('.el-checkbox__input')?.getAttribute('class') || '';
                return nc.includes('in-checked-path') || cc.includes('is-checked');
            };
            for (let i = 0; i < 3; i++) {
                if (!isChecked()) return 'unchecked';
                fire(inner) || fire(input) || fire(nation);
            }
            return isChecked() ? 'checked' : 'unchecked';
        }""")
    print(
        "      🧪 全国双击清空: "
        f"before={nation_before}, firstClick={first_ok}, afterFirst={nation_after_first}, "
        f"secondClick={second_ok}, afterSecond={nation_after_second}"
    )
    await asyncio.sleep(0.1)
    # 再点全国展开大区列（快路径，避免反复等待）
    _ = await expand_in_menu(0, "全国")

    selected = {t: False for t in targets}
    # 路径提示优先：确保先展开到“省区”再勾选“营运区/加盟营运区”
    area_path_hints = {
        "黑龙江省区": ["北方大区", "黑龙江省区"],
        "黑龙江省区加盟": ["北方大区加盟", "黑龙江省区加盟"],
        "武汉营运区": ["华中大区", "湖北省区", "武汉营运区"],
        "武汉营运区加盟": ["华中大区加盟", "湖北省区加盟", "武汉营运区加盟"],
        "广佛省区": ["华南大区", "广佛省区"],
        "广佛省区加盟": ["华南大区加盟", "广佛省区加盟"],
        "大郑州营运区": ["西北大区", "河南省区", "大郑州营运区"],
        "大郑州营运区加盟": ["西北大区加盟", "河南省区加盟", "大郑州营运区加盟"],
        "肇庆营运区": ["华南大区", "广佛省区", "肇庆营运区"],
        "肇庆营运区加盟": ["华南大区加盟", "广佛省区加盟", "肇庆营运区加盟"],
        "云浮营运区": ["华南大区", "广佛省区", "云浮营运区"],
        "云浮营运区加盟": ["华南大区加盟", "广佛省区加盟", "云浮营运区加盟"],
        # 广佛省区常用简称（从文件主消费营运区复用到执行员工）
        "广州一营运区": ["华南大区", "广佛省区", "广州一营运区"],
        "广州一营运区加盟": ["华南大区加盟", "广佛省区加盟", "广州一营运区加盟"],
        "广州二营运区": ["华南大区", "广佛省区", "广州二营运区"],
        "广州二营运区加盟": ["华南大区加盟", "广佛省区加盟", "广州二营运区加盟"],
        "花都营运区": ["华南大区", "广佛省区", "花都营运区"],
        "花都营运区加盟": ["华南大区加盟", "广佛省区加盟", "花都营运区加盟"],
        "番禺营运区": ["华南大区", "广佛省区", "番禺营运区"],
        "番禺营运区加盟": ["华南大区加盟", "广佛省区加盟", "番禺营运区加盟"],
        "佛山营运区": ["华南大区", "广佛省区", "佛山营运区"],
        "佛山营运区加盟": ["华南大区加盟", "广佛省区加盟", "佛山营运区加盟"],
        "顺德营运区": ["华南大区", "广佛省区", "顺德营运区"],
        "顺德营运区加盟": ["华南大区加盟", "广佛省区加盟", "顺德营运区加盟"],
        "江门营运区": ["华南大区", "广佛省区", "江门营运区"],
        "江门营运区加盟": ["华南大区加盟", "广佛省区加盟", "江门营运区加盟"],
    }

    for t in targets:
        path = area_path_hints.get(t)
        if not path:
            continue
        # 快路径：保持面板一次展开，连续点选，避免每个目标 reopen 带来的卡顿。
        if await js_pick_target_by_path(path):
            selected[t] = True
            continue
        for i, seg in enumerate(path):
            menu_idx = i + 1
            if i < len(path) - 1:
                await expand_in_menu(menu_idx, seg)
            else:
                for idx in (menu_idx, 2, 3, 4):
                    if await check_in_menu(idx, seg):
                        selected[t] = (await get_menu_checked_state(idx, seg)) == "checked"
                        if not selected[t]:
                            selected[t] = True
                        break

    if all(selected.values()):
        selected_labels = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const panel = Array.from(document.querySelectorAll('.el-cascader-panel')).find(isVisible);
            if (!panel) return [];
            const checked = Array.from(panel.querySelectorAll('.el-checkbox__input.is-checked'));
            return checked.map(c => {
                const node = c.closest('.el-cascader-node');
                const label = node ? node.querySelector('.el-cascader-node__label') : null;
                return (label?.textContent || '').trim();
            }).filter(Boolean);
        }""")
        print(f"      🧪 执行员工面板勾选节点: {selected_labels}")
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.15)
        readback = await page.evaluate("""() => {
            const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
            for (const label of labels) {
                const txt = (label.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('执行员工')) continue;
                const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
                if (!item) continue;
                const input = item.querySelector('input.el-input__inner');
                const tags = Array.from(item.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                    .map(n => (n.textContent || '').trim())
                    .filter(Boolean);
                return [input ? (input.value || '').trim() : '', ...tags].join(' ');
            }
            return '';
        }""")
        for t in targets:
            if t in readback:
                selected[t] = True
        print(f"      🧪 执行员工回读文本: {readback}")
        return all(selected.values())

    region_targets = [t for t in targets if "大区" in t]
    province_targets = [t for t in targets if "省区" in t or "营运区" in t or "店" in t]

    # 先选大区目标（例如西北大区）
    for rt in region_targets:
        if await check_in_menu(1, rt):
            selected[rt] = (await get_menu_checked_state(1, rt)) == "checked" or selected.get(rt, False)

    # 再跨大区选省区目标（例如湖北省区）
    region_nodes = page.locator(".el-cascader-panel:visible").last.locator(".el-cascader-menu").nth(1).locator(".el-cascader-node .el-cascader-node__label")
    region_count = await region_nodes.count()
    region_names = []
    for i in range(region_count):
        txt = ((await region_nodes.nth(i).text_content()) or "").strip()
        if "大区" in txt:
            region_names.append(txt)

    for region in region_names:
        await expand_in_menu(1, region)
        for pt in province_targets:
            if selected.get(pt):
                continue
            if await check_in_menu(2, pt):
                selected[pt] = (await get_menu_checked_state(2, pt)) == "checked" or selected.get(pt, False)

    # 深层兜底：仅对未命中目标再按路径重试一轮（避免慢速反复展开）
    unresolved = [k for k, v in selected.items() if not v]
    for t in unresolved:
        path = area_path_hints.get(t)
        if not path:
            continue
        for i, seg in enumerate(path):
            menu_idx = i + 1
            if i < len(path) - 1:
                await expand_in_menu(menu_idx, seg)
            else:
                for idx in (menu_idx, 2, 3, 4):
                    if await check_in_menu(idx, seg):
                        selected[t] = (await get_menu_checked_state(idx, seg)) == "checked" or selected.get(t, False)
                        break

    # 通用叶子兜底：不依赖固定层级，按“可见节点文本”直接勾选；若未出现则自动展开后再试。
    unresolved = [k for k, v in selected.items() if not v]
    for t in unresolved:
        ok = await page.evaluate("""(target) => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const fire = (el) => {
                if (!el) return false;
                ['pointerdown','mousedown','mouseup','click'].forEach(tp => {
                    el.dispatchEvent(new MouseEvent(tp, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            const tgt = String(target || '').trim();
            const tgtNorm = norm(tgt);
            const needJoin = tgtNorm.includes('加盟');
            const simple = tgtNorm.replace('营运区', '').replace('省区', '').replace('大区', '').replace('加盟', '');
            const panel = Array.from(document.querySelectorAll('.el-cascader-panel')).filter(isVisible).pop();
            if (!panel) return false;

            const pickVisible = () => {
                const nodes = Array.from(panel.querySelectorAll('.el-cascader-node')).filter(isVisible);
                let candidate = null;
                let score = -1;
                for (const node of nodes) {
                    const lb = node.querySelector('.el-cascader-node__label');
                    const txt = norm(lb ? lb.textContent : '');
                    if (!txt) continue;
                    const hasJoin = txt.includes('加盟');
                    if (hasJoin !== needJoin) continue;
                    let s = -1;
                    if (txt === tgtNorm) s = 4;
                    else if (txt.includes(tgtNorm)) s = 3;
                    else if (tgtNorm.includes(txt)) s = 2;
                    else if (simple && txt.includes(simple)) s = 1;
                    if (s > score) { score = s; candidate = node; }
                }
                if (!candidate || score < 0) return false;
                const input = candidate.querySelector('input.el-checkbox__original');
                const inner = candidate.querySelector('.el-checkbox__inner');
                const checked = !!(input && input.checked);
                if (!checked) fire(inner) || fire(input) || fire(candidate);
                return true;
            };

            if (pickVisible()) return true;

            // 展开一轮后再尝试
            const expanders = Array.from(panel.querySelectorAll('.el-cascader-node__postfix')).filter(isVisible);
            for (const exp of expanders) fire(exp);
            return pickVisible();
        }""", t)
        if ok:
            selected[t] = True

    selected_labels = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
        };
        const panel = Array.from(document.querySelectorAll('.el-cascader-panel')).find(isVisible);
        if (!panel) return [];
        const checked = Array.from(panel.querySelectorAll('.el-checkbox__input.is-checked'));
        return checked.map(c => {
            const node = c.closest('.el-cascader-node');
            const label = node ? node.querySelector('.el-cascader-node__label') : null;
            return (label?.textContent || '').trim();
        }).filter(Boolean);
    }""")
    print(f"      🧪 执行员工面板勾选节点: {selected_labels}")

    await page.keyboard.press("Escape")
    await asyncio.sleep(0.2)

    # 回读校验：限定在“执行员工”字段容器内。
    readback = await page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            const input = item.querySelector('input.el-input__inner');
            const tags = Array.from(item.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                .map(n => (n.textContent || '').trim())
                .filter(Boolean);
            return [input ? (input.value || '').trim() : '', ...tags].join(' ');
        }
        return '';
    }""")
    for t in targets:
        if t in readback:
            selected[t] = True

    print(f"      🧪 执行员工目标命中: {selected}")
    print(f"      🧪 执行员工回读文本: {readback}")
    if all(selected.values()):
        return True

    # 二级判定（防误杀）：页面已存在执行员工回读且未出现该字段校验报错时放行。
    try:
        loose_ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
            for (const label of labels) {
                const txt = (label.textContent || '').replace(/\\s+/g, '');
                if (!txt.includes('执行员工')) continue;
                const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
                if (!item || !isVisible(item)) continue;
                const input = item.querySelector('input.el-input__inner, input[placeholder*="请选择"]');
                const inputVal = ((input && input.value) || '').trim();
                const tags = Array.from(item.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                    .map(n => (n.textContent || '').trim())
                    .filter(Boolean);
                const hasValue = !!(inputVal || tags.length > 0);
                const hasError = Array.from(item.querySelectorAll('.el-form-item__error, .ant-form-item-explain-error'))
                    .some(n => isVisible(n));
                return hasValue && !hasError;
            }
            return false;
        }""")
        if loose_ok:
            print("      ⚠️ 执行员工精确回读未全命中，按页面已填+无报错放行")
            return True
    except Exception:
        pass
    return False

async def fill_step3_executor_by_condition(page, raw_values: str, include_franchise: bool = False) -> bool:
    """第3步执行员工（按条件筛选客户）：选择员工弹窗 -> 树节点 -> 添加全部 -> 确定。"""
    targets = [normalize_area_alias(x) for x in split_multi_values(raw_values)]
    if include_franchise:
        ext = []
        for t in targets:
            tt = (t or "").strip()
            if not tt:
                continue
            base = normalize_area_alias(tt.replace("加盟", ""))
            ext.append(base)
            ext.append(normalize_area_alias(f"{base}加盟"))
        seen = set()
        targets = [x for x in ext if not (x in seen or seen.add(x))]
    if not targets:
        return True
    print(f"      🧪 按条件筛选客户-目标节点: {targets}")

    async def open_picker() -> bool:
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const buttons = Array.from(document.querySelectorAll('button, .el-button, .ant-btn')).filter(isVisible);
            const hit = buttons.find(b => {
                const t = norm(b.textContent || '');
                return t === '选择员工' || t.includes('选择员工');
            });
            if (hit) {
                (hit.closest('button') || hit).click();
                return true;
            }
            return false;
        }""")
        if not ok:
            return False
        await asyncio.sleep(0.5)
        opened = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap')).filter(isVisible);
            for (const w of wrappers) {
                const txt = norm(w.textContent || '');
                if (txt.includes('选择员工')) return true;
            }
            const dialogs = Array.from(document.querySelectorAll('.el-dialog, .ant-modal')).filter(isVisible);
            for (const d of dialogs) {
                const txt = norm(d.textContent || '');
                if (txt.includes('选择员工')) return true;
            }
            return false;
        }""")
        if not opened:
            return False
        return True

    async def modal_pick_area(target: str, expand_only: bool = False) -> bool:
        return await page.evaluate("""(payload) => {
            const target = payload?.target || '';
            const expandOnly = !!payload?.expandOnly;
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const pickModal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                if (!isVisible(d)) return false;
                const txt = norm(d.textContent || '');
                return txt.includes('选择员工');
            });
            if (!pickModal) return false;
            const tgt = norm(target);
            const rows = Array.from(pickModal.querySelectorAll('.el-tree-node__content')).filter(isVisible);
            if (!rows.length) return false;
            const fire = (el) => {
                if (!el) return false;
                ['pointerdown','mousedown','mouseup','click'].forEach(tp => {
                    el.dispatchEvent(new MouseEvent(tp, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            let hit = null;
            let bestScore = -1;
            const isJoin = tgt.includes('加盟');
            for (const row of rows) {
                const label = row.querySelector('.el-tree-node__label');
                const txt = norm(label ? label.textContent : row.textContent || '');
                if (!txt) continue;
                let score = -1;
                if (txt === tgt) score = 3; // 精准命中最高优先
                else if (txt.includes(tgt)) score = 2; // 文本包含目标
                else if (!isJoin && !txt.includes('加盟') && tgt.includes(txt)) score = 1; // 仅非加盟目标允许反向包含
                if (score > bestScore) {
                    bestScore = score;
                    hit = row;
                }
            }
            if (!hit || bestScore < 0) return false;
            hit.scrollIntoView({ block: 'center' });
            const exp = hit.querySelector('.el-tree-node__expand-icon');
            if (exp) {
                // 仅当未展开时点击展开，避免二次点击折叠。
                const cls = exp.className || '';
                const alreadyExpanded = cls.includes('is-expanded') || cls.includes('expanded');
                if (!alreadyExpanded) {
                    fire(exp);
                }
            }
            if (expandOnly) return true;
            // 该弹窗按区域筛选通常通过“点击节点文本”触发左侧员工列表刷新。
            const label = hit.querySelector('.el-tree-node__label');
            if (label && fire(label)) return true;
            if (fire(hit)) return true;
            const cbInner = hit.querySelector('.el-checkbox__inner');
            if (cbInner && fire(cbInner)) return true;
            const cbInput = hit.querySelector('.el-checkbox__original');
            if (cbInput && fire(cbInput)) return true;
            return false;
        }""", {"target": target, "expandOnly": bool(expand_only)})

    async def modal_filter_pick_area(target: str) -> bool:
        """优先通过“输入关键字进行过滤”快速定位并点击目标节点。"""
        return await page.evaluate("""(target) => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const norm = (s) => (s || '').replace(/\\s+/g, '');
            const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                if (!isVisible(d)) return false;
                const txt = norm(d.textContent || '');
                return txt.includes('选择员工');
            });
            if (!modal) return false;
            const tgt = norm(target || '');
            if (!tgt) return false;
            const fireInput = (inp, val) => {
                if (!inp) return false;
                inp.focus();
                inp.value = val;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                return true;
            };
            const fireClick = (el) => {
                if (!el) return false;
                ['pointerdown','mousedown','mouseup','click'].forEach(tp => {
                    el.dispatchEvent(new MouseEvent(tp, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof el.click === 'function') el.click();
                return true;
            };
            const kw = Array.from(modal.querySelectorAll('input, textarea')).find(inp => {
                if (!isVisible(inp)) return false;
                const p = norm(inp.getAttribute('placeholder') || '');
                return p.includes('关键字') || p.includes('过滤');
            });
            if (kw) {
                fireInput(kw, target || '');
            }
            const labels = Array.from(modal.querySelectorAll('.el-tree-node__label')).filter(isVisible);
            let hit = null;
            let best = -1;
            for (const lb of labels) {
                const txt = norm(lb.textContent || '');
                if (!txt) continue;
                let score = -1;
                if (txt === tgt) score = 3;
                else if (txt.includes(tgt)) score = 2;
                else if (!tgt.includes('加盟') && tgt.includes(txt)) score = 1;
                if (score > best) { best = score; hit = lb; }
            }
            if (!hit || best < 0) return false;
            hit.scrollIntoView({ block: 'center' });
            return fireClick(hit);
        }""", target)

    async def modal_switch_to_tree() -> bool:
        """若弹窗存在“切换为选择树”，先切到树模式再选区域。"""
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                if (!isVisible(d)) return false;
                const txt = (d.textContent || '').replace(/\\s+/g, '');
                return txt.includes('选择员工');
            });
            if (!modal) return false;
            const btn = Array.from(modal.querySelectorAll('button,span,a,div')).find(el => {
                if (!isVisible(el)) return false;
                const t = (el.textContent || '').replace(/\\s+/g, '');
                return t.includes('切换为选择树');
            });
            if (!btn) return false;
            (btn.closest('button') || btn).click();
            return true;
        }""")
        if ok:
            await asyncio.sleep(0.5)
        return bool(ok)

    async def modal_click_add_all() -> bool:
        return await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                if (!isVisible(d)) return false;
                const txt = (d.textContent || '').replace(/\\s+/g, '');
                return txt.includes('选择员工');
            });
            if (!modal) return false;
            let btn = Array.from(modal.querySelectorAll('button.el-button.el-button--success.el-button--mini')).find(el => {
                if (!isVisible(el)) return false;
                const t = (el.textContent || '').replace(/\\s+/g, '');
                return t.includes('添加全部');
            });
            if (!btn) {
                btn = Array.from(modal.querySelectorAll('button,span,div,a')).find(el => {
                    if (!isVisible(el)) return false;
                    const t = (el.textContent || '').replace(/\\s+/g, '');
                    return (
                        t === '添加全部'
                        || t.includes('添加全部')
                        || t.includes('全部添加')
                        || t.includes('添加员工')
                        || t.includes('添加选中')
                    );
                });
            }
            if (!btn) return false;
            (btn.closest('button') || btn).click();
            return true;
        }""")

    async def modal_confirm() -> bool:
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const s = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            };
            const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                if (!isVisible(d)) return false;
                const txt = (d.textContent || '').replace(/\\s+/g, '');
                return txt.includes('选择员工');
            });
            if (!modal) return false;
            // 1) 首选 footer 内主按钮（最稳定）
            const footerPrimary = Array.from(modal.querySelectorAll(
                '.el-dialog__footer button.el-button--primary, .ant-modal-footer .ant-btn-primary'
            )).find(isVisible);
            if (footerPrimary) {
                footerPrimary.click();
                return true;
            }
            // 2) 次选固定 class + 文本
            let btn = Array.from(modal.querySelectorAll('button.el-button.el-button--primary.el-button--small')).find(b => {
                if (!isVisible(b)) return false;
                const t = (b.textContent || '').replace(/\\s+/g, '');
                return t === '确定' || t === '确 定' || t.includes('确定');
            });
            if (btn) {
                (btn.closest('button') || btn).click();
                return true;
            }
            const btns = Array.from(modal.querySelectorAll('button,span,div,a')).filter(isVisible);
            for (const b of btns) {
                const t = (b.textContent || '').replace(/\\s+/g, '');
                if (t === '确定' || t === '确 定' || t.includes('确定')) {
                    (b.closest('button') || b).click();
                    return true;
                }
            }
            // 3) 最后兜底：选最靠右主按钮
            const allPrimary = Array.from(modal.querySelectorAll('button.el-button--primary, .ant-btn-primary'))
                .filter(isVisible)
                .sort((a,b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
            if (allPrimary.length) {
                allPrimary[0].click();
                return true;
            }
            return false;
        }""")
        if ok:
            await asyncio.sleep(0.5)
        return bool(ok)

    async def read_modal_current_tree_label() -> str:
        """读取弹窗树当前激活节点文本（用于确认确实切到了目标节点）。"""
        try:
            return (await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                    if (!isVisible(d)) return false;
                    const txt = norm(d.textContent || '');
                    return txt.includes('选择员工');
                });
                if (!modal) return '';
                const cand = modal.querySelector('.el-tree-node.is-current .el-tree-node__label')
                    || modal.querySelector('.el-tree-node__content.is-current .el-tree-node__label')
                    || modal.querySelector('.el-tree-node.is-current .el-tree-node__content .el-tree-node__label');
                if (!cand) return '';
                return norm(cand.textContent || '');
            }""") or "").strip()
        except Exception:
            return ""

    async def ensure_modal_target_active(target: str) -> bool:
        """确保树里当前激活节点就是目标，避免只展开未切到目标。"""
        tgt = normalize_area_alias(target)
        for _ in range(4):
            _ = await modal_pick_area(tgt, expand_only=False)
            await asyncio.sleep(0.2)
            curr = await read_modal_current_tree_label()
            if curr and (curr == tgt or tgt in curr):
                return True
        return False

    async def read_selected_count() -> int:
        try:
            val = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const nodes = Array.from(document.querySelectorAll('body *')).filter(isVisible);
                for (const n of nodes) {
                    const t = (n.textContent || '').replace(/\\s+/g, '');
                    if (!t.includes('已选中')) continue;
                    const m = t.match(/已选中[:：]?\\s*(\\d+)人?/);
                    if (m) return Number(m[1] || 0);
                    const m2 = t.match(/已选中\\(?（?(\\d+)\\)?）?/);
                    if (m2) return Number(m2[1] || 0);
                }
                return 0;
            }""")
            return int(val or 0)
        except Exception:
            return 0

    async def read_modal_added_count() -> int:
        """读取“选择员工”弹窗右侧已添加数量（已选员工共X条）。"""
        try:
            return int(await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                    if (!isVisible(d)) return false;
                    const txt = norm(d.textContent || '');
                    return txt.includes('选择员工');
                });
                if (!modal) return 0;
                const txt = norm(modal.textContent || '');
                const m = txt.match(/已选员工共(\\d+)条/);
                if (m) return Number(m[1] || 0);
                // 优先：按“按区域移除”后的右侧区域提取“共X条”
                if (txt.includes('按区域移除')) {
                    const part = txt.split('按区域移除').pop() || '';
                    const arr = Array.from(part.matchAll(/共(\\d+)条/g)).map(x => Number(x[1] || 0));
                    if (arr.length) return arr[arr.length - 1];
                }
                // 次优：按“移除全部/移除所选”后的区域提取
                if (txt.includes('移除全部')) {
                    const part2 = txt.split('移除全部').pop() || '';
                    const arr2 = Array.from(part2.matchAll(/共(\\d+)条/g)).map(x => Number(x[1] || 0));
                    if (arr2.length) return arr2[arr2.length - 1];
                }
                // 兜底：全弹窗出现多个“共X条”时取最大值（通常右侧已选 > 左侧候选）
                const all = Array.from(txt.matchAll(/共(\\d+)条/g)).map(x => Number(x[1] || 0));
                if (all.length) return Math.max(...all);
                // 未命中任何人数文本
                if (txt.includes('暂无已选员工')) return 0;
                return -1;
            }""") or 0)
        except Exception:
            return 0

    async def read_modal_left_count() -> int:
        """读取“选择员工”弹窗左侧候选员工数量（共X条）。"""
        try:
            return int(await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                    if (!isVisible(d)) return false;
                    const txt = norm(d.textContent || '');
                    return txt.includes('选择员工');
                });
                if (!modal) return 0;
                const txt = norm(modal.textContent || '');
                // 结构通常是：左侧“共X条” + 右侧“已选员工共Y条”
                const all = Array.from(txt.matchAll(/共(\\d+)条/g)).map(m => Number(m[1] || 0));
                if (!all.length) return 0;
                const right = (txt.match(/已选员工共(\\d+)条/) || [null, "0"])[1];
                const rightNum = Number(right || 0);
                // 优先返回非右侧的第一个共X条
                for (const n of all) {
                    if (n !== rightNum) return n;
                }
                // 兜底：返回第一个
                return all[0] || 0;
            }""") or 0)
        except Exception:
            return 0

    async def modal_target_checked(target: str) -> bool:
        """判定当前目标节点是否被选中（用于“添加全部后人数未增长”的去重场景）。"""
        try:
            return bool(await page.evaluate("""(target) => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, '');
                const tgt = norm(target || '');
                const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                    if (!isVisible(d)) return false;
                    const txt = norm(d.textContent || '');
                    return txt.includes('选择员工');
                });
                if (!modal || !tgt) return false;
                const rows = Array.from(modal.querySelectorAll('.el-tree-node__content')).filter(isVisible);
                let hit = null;
                let best = -1;
                for (const row of rows) {
                    const lb = row.querySelector('.el-tree-node__label');
                    const txt = norm(lb ? lb.textContent : row.textContent || '');
                    if (!txt) continue;
                    let score = -1;
                    if (txt === tgt) score = 3;
                    else if (txt.includes(tgt)) score = 2;
                    else if (!tgt.includes('加盟') && tgt.includes(txt)) score = 1;
                    if (score > best) { best = score; hit = row; }
                }
                if (!hit || best < 0) return false;
                const box = hit.querySelector('.el-checkbox__input') || hit.querySelector('.el-checkbox');
                const cls = box ? (box.className || '') : '';
                return cls.includes('is-checked') || cls.includes('checked');
            }""", target))
        except Exception:
            return False

    if not await open_picker():
        print("      ⚠️ 按条件筛选客户-未找到“选择员工”入口")
        return False
    # 兼容“列表模式/树模式”切换：优先切到树模式，便于按区域逐级选择。
    _ = await modal_switch_to_tree()
    # 常见树控件需要先激活“全国”根节点，后续省区/营运区才会出现。
    _ = await modal_pick_area("全国")
    await asyncio.sleep(0.2)

    # 路径提示，先点击父节点再点击目标节点（点击文本即可触发中间员工列表刷新）
    path_hints = {
        "广佛省区": ["华南大区", "广佛省区"],
        "广佛省区加盟": ["华南大区加盟", "广佛省区加盟"],
        "大郑州营运区": ["西北大区", "河南省区", "大郑州营运区"],
        "大郑州营运区加盟": ["西北大区加盟", "河南省区加盟", "大郑州营运区加盟"],
        "郑州": ["西北大区", "河南省区", "大郑州营运区"],
        "郑州加盟": ["西北大区加盟", "河南省区加盟", "大郑州营运区加盟"],
        "黑龙江省区": ["北方大区", "黑龙江省区"],
        "黑龙江省区加盟": ["北方大区加盟", "黑龙江省区加盟"],
        "武汉营运区": ["华中大区", "湖北省区", "武汉营运区"],
        "武汉营运区加盟": ["华中大区加盟", "湖北省区加盟", "武汉营运区加盟"],
        "武汉": ["华中大区", "湖北省区", "武汉营运区"],
        "武汉加盟": ["华中大区加盟", "湖北省区加盟", "武汉营运区加盟"],
        "江西省区": ["华中大区", "江西省区"],
        "江西省区加盟": ["华中大区加盟", "江西省区加盟"],
        # 社群常见简称（文件里只写城市名）
        "肇庆": ["华南大区", "广佛省区", "肇庆营运区"],
        "肇庆营运区": ["华南大区", "广佛省区", "肇庆营运区"],
        "肇庆加盟": ["华南大区加盟", "广佛省区加盟", "肇庆营运区加盟"],
        "肇庆营运区加盟": ["华南大区加盟", "广佛省区加盟", "肇庆营运区加盟"],
        "云浮": ["华南大区", "广佛省区", "云浮营运区"],
        "云浮营运区": ["华南大区", "广佛省区", "云浮营运区"],
        "云浮加盟": ["华南大区加盟", "广佛省区加盟", "云浮营运区加盟"],
        "云浮营运区加盟": ["华南大区加盟", "广佛省区加盟", "云浮营运区加盟"],
    }

    picked_any = False
    selected_before = await read_selected_count()
    modal_added_before = await read_modal_added_count()
    for t in targets:
        # 先走关键词过滤命中（对层级较深的营运区更稳）
        _ = await modal_filter_pick_area(t)
        await asyncio.sleep(0.15)
        chain = path_hints.get(t, [t])
        target_hit = False
        for idx, seg in enumerate(chain):
            seg_ok = await modal_pick_area(seg, expand_only=(idx < len(chain) - 1))
            target_hit = target_hit or bool(seg_ok)
            await asyncio.sleep(0.15)
        # 兜底：路径未命中时，再直接尝试目标文本一次（例如名称别名/层级变化）
        if not target_hit:
            direct_ok = await modal_pick_area(t)
            target_hit = target_hit or bool(direct_ok)
            await asyncio.sleep(0.15)
        if not target_hit:
            # 加盟兜底：找不到“xx加盟”时，尝试去掉“加盟”后再选一次
            if t.endswith("加盟"):
                plain = t[:-2]
                plain_ok = await modal_pick_area(plain)
                target_hit = target_hit or bool(plain_ok)
                await asyncio.sleep(0.15)
        if not target_hit:
            # 简称兜底：如“肇庆/云浮”在树里实际为“肇庆营运区/云浮营运区”
            cand = []
            if t.endswith("加盟"):
                plain = t[:-2]
                if (plain and ("大区" not in plain) and ("省区" not in plain) and ("营运区" not in plain)):
                    cand.append(f"{plain}营运区加盟")
            else:
                if ("大区" not in t) and ("省区" not in t) and ("营运区" not in t):
                    cand.append(f"{t}营运区")
            for c in cand:
                c_ok = await modal_pick_area(c)
                target_hit = target_hit or bool(c_ok)
                await asyncio.sleep(0.15)
                if target_hit:
                    # 统一把当前目标替换为真实命中节点文本，后续激活校验/日志更准确
                    t = c
                    break
        if not target_hit:
            continue
        active_ok = await ensure_modal_target_active(t)
        curr_label = await read_modal_current_tree_label()
        print(f"      🧪 目标节点激活校验: target={t}, active={curr_label or 'none'}, ok={active_ok}")
        if not active_ok:
            print(f"      ⚠️ 未成功激活目标节点，跳过本轮添加: {t}")
            continue
        # 选中区域后，等待左侧列表加载（共X条从0变大）
        left_before = await read_modal_left_count()
        left_after = left_before
        for _ in range(20):  # ~6秒
            await asyncio.sleep(0.3)
            left_after = await read_modal_left_count()
            if left_after > 0:
                break
        print(f"      🧪 选择区域后左侧员工数: before={left_before}, after={left_after}, target={t}")
        add_ok = await modal_click_add_all()
        if add_ok:
            await asyncio.sleep(0.25)
            modal_added_now = await read_modal_added_count()
            # 强校验：必须看到右侧“已选员工共X条”真实增长；否则重试一次选择+添加。
            if modal_added_now < 0 or modal_added_now <= modal_added_before:
                _ = await ensure_modal_target_active(t)
                await asyncio.sleep(0.2)
                _ = await modal_click_add_all()
                for _ in range(20):  # 最多约6秒等待右侧已选增长
                    await asyncio.sleep(0.3)
                    modal_added_now = await read_modal_added_count()
                    if modal_added_now > modal_added_before:
                        break
            selected_now = await read_selected_count()
            print(f"      🧪 添加全部后右侧已选条数: before={modal_added_before}, after={modal_added_now}, target={t}")
            target_checked = await modal_target_checked(t)
            if (modal_added_now > modal_added_before) or target_checked:
                picked_any = True
                if modal_added_now > modal_added_before:
                    modal_added_before = modal_added_now
                selected_before = max(selected_before, selected_now)
            else:
                print(f"      ⚠️ 添加全部后右侧已选条数未增长，判定未生效: {t}")
        await asyncio.sleep(0.2)

    if not picked_any:
        try:
            diag = await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const modal = Array.from(document.querySelectorAll('.el-dialog__wrapper, .ant-modal-wrap, .el-dialog, .ant-modal')).find(d => {
                    if (!isVisible(d)) return false;
                    const txt = (d.textContent || '').replace(/\\s+/g, '');
                    return txt.includes('选择员工');
                });
                if (!modal) return { found: false, buttons: [], preview: '' };
                const btns = Array.from(modal.querySelectorAll('button,span,a,div'))
                    .filter(isVisible)
                    .map(n => (n.textContent || '').replace(/\\s+/g, ' ').trim())
                    .filter(Boolean)
                    .slice(0, 40);
                const preview = (modal.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 320);
                return { found: true, buttons: btns, preview };
            }""")
            print(f"      🧪 选择员工弹窗诊断: found={diag.get('found')}, buttons={diag.get('buttons', [])}")
            if diag.get("preview"):
                print(f"      🧪 选择员工弹窗文本: {diag.get('preview')}")
        except Exception:
            pass
        print("      ⚠️ 按条件筛选客户-未成功执行“添加全部”")
        return False

    confirm_ok = await modal_confirm()
    if not confirm_ok:
        print("      ⚠️ 按条件筛选客户-未找到弹窗“确定”按钮")
        return False

    selected_count = await read_selected_count()
    if selected_count <= 0:
        # 社群页面“已选中人数”可能异步回写，轮询等待一段时间再判定，避免误判为0。
        for _ in range(20):  # 最多约 6 秒
            await asyncio.sleep(0.3)
            selected_count = await read_selected_count()
            if selected_count > 0:
                break
    print(f"      🧪 按条件筛选客户-已选中人数: {selected_count}")
    return selected_count > 0

async def set_plan_time_range(page, start_time: str, end_time: str):
    """设置 Element 日期范围并点击确定，避免值未提交。"""
    s_date, s_time = split_datetime(start_time)
    e_date, e_time = split_datetime(end_time, default_time="23:00:00")
    print(f"   📅 计划时间: {s_date} {s_time} -> {e_date} {e_time}")

    item = await get_form_item_by_label(page, "计划时间")
    if not item:
        print("      ⚠️ 未找到“计划时间”字段，回退到普通输入")
        await fill_input(page, "开始日期", start_time)
        await fill_input(page, "结束日期", end_time)
        return

    async def apply_once() -> bool:
        # 打开日期范围面板
        await item.locator("input").first.click(force=True)
        panel = page.locator('.el-picker-panel.el-date-range-picker:visible').first
        try:
            await panel.wait_for(timeout=3000)
        except PlaywrightTimeout:
            try:
                await item.locator("input").first.click(force=True)
                await panel.wait_for(timeout=2500)
            except PlaywrightTimeout:
                return False

        # 在面板头部编辑器中填值（并回车触发内部校验）
        s_date_input = panel.get_by_placeholder("开始日期").first
        s_time_input = panel.get_by_placeholder("开始时间").first
        e_date_input = panel.get_by_placeholder("结束日期").first
        e_time_input = panel.get_by_placeholder("结束时间").first
        await fill_with_retry(s_date_input, s_date)
        await s_date_input.press("Enter")
        await fill_with_retry(s_time_input, s_time)
        await s_time_input.press("Enter")
        await fill_with_retry(e_date_input, e_date)
        await e_date_input.press("Enter")
        await fill_with_retry(e_time_input, e_time)
        await e_time_input.press("Enter")

        # 必须点确定，否则会保留旧值
        footer_confirm = panel.locator('.el-picker-panel__footer button:has-text("确定")').first
        await footer_confirm.click(force=True)
        await asyncio.sleep(0.35)
        return True

    async def direct_set_two_inputs() -> bool:
        """兜底：直接写入计划时间区域内的前两个输入框（开始/结束）。"""
        start_full = f"{s_date} {s_time}"
        end_full = f"{e_date} {e_time}"
        ok = await item.evaluate(
            """(node, payload) => {
                const inputs = Array.from(node.querySelectorAll('input'));
                if (inputs.length < 2) return false;
                const [startInput, endInput] = inputs;
                const write = (el, val) => {
                    el.focus();
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                    el.blur();
                };
                write(startInput, payload.start);
                write(endInput, payload.end);
                return true;
            }""",
            {"start": start_full, "end": end_full}
        )
        await asyncio.sleep(0.25)
        return ok

    applied = await apply_once()
    values = await read_item_input_values(item)
    ok = values_include_datetime(values, s_date, s_time) and values_include_datetime(values, e_date, e_time)
    if not ok:
        print(f"      ⚠️ 第1轮计划时间未生效，回读={values}，执行第2轮写入...")
        applied = await apply_once() or applied
        values = await read_item_input_values(item)
        ok = values_include_datetime(values, s_date, s_time) and values_include_datetime(values, e_date, e_time)

    if not ok:
        wrote = await direct_set_two_inputs()
        values = await read_item_input_values(item)
        ok = wrote and values_include_datetime(values, s_date, s_time) and values_include_datetime(values, e_date, e_time)
        if wrote:
            print("      ⚠️ 日期面板路径失败，已走双输入框兜底")

    # 最后一轮强制覆盖，避免页面内部回填旧结束时间
    if ok:
        await direct_set_two_inputs()
        values = await read_item_input_values(item)
        ok = values_include_datetime(values, s_date, s_time) and values_include_datetime(values, e_date, e_time)

    if not ok:
        raise RuntimeError(f"计划时间回读校验失败，当前值={values}，期望={s_date} {s_time} -> {e_date} {e_time}")
    print(f"      ✅ 计划时间回读校验通过: {values}")

async def set_send_time(page, send_time: str):
    """设置发送时间：单日期时间面板内填写并强制点击确定。"""
    s_date, s_time = split_datetime(send_time)
    print(f"   🕒 发送时间: {s_date} {s_time}")

    item = await get_form_item_by_label(page, "发送时间")
    if not item:
        raise RuntimeError("发送时间设置失败：未找到字段")

    expected = f"{s_date} {s_time}"

    async def apply_once() -> bool:
        await item.locator("input").first.click(force=True)
        panel = page.locator('.el-picker-panel.el-date-picker:visible').first
        try:
            await panel.wait_for(timeout=2500)
        except PlaywrightTimeout:
            return False
        await fill_with_retry(panel.get_by_placeholder("选择日期").first, s_date)
        await fill_with_retry(panel.get_by_placeholder("选择时间").first, s_time)
        footer_confirm = panel.locator('.el-picker-panel__footer button:has-text("确定")').first
        await footer_confirm.click(force=True)
        await asyncio.sleep(0.3)
        print("      ✅ 已点击发送时间面板“确定”")
        return True

    field_input = item.locator("input").first
    applied = await apply_once()
    if not applied:
        applied = await apply_once()

    field_value = (await field_input.input_value()).strip()
    print(f"      🔎 发送时间字段回读: {field_value}")

    if not datetime_equals(field_value, expected):
        # 兜底：直接回填字段本体，并触发 input/change/Enter/blur。
        await fill_with_retry(field_input, expected)
        await field_input.press("Enter")
        await field_input.blur()
        await asyncio.sleep(0.2)
        field_value = (await field_input.input_value()).strip()
        print(f"      🔁 发送时间兜底后回读: {field_value}")

    if not datetime_equals(field_value, expected):
        raise RuntimeError(f"发送时间回读校验失败，当前值={field_value}，期望={expected}")
    print(f"      ✅ 发送时间回读校验通过: {field_value}")

# ============ 第1步：基础信息 ============

async def fill_step1(page, data: dict, auto_next: bool = True):
    """填充第1步"""
    print("\n📋 第1步：基础信息")
    print("="*50)
    
    await page.wait_for_selector('.el-form, .ant-form', timeout=10000)
    await wait_and_log(page, 2, "页面加载中...")
    
    results = {}

    await fill_input(page, "计划名称", data["name"])
    results["第1步-计划名称"] = True
    region_ok = await select_option(page, "计划区域", data["region"])
    if not region_ok:
        await asyncio.sleep(0.5)
        region_ok = await select_option(page, "计划区域", data["region"])
    if not region_ok:
        raise RuntimeError("第1步失败：计划区域未选择成功")
    results["第1步-计划区域"] = True
    theme_val = data.get("theme", "其他")
    # 营销主题在页面是多选组件：即便仅传一个值，也按多选逻辑处理，
    # 这样可先清理默认“其他”等历史脏值，再精确保留目标主题。
    theme_is_multi = True
    theme_ok = await select_option(page, "营销主题", theme_val, is_multi=theme_is_multi)
    if not theme_ok:
        await asyncio.sleep(0.5)
        theme_ok = await select_option(page, "营销主题", theme_val, is_multi=theme_is_multi)
    if not theme_ok:
        raise RuntimeError("第1步失败：营销主题未选择成功")
    results["第1步-营销主题"] = True
    
    def _is_effective_config_value(v: str) -> bool:
        s = str(v or "").strip()
        if not s:
            return False
        # 兼容业务文件中“空值占位”写法：这些都按未配置处理（即跳过）
        return s.lower() not in {"-", "--", "无", "空", "null", "none", "nan", "n/a", "na"}

    scene_type = (data.get("scene_type", "") or "").strip()
    plan_type = (data.get("plan_type", "") or "").strip()
    if _is_effective_config_value(scene_type):
        # 先尝试真实选择（社群页有时看起来像禁用态，实际可选）
        scene_ok = await select_option(page, "场景类型", scene_type)
        if not scene_ok:
            scene_state = await read_select_state_and_value(page, "场景类型")
            if scene_state.get("found") and scene_state.get("locked"):
                curr = (scene_state.get("value") or "").strip()
                full_txt = (scene_state.get("full_text") or "").strip()
                if curr and (scene_type in curr or curr in scene_type):
                    scene_ok = True
                    print(f"   ✅ 场景类型: 禁用态且已匹配（{curr}），快速跳过")
                elif full_txt and (scene_type in full_txt):
                    scene_ok = True
                    print(f"   ✅ 场景类型: 禁用态文本命中（{scene_type}），快速跳过")
        print(f"   {'✅' if scene_ok else '⚠️'} 场景类型: {scene_type if scene_ok else '未匹配，已跳过'}")
        if not scene_ok:
            raise RuntimeError(f"第1步失败：场景类型未选择成功（期望={scene_type}）")
    else:
        print("   ⏭️  场景类型: 未配置，跳过")
    if _is_effective_config_value(plan_type):
        # 先尝试真实选择（社群页有时看起来像禁用态，实际可选）
        plan_ok = await select_option(page, "计划类型", plan_type)
        if not plan_ok:
            plan_state = await read_select_state_and_value(page, "计划类型")
            if plan_state.get("found") and plan_state.get("locked"):
                curr = (plan_state.get("value") or "").strip()
                full_txt = (plan_state.get("full_text") or "").strip()
                if curr and (plan_type in curr or curr in plan_type):
                    plan_ok = True
                    print(f"   ✅ 计划类型: 禁用态且已匹配（{curr}），快速跳过")
                elif full_txt and (plan_type in full_txt):
                    plan_ok = True
                    print(f"   ✅ 计划类型: 禁用态文本命中（{plan_type}），快速跳过")
        print(f"   {'✅' if plan_ok else '⚠️'} 计划类型: {plan_type if plan_ok else '未匹配，已跳过'}")
        if not plan_ok:
            raise RuntimeError(f"第1步失败：计划类型未选择成功（期望={plan_type}）")
    else:
        print("   ⏭️  计划类型: 未配置，跳过")
    print("   ⏭️  营销模板: 跳过")
    
    await select_radio(page, "推荐算法", data["use_recommend"])
    results["第1步-推荐算法"] = True
    await set_plan_time_range(page, data["start_time"], data["end_time"])
    results["第1步-计划时间"] = True
    await select_radio(page, "触发方式", data["trigger_type"])
    results["第1步-触发方式"] = True
    await set_send_time(page, data["send_time"])
    results["第1步-发送时间"] = True
    await select_radio(page, "触达限制", data["global_limit"])
    results["第1步-全局触达限制"] = True
    await select_radio(page, "设置目标", data["set_target"])
    results["第1步-是否设置目标"] = True
    
    print("\n   ✅ 第1步完成")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step1-after.png')
    
    if auto_next:
        print("   ⏭️  点击下一步...")
        clicked = await click_button_with_text(page, "下一步")
        did_next = clicked
        if not clicked:
            community_mode = (
                "addcommunityPlan" in (data.get("create_url", "") or "")
                or "会员通-发送社群" in (data.get("channels", "") or "")
            )
            if community_mode:
                print("      ⏭️ 社群页未检测到“下一步”，按单页流程继续")
                did_next = False
            else:
                raise RuntimeError("第1步完成后未能点击“下一步”")
        if did_next:
            print("      ✅ 点击成功")
            results["第1步-下一步按钮"] = True
            await wait_and_log(page, 3, "等待页面跳转...")
            try:
                still_on_step1 = await page.evaluate("""() => {
                    const text = document.body?.innerText || '';
                    return text.includes('计划名称') && text.includes('计划时间') && text.includes('发送时间');
                }""")
                if still_on_step1:
                    err = await read_visible_error_hint(page)
                    if err:
                        raise RuntimeError(f"第1步业务校验未通过: {err}")
            except Exception:
                raise
        else:
            results["第1步-下一步按钮"] = True
    else:
        print("   ⏭️  第2步自动化模式：第1步暂不点击下一步，由第2步完成后统一跳转")
    return results

# ============ 第2步：目标分群 ============

async def fill_step2(page, data: dict, strict_step2: bool = False):
    """填充第2步：目标分群"""
    print("\n📋 第2步：目标分群")
    print("="*50)
    results = {
        "第2步-编辑按钮": False,
        "第2步-弹窗可见": False,
        "第2步-更新方式": False,
        "第2步-主消费营运区": False,
        "第2步-主消费门店": False,
        "第2步-商品编码": False,
        "第2步-门店信息已选": False,
        "第2步-券规则ID": False,
        "第2步-预跑按钮": False,
        "第2步-下一步按钮": False,
    }
    step2_has_pick_btn = True
    step2_has_coupon_row = True
    
    await wait_and_log(page, 2, "等待第2步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-before.png')
    
    print("   🖱️  点击分群的编辑按钮...")
    async def click_edit_once() -> bool:
        try:
            return await page.evaluate('''() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if ((btn.textContent || '').includes('编辑')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')
        except:
            return False

    clicked_edit = await click_edit_once()
    if clicked_edit:
        print("      ✅ JavaScript点击成功")
        results["第2步-编辑按钮"] = True
    else:
        print("      ⚠️ 点击编辑失败")
    
    await wait_and_log(page, 3, "弹窗加载中...")
    # 强制前台，避免 CDP 下后台页“点击成功但用户没看到”
    try:
        await page.bring_to_front()
    except Exception:
        pass
    
    # 处理可能的浏览器弹窗（如本地网络权限）
    try:
        page.on('dialog', lambda dialog: dialog.accept())
    except:
        pass
    
    # 检测弹窗内是否有 iframe
    async def read_iframe_info():
        return await page.evaluate('''() => {
            const iframes = document.querySelectorAll('iframe');
            const info = [];
            iframes.forEach((iframe, i) => {
                const rect = iframe.getBoundingClientRect();
                const style = window.getComputedStyle(iframe);
                info.push({
                    index: i,
                    src: iframe.src || '',
                    id: iframe.id || '',
                    name: iframe.name || '',
                    visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
                });
            });
            return info;
        }''')

    print("   🔍 检测弹窗内的 iframe...")
    iframe_info = await read_iframe_info()
    print(f"      找到 {len(iframe_info)} 个 iframe")
    if len(iframe_info) == 0 and strict_step2:
        raise RuntimeError("第2步失败：未检测到分群 iframe 弹窗")
    
    # 等待弹窗/iframe 内容加载
    print("   ⏳ 等待 iframe 内容加载...")
    await asyncio.sleep(3)
    
    step2_error = None

    if iframe_info:
        # 等待可见 iframe 稳定出现，避免“闪现即消失”被过早判失败。
        visible_iframes = [x for x in iframe_info if x.get("visible")]
        if len(visible_iframes) == 0:
            for _ in range(8):
                await asyncio.sleep(0.4)
                iframe_info = await read_iframe_info()
                visible_iframes = [x for x in iframe_info if x.get("visible")]
                if len(visible_iframes) > 0:
                    break
        # 若仍不可见，重试一次点击编辑再等待。
        if len(visible_iframes) == 0:
            print("      ⚠️ iframe 暂不可见，重试点击编辑...")
            await click_edit_once()
            for _ in range(8):
                await asyncio.sleep(0.4)
                iframe_info = await read_iframe_info()
                visible_iframes = [x for x in iframe_info if x.get("visible")]
                if len(visible_iframes) > 0:
                    break
        print(f"      可见 iframe: {len(visible_iframes)}")
        await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-modal-visible-check.png')
        if len(visible_iframes) == 0 and strict_step2:
            raise RuntimeError("第2步失败：检测到 iframe 但均不可见（疑似未真正打开弹窗）")
        if len(visible_iframes) > 0:
            results["第2步-弹窗可见"] = True

        print("   🔧 在 iframe 内执行操作...")
        try:
            # 优先获取可见 iframe 对应 frame 对象
            frame_handle = await page.query_selector('iframe')
            if visible_iframes:
                for idx, it in enumerate(iframe_info):
                    if it.get("visible"):
                        candidate = page.locator("iframe").nth(idx)
                        if await candidate.count() > 0:
                            frame_handle = await candidate.element_handle()
                            break
            if frame_handle:
                frame = await frame_handle.content_frame()
                if frame:
                    async def _frame_eval_with_refetch(js_code: str, arg=None, retries: int = 3):
                        nonlocal frame, frame_handle, iframe_info, visible_iframes
                        last_err = None
                        for i in range(retries):
                            try:
                                if arg is None:
                                    return await frame.evaluate(js_code)
                                return await frame.evaluate(js_code, arg)
                            except Exception as e:
                                last_err = e
                                if "Frame was detached" not in str(e):
                                    raise
                                if i >= retries - 1:
                                    break
                                print(f"      ⚠️ iframe 已分离，重抓 frame 并重试 ({i + 1}/{retries - 1})")
                                try:
                                    await click_edit_once()
                                except Exception:
                                    pass
                                await asyncio.sleep(1.0)
                                iframe_info = await read_iframe_info()
                                visible_iframes = [x for x in iframe_info if x.get("visible")]
                                if not visible_iframes:
                                    await asyncio.sleep(0.6)
                                    iframe_info = await read_iframe_info()
                                    visible_iframes = [x for x in iframe_info if x.get("visible")]
                                frame_handle = None
                                for idx, it in enumerate(iframe_info):
                                    if it.get("visible"):
                                        candidate = page.locator("iframe").nth(idx)
                                        if await candidate.count() > 0:
                                            frame_handle = await candidate.element_handle()
                                            break
                                if frame_handle:
                                    frame = await frame_handle.content_frame()
                        raise last_err

                    # 内网/代理异常时常见现象：iframe 空白或加载失败，提前抛错避免“假成功”。
                    frame_diag = await _frame_eval_with_refetch("""() => {
                        const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').trim();
                        return {
                            href: location.href || '',
                            title: document.title || '',
                            textLen: bodyText.length,
                            hasErrKeyword: /ERR_|无法访问|无法连接|network|proxy|超时/i.test(bodyText + ' ' + (document.title || ''))
                        };
                    }""")
                    print(f"      iframe诊断: href={frame_diag.get('href','')}, title={frame_diag.get('title','')}, textLen={frame_diag.get('textLen',0)}")
                    # 兼容偶发：iframe 首次进入 chrome-error://chromewebdata 或临时空白，重开一次编辑弹窗后重抓 frame。
                    chrome_error_like = (
                        str(frame_diag.get("href", "")).startswith("chrome-error://")
                        or frame_diag.get("textLen", 0) == 0
                        or frame_diag.get("hasErrKeyword")
                    )
                    if chrome_error_like:
                        recovered = False
                        for retry_idx in range(2):
                            print(f"      ⚠️ iframe 加载异常，尝试重开弹窗并重抓 frame ({retry_idx + 1}/2)")
                            await click_edit_once()
                            await asyncio.sleep(1.2)
                            iframe_info = await read_iframe_info()
                            visible_iframes = [x for x in iframe_info if x.get("visible")]
                            if not visible_iframes:
                                await asyncio.sleep(0.8)
                                iframe_info = await read_iframe_info()
                                visible_iframes = [x for x in iframe_info if x.get("visible")]
                            if not visible_iframes:
                                continue
                            frame_handle = None
                            for idx, it in enumerate(iframe_info):
                                if it.get("visible"):
                                    candidate = page.locator("iframe").nth(idx)
                                    if await candidate.count() > 0:
                                        frame_handle = await candidate.element_handle()
                                        break
                            if not frame_handle:
                                continue
                            frame = await frame_handle.content_frame()
                            if not frame:
                                continue
                            frame_diag = await _frame_eval_with_refetch("""() => {
                                const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').trim();
                                return {
                                    href: location.href || '',
                                    title: document.title || '',
                                    textLen: bodyText.length,
                                    hasErrKeyword: /ERR_|无法访问|无法连接|network|proxy|超时/i.test(bodyText + ' ' + (document.title || ''))
                                };
                            }""")
                            print(f"      🧪 iframe 重抓诊断: href={frame_diag.get('href','')}, title={frame_diag.get('title','')}, textLen={frame_diag.get('textLen',0)}")
                            still_bad = (
                                str(frame_diag.get("href", "")).startswith("chrome-error://")
                                or frame_diag.get("textLen", 0) == 0
                                or frame_diag.get("hasErrKeyword")
                            )
                            if not still_bad:
                                recovered = True
                                break
                        if not recovered:
                            raise RuntimeError("第2步 iframe 内容为空或疑似网络/代理异常，请检查 VPN/代理并重试")

                    # 关键控件就绪等待：避免 iframe 刚打开时 textLen 很低、控件尚未挂载导致后续字段全 miss。
                    ready = await frame.evaluate("""() => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                        };
                        const hasNameInput = !!Array.from(document.querySelectorAll('input'))
                            .find(i => isVisible(i) && (
                                (i.getAttribute('placeholder') || '').includes('名称') ||
                                (i.getAttribute('placeholder') || '').includes('请输入')
                            ));
                        const hasPickBtn = !!Array.from(document.querySelectorAll('button'))
                            .find(b => isVisible(b) && (b.textContent || '').replace(/\\s+/g, '').includes('选择数据'));
                        const hasCouponRow = !!Array.from(document.querySelectorAll('.event-row, .ant-form-item, .ant-row, div'))
                            .find(r => isVisible(r) && (r.textContent || '').replace(/\\s+/g, '').includes('券规则ID'));
                        const textLen = ((document.body && document.body.innerText) ? document.body.innerText.trim().length : 0);
                        return { ok: (hasNameInput || hasPickBtn || hasCouponRow), hasNameInput, hasPickBtn, hasCouponRow, textLen };
                    }""")
                    if not ready.get("ok"):
                        print(f"      ⏳ iframe 控件未就绪，等待加载... textLen={ready.get('textLen', 0)}")
                        for _ in range(20):  # 最多再等 10 秒
                            await asyncio.sleep(0.5)
                            ready = await frame.evaluate("""() => {
                                const isVisible = (el) => {
                                    if (!el) return false;
                                    const style = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                };
                                const hasNameInput = !!Array.from(document.querySelectorAll('input'))
                                    .find(i => isVisible(i) && (
                                        (i.getAttribute('placeholder') || '').includes('名称') ||
                                        (i.getAttribute('placeholder') || '').includes('请输入')
                                    ));
                                const hasPickBtn = !!Array.from(document.querySelectorAll('button'))
                                    .find(b => isVisible(b) && (b.textContent || '').replace(/\\s+/g, '').includes('选择数据'));
                                const hasCouponRow = !!Array.from(document.querySelectorAll('.event-row, .ant-form-item, .ant-row, div'))
                                    .find(r => isVisible(r) && (r.textContent || '').replace(/\\s+/g, '').includes('券规则ID'));
                                const textLen = ((document.body && document.body.innerText) ? document.body.innerText.trim().length : 0);
                                return { ok: (hasNameInput || hasPickBtn || hasCouponRow), hasNameInput, hasPickBtn, hasCouponRow, textLen };
                            }""")
                            if ready.get("ok"):
                                break
                        print(
                            "      🧪 iframe 就绪回读: "
                            f"ok={ready.get('ok')}, textLen={ready.get('textLen', 0)}, "
                            f"name={ready.get('hasNameInput')}, pickBtn={ready.get('hasPickBtn')}, coupon={ready.get('hasCouponRow')}"
                        )
                    if not ready.get("ok"):
                        raise RuntimeError(
                            f"第2步 iframe 控件未就绪（textLen={ready.get('textLen', 0)}），请检查网络/VPN或重试"
                        )
                    step2_has_pick_btn = bool(ready.get("hasPickBtn"))
                    step2_has_coupon_row = bool(ready.get("hasCouponRow"))

                    # 第2步“名称”输入框自动填充已关闭，避免触发该弹窗异常关闭。
                    print("   📝 名称: ⏭️ 已跳过自动填充")
                    
                    # 在 iframe 内选择更新方式（回读校验）
                    print("   ⚪ 更新方式: " + data.get("update_type", "自动更新"))
                    try:
                        has_update_field = await frame.evaluate("""() => {
                            const txt = (document.body?.innerText || '').replace(/\\s+/g, '');
                            return txt.includes('自动更新') || txt.includes('手动更新') || txt.includes('更新方式');
                        }""")
                        if not has_update_field:
                            print("      ⏭️ 当前页面未检测到“更新方式”字段，自动跳过")
                            results["第2步-更新方式"] = True
                        elif "自动" in data.get("update_type", ""):
                            await frame.evaluate('''() => {
                                const els = document.querySelectorAll('*');
                                for (const el of els) {
                                    if (el.textContent.trim() === '自动更新') {
                                        el.click();
                                        return 'clicked';
                                    }
                                }
                            }''')
                            await asyncio.sleep(0.2)
                            update_ok = await frame.evaluate("""() => {
                                const checked = document.querySelector('.ant-radio-wrapper-checked, .el-radio.is-checked');
                                if (!checked) return false;
                                const txt = (checked.textContent || '').replace(/\\s+/g, '');
                                return txt.includes('自动更新');
                            }""")
                            if update_ok:
                                print("      ✅ 已选择自动更新")
                                results["第2步-更新方式"] = True
                            else:
                                print("      ⚠️ 更新方式回读失败（未选中自动更新）")
                        else:
                            # 非“自动更新”场景当前不强控，避免误伤其它配置
                            results["第2步-更新方式"] = True
                    except Exception as e:
                        print(f"      ⚠️ 更新方式选择失败: {e}")
                    
                    # 在 iframe 内点击选择数据按钮
                    if data.get("main_operating_area"):
                        print(f"   🏢 主消费营运区: {data['main_operating_area']}")
                        try:
                            if not step2_has_pick_btn:
                                print("      ⏭️ 当前页面未检测到“选择数据”控件，主消费营运区自动跳过")
                                results["第2步-主消费营运区"] = True
                                raise RuntimeError("__skip_main_operating_area__")
                            area_escaped = escape_js_string(data["main_operating_area"])
                            clicked = await frame.evaluate('''() => {
                                const btns = document.querySelectorAll('button');
                                for (const btn of btns) {
                                    if (btn.textContent.includes('选择数据')) {
                                        btn.click();
                                        return 'clicked';
                                    }
                                }
                                return 'not_found';
                            }''')
                            if clicked == 'not_found':
                                # 兜底1：更宽松文本定位（a/div/span）
                                clicked = await frame.evaluate('''() => {
                                    const els = document.querySelectorAll('a, span, div');
                                    for (const el of els) {
                                        const t = (el.textContent || '').trim();
                                        if (t === '选择数据' || t.includes('选择数据')) {
                                            el.click();
                                            return 'clicked';
                                        }
                                    }
                                    return 'not_found';
                                }''')

                            if clicked == 'clicked':
                                print("      ✅ 已点击选择数据按钮")
                                await asyncio.sleep(2)
                                before_selected_count = await frame.evaluate("""() => {
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const style = window.getComputedStyle(el);
                                        const rect = el.getBoundingClientRect();
                                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                    };
                                    const button = Array.from(document.querySelectorAll('button.ant-btn.ant-btn-primary'))
                                        .filter(isVisible)
                                        .find(b => ((b.textContent || '').replace(/\\s+/g, '')).includes('选择数据'));
                                    const scope = button ? (button.closest('.condition__right, .condition, .box') || button.parentElement) : document;
                                    const nodes = Array.from(scope.querySelectorAll('.ml-2, div, span')).filter(isVisible);
                                    const hit = nodes.find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                    return hit ? (hit.textContent || '').trim() : '';
                                }""")
                                if before_selected_count:
                                    print(f"      🧪 营运区确认前回读: {before_selected_count}")
                                
                                area_raw = data['main_operating_area']
                                area_targets = [x.strip() for x in re.split(r"[、，,|;\\n]+", area_raw) if x.strip()]
                                if not area_targets:
                                    area_targets = [area_raw.strip()]
                                area_targets = [normalize_area_for_step2(x) for x in area_targets if x]
                                print(f"      🔍 选择营运区: {', '.join(area_targets)}")

                                multi_select_result = await frame.evaluate("""async (targets) => {
                                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                                    const norm = (s) => (s || '').replace(/\\s+/g, '');
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const style = window.getComputedStyle(el);
                                        const rect = el.getBoundingClientRect();
                                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                    };
                                    const fireClick = (el) => {
                                        if (!el) return;
                                        ['pointerdown','mousedown','mouseup','click'].forEach(type => {
                                            el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                                        });
                                        if (typeof el.click === 'function') el.click();
                                    };
                                    const modals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root')).filter(isVisible);
                                    const pickerModal = modals.find(m => !!m.querySelector('.ant-tree, .ant-tree-list-holder-inner')) || null;
                                    if (!pickerModal) return { ok: false, reason: 'picker_modal_not_found', items: [] };
                                    const treeHolder = pickerModal.querySelector('.ant-tree-list-holder, .ant-tree-list, .ant-tree');

                                    const findNodeByText = (key) => {
                                        const keyNorm = norm(key);
                                        const nodes = Array.from(pickerModal.querySelectorAll('.ant-tree-treenode'));
                                        for (const n of nodes) {
                                            const title = n.querySelector('.ant-tree-title') || n.querySelector('[title]');
                                            const txt = norm((title?.textContent || '').trim());
                                            if (txt === keyNorm || txt.includes(keyNorm)) return n;
                                        }
                                        return null;
                                    };

                                    const findNodeByScroll = (key) => {
                                        if (treeHolder && typeof treeHolder.scrollTop === 'number') treeHolder.scrollTop = 0;
                                        for (let i = 0; i < 24; i += 1) {
                                            const node = findNodeByText(key);
                                            if (node) return node;
                                            if (!treeHolder || typeof treeHolder.scrollTop !== 'number') break;
                                            const nextTop = treeHolder.scrollTop + Math.max(120, Math.floor((treeHolder.clientHeight || 240) * 0.8));
                                            if (nextTop === treeHolder.scrollTop) break;
                                            treeHolder.scrollTop = nextTop;
                                        }
                                        return null;
                                    };

                                    const expandByName = async (name) => {
                                        const node = findNodeByText(name);
                                        if (!node) return false;
                                        const sw = node.querySelector('.ant-tree-switcher');
                                        if (sw && !sw.classList.contains('ant-tree-switcher_open')) {
                                            fireClick(sw);
                                            await sleep(350);
                                        }
                                        return true;
                                    };

                                    // 业务高频节点父链提示，避免单段名称（如“九江”）找不到。
                                    const parentHints = {
                                        '辽宁省区': ['北方大区'],
                                        '郑州': ['西北大区', '河南省区'],
                                        '大郑州营运区': ['西北大区', '河南省区'],
                                        '九江': ['华中大区', '江西省区'],
                                        '南昌': ['华中大区', '江西省区'],
                                        '广州二': ['华南大区', '广佛省区'],
                                        '肇庆': ['华南大区', '广佛省区'],
                                        '云浮': ['华南大区', '广佛省区'],
                                        '肇庆营运区': ['华南大区', '广佛省区'],
                                        '云浮营运区': ['华南大区', '广佛省区'],
                                    };

                                    const expandTopRegions = async () => {
                                        const roots = ['北方大区', '华中大区', '西北大区', '西南大区', '华南大区', '华东大区'];
                                        for (const r of roots) {
                                            await expandByName(r);
                                        }
                                    };

                                    const expandAllVisibleClosed = async (maxRounds = 4) => {
                                        for (let round = 0; round < maxRounds; round += 1) {
                                            const closedSwitchers = Array.from(
                                                pickerModal.querySelectorAll('.ant-tree-treenode .ant-tree-switcher.ant-tree-switcher_close')
                                            ).filter(isVisible);
                                            if (!closedSwitchers.length) break;
                                            let clicked = 0;
                                            for (const sw of closedSwitchers) {
                                                const node = sw.closest('.ant-tree-treenode');
                                                if (!node) continue;
                                                const title = node.querySelector('.ant-tree-title') || node.querySelector('[title]');
                                                // 优先展开中间层（大区/省区/营运区），避免展开过深太慢
                                                const t = norm((title?.textContent || '').trim());
                                                if (!(t.includes('大区') || t.includes('省区') || t.includes('营运区'))) continue;
                                                fireClick(sw);
                                                clicked += 1;
                                                if (clicked >= 12) break;
                                            }
                                            await sleep(300);
                                            if (!clicked) break;
                                        }
                                    };

                                    const items = [];
                                    for (const target of targets || []) {
                                        const segs = (target || '').split(/[\\-\\/、>|]/).map(s => (s || '').trim()).filter(Boolean);
                                        const leaf = segs.length ? segs[segs.length - 1] : target;
                                        const trace = [];
                                        for (const seg of segs.slice(0, -1)) {
                                            const parentNode = findNodeByText(seg);
                                            if (!parentNode) { trace.push('miss:' + seg); continue; }
                                            const sw = parentNode.querySelector('.ant-tree-switcher');
                                            if (sw && !sw.classList.contains('ant-tree-switcher_open')) {
                                                fireClick(sw);
                                                trace.push('expand:' + seg);
                                                await sleep(400);
                                            } else {
                                                trace.push('open:' + seg);
                                            }
                                        }
                                        // 单段目标优先按业务父链提示展开（如“九江”）
                                        if (segs.length <= 1) {
                                            const hints = parentHints[leaf] || [];
                                            for (const h of hints) {
                                                const ok = await expandByName(h);
                                                trace.push((ok ? 'expand_hint:' : 'miss_hint:') + h);
                                            }
                                        }

                                        const leafCandidates = Array.from(new Set([
                                            leaf,
                                            leaf.replace(/营运区$/, ''),
                                            leaf.replace(/省区$/, ''),
                                            leaf.replace(/大区$/, ''),
                                            leaf.includes('营运区') ? '' : (leaf + '营运区'),
                                        ].filter(Boolean)));
                                        const findNodeByCandidates = () => {
                                            for (const k of leafCandidates) {
                                                const n = findNodeByScroll(k);
                                                if (n) return { node: n, key: k };
                                            }
                                            return { node: null, key: '' };
                                        };

                                        let hit = findNodeByCandidates();
                                        let node = hit.node;
                                        // 仍找不到时，尝试先把根大区展开再搜索一次
                                        if (!node) {
                                            await expandTopRegions();
                                            trace.push('expand_roots');
                                            await sleep(300);
                                            hit = findNodeByCandidates();
                                            node = hit.node;
                                        }
                                        // 仍找不到，兜底：逐轮展开可见闭合节点，再搜索
                                        if (!node) {
                                            await expandAllVisibleClosed(5);
                                            trace.push('expand_visible_closed');
                                            await sleep(300);
                                            hit = findNodeByCandidates();
                                            node = hit.node;
                                        }
                                        if (!node) {
                                            items.push({ area: target, status: 'not_found', trace, tried: leafCandidates });
                                            continue;
                                        }
                                        if (hit.key && hit.key !== leaf) trace.push('leaf_fallback:' + hit.key);
                                        node.scrollIntoView({ block: 'center' });
                                        const cb = node.querySelector('.ant-tree-checkbox');
                                        if (!cb) {
                                            items.push({ area: target, status: 'checkbox_not_found', trace });
                                            continue;
                                        }
                                        if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                            fireClick(cb);
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) fireClick(cb.querySelector('.ant-tree-checkbox-inner'));
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) fireClick(cb.querySelector('.ant-tree-checkbox-input, input[type=\"checkbox\"]'));
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) fireClick(node.querySelector('.ant-tree-node-content-wrapper'));
                                        }
                                        items.push({ area: target, status: cb.classList.contains('ant-tree-checkbox-checked') ? 'checked' : 'click_no_effect', trace });
                                        await sleep(250);
                                    }
                                    return { ok: true, items };
                                }""", area_targets)

                                items = (multi_select_result or {}).get("items", []) if isinstance(multi_select_result, dict) else []
                                ok_items = [it for it in items if (it.get("status") in ("checked", "already_checked"))]
                                bad_items = [it for it in items if (it.get("status") not in ("checked", "already_checked"))]
                                for it in items:
                                    print(f"         选择结果: {it.get('area')} -> {it.get('status')} | trace={it.get('trace', [])}")
                                if bad_items:
                                    print(f"      ⚠️ 营运区未全部勾选成功: {[x.get('area') for x in bad_items]}")
                                    # 只关闭“选择数据”小弹窗，不关闭“编辑分群”大弹窗。
                                    confirm_area_result = await frame.evaluate("""() => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            const rect = el.getBoundingClientRect();
                                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                        };
                                        const norm = (s) => (s || '').replace(/\\s+/g, '');
                                        const modals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root')).filter(isVisible);
                                        const pickerModal = modals.find(m => !!m.querySelector('.ant-tree, .ant-tree-list-holder-inner')) || null;
                                        if (!pickerModal) return { ok: false, reason: 'picker_modal_not_found' };

                                        const btns = Array.from(pickerModal.querySelectorAll('button.ant-btn.ant-btn-primary')).filter(isVisible);
                                        const btn = btns.find(b => {
                                            const t = norm(b.textContent || '');
                                            return t === '确定' || t === '确 定';
                                        });
                                        if (!btn) return { ok: false, reason: 'picker_confirm_not_found' };

                                        btn.click();
                                        const pickerStillVisible = isVisible(pickerModal);
                                        const countNode = Array.from(document.querySelectorAll('.ml-2, div, span'))
                                            .filter(isVisible)
                                            .find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                        return {
                                            ok: true,
                                            pickerStillVisible,
                                            selectedCount: countNode ? (countNode.textContent || '').trim() : ''
                                        };
                                    }""")
                                    await asyncio.sleep(1.0)
                                    selected_count_text = await frame.evaluate("""() => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            const rect = el.getBoundingClientRect();
                                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                        };
                                        const button = Array.from(document.querySelectorAll('button.ant-btn.ant-btn-primary'))
                                            .filter(isVisible)
                                            .find(b => ((b.textContent || '').replace(/\\s+/g, '')).includes('选择数据'));
                                        const scope = button ? (button.closest('.condition__right, .condition, .box') || button.parentElement) : document;
                                        const nodes = Array.from(scope.querySelectorAll('.ml-2, div, span')).filter(isVisible);
                                        const hit = nodes.find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                        return hit ? (hit.textContent || '').trim() : '';
                                    }""")
                                    picker_still_visible = bool(confirm_area_result.get("pickerStillVisible"))
                                    selected_num = int(re.search(r'(\d+)', selected_count_text).group(1)) if selected_count_text and re.search(r'(\d+)', selected_count_text) else 0
                                    if confirm_area_result.get("ok") and selected_num > 0:
                                        print(f"      ✅ 营运区已确认: {selected_count_text}")
                                        if picker_still_visible:
                                            print("      ⚠️ 选择数据弹窗关闭状态未可靠识别，当前按已点击“确定”且已回读到已选条数放行")
                                        if len(ok_items) < len(area_targets):
                                            print(
                                                "      ⚠️ 节点逐项回读未全部命中，"
                                                f"但已选条数={selected_num}>0，按业务规则放行（目标命中 {len(ok_items)}/{len(area_targets)}）"
                                            )
                                        results["第2步-主消费营运区"] = True
                                    else:
                                        print(
                                            "      ⚠️ 营运区确认失败: "
                                            f"reason={confirm_area_result.get('reason','')}, "
                                            f"pickerStillVisible={picker_still_visible}, "
                                            f"selectedCountBefore={before_selected_count}, "
                                            f"selectedCountAfter={selected_count_text or confirm_area_result.get('selectedCount','')}, "
                                            f"selectedNum={selected_num}, "
                                            f"selectedAreas={len(ok_items)}/{len(area_targets)}"
                                        )
                            else:
                                # 兜底2：某些页面树已默认展开，直接尝试勾选
                                print("      ⚠️ 未找到选择数据按钮，尝试直接在当前树中勾选...")
                                area = data['main_operating_area']
                                selected_direct_result = await frame.evaluate("""
                                () => {
                                    const targetArea = '""" + area_escaped + """';
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const style = window.getComputedStyle(el);
                                        const rect = el.getBoundingClientRect();
                                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                    };
                                    const modalCandidates = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root'))
                                        .filter(isVisible)
                                        .map(el => ({
                                            el,
                                            area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
                                            hasTree: !!el.querySelector('.ant-tree, .ant-tree-list-holder-inner'),
                                        }))
                                        .filter(x => x.hasTree)
                                        .sort((a, b) => a.area - b.area);
                                    const pickerModal = modalCandidates.length ? modalCandidates[0].el : null;
                                    if (!pickerModal) return { status: 'picker_modal_not_found', matched: false };
                                    const fireClick = (el) => {
                                        if (!el) return;
                                        ['pointerdown', 'mousedown', 'mouseup', 'click'].forEach(type => {
                                            el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                                        });
                                        if (typeof el.click === 'function') el.click();
                                    };
                                    const nodes = Array.from(pickerModal.querySelectorAll('.ant-tree-treenode'));
                                    for (const n of nodes) {
                                        const title = n.querySelector('.ant-tree-title') || n.querySelector('[title]');
                                        const txt = (title?.textContent || '').trim();
                                        const segs = (targetArea || '')
                                            .split(/[\\-\\/、>|]/)
                                            .map(s => (s || '').trim())
                                            .filter(Boolean);
                                        const leaf = segs.length ? segs[segs.length - 1] : targetArea;
                                        if (!(txt === leaf || txt.includes(leaf))) continue;
                                        n.scrollIntoView({ block: 'center' });
                                        const cb = n.querySelector('.ant-tree-checkbox');
                                        if (!cb) return { status: 'checkbox_not_found', matched: true };
                                        if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                            fireClick(cb);
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                                const inner = cb.querySelector('.ant-tree-checkbox-inner');
                                                fireClick(inner);
                                            }
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                                const titleWrap = n.querySelector('.ant-tree-node-content-wrapper');
                                                fireClick(titleWrap);
                                            }
                                        }
                                        return {
                                            status: cb.classList.contains('ant-tree-checkbox-checked') ? 'checked' : 'click_no_effect',
                                            matched: true
                                        };
                                    }
                                    return { status: 'not_found', matched: false };
                                }
                                """)
                                selected_direct = selected_direct_result.get('status') if isinstance(selected_direct_result, dict) else selected_direct_result
                                matched_direct_area_node = bool(selected_direct_result.get('matched')) if isinstance(selected_direct_result, dict) else selected_direct == "checked"
                                if matched_direct_area_node:
                                    if selected_direct == "checked":
                                        print(f"      ✅ 已直接勾选营运区: {area}")
                                    else:
                                        print(f"      ⚠️ 直接勾选状态未确认，继续尝试小弹窗确定并用已选条数校验: {area} ({selected_direct})")
                                    before_selected_count = await frame.evaluate("""() => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            const rect = el.getBoundingClientRect();
                                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                        };
                                        const button = Array.from(document.querySelectorAll('button.ant-btn.ant-btn-primary'))
                                            .filter(isVisible)
                                            .find(b => ((b.textContent || '').replace(/\\s+/g, '')).includes('选择数据'));
                                        const scope = button ? (button.closest('.condition__right, .condition, .box') || button.parentElement) : document;
                                        const nodes = Array.from(scope.querySelectorAll('.ml-2, div, span')).filter(isVisible);
                                        const hit = nodes.find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                        return hit ? (hit.textContent || '').trim() : '';
                                    }""")
                                    if before_selected_count:
                                        print(f"      🧪 营运区确认前回读: {before_selected_count}")
                                    confirm_area_result = await frame.evaluate("""() => {
                                        const norm = (s) => (s || '').replace(/\\s+/g, '');
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            const rect = el.getBoundingClientRect();
                                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                        };
                                        const textOf = (el) => norm(el?.textContent || '');
                                        const modalCandidates = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root'))
                                            .filter(isVisible)
                                            .map(el => ({
                                                el,
                                                area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
                                                hasTree: !!el.querySelector('.ant-tree, .ant-tree-list-holder-inner'),
                                            }))
                                            .filter(x => x.hasTree)
                                            .sort((a, b) => a.area - b.area);
                                        const pickerModal = modalCandidates.length ? modalCandidates[0].el : null;
                                        if (!pickerModal) {
                                            return { ok: false, reason: 'picker_modal_not_found' };
                                        }
                                        const btn = Array.from(pickerModal.querySelectorAll('button.ant-btn.ant-btn-primary'))
                                            .find(b => {
                                                const t = textOf(b);
                                                return t === '确定' || t === '确 定';
                                            });
                                        if (!btn) {
                                            return { ok: false, reason: 'picker_confirm_not_found' };
                                        }
                                        btn.click();
                                        const pickerStillVisible = isVisible(pickerModal);
                                        const countNode = Array.from(document.querySelectorAll('.condition, .box, .ant-form-item, div'))
                                            .filter(isVisible)
                                            .map(node => node.querySelector('.ml-2') || node)
                                            .find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                        return {
                                            ok: true,
                                            pickerStillVisible,
                                            selectedCount: countNode ? (countNode.textContent || '').trim() : ''
                                        };
                                    }""")
                                    await asyncio.sleep(1.0)
                                    selected_count_text = await frame.evaluate("""() => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            const rect = el.getBoundingClientRect();
                                            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                        };
                                        const button = Array.from(document.querySelectorAll('button.ant-btn.ant-btn-primary'))
                                            .filter(isVisible)
                                            .find(b => ((b.textContent || '').replace(/\\s+/g, '')).includes('选择数据'));
                                        const scope = button ? (button.closest('.condition__right, .condition, .box') || button.parentElement) : document;
                                        const nodes = Array.from(scope.querySelectorAll('.ml-2, div, span')).filter(isVisible);
                                        const hit = nodes.find(n => /已选[:：]\\s*\\d+/.test((n.textContent || '').trim()));
                                        return hit ? (hit.textContent || '').trim() : '';
                                    }""")
                                    picker_still_visible = bool(confirm_area_result.get("pickerStillVisible"))
                                    selected_num = int(re.search(r'(\d+)', selected_count_text).group(1)) if selected_count_text and re.search(r'(\d+)', selected_count_text) else 0
                                    if confirm_area_result.get("ok") and selected_num > 0:
                                        print(f"      ✅ 营运区已确认: {selected_count_text}")
                                        if picker_still_visible:
                                            print("      ⚠️ 选择数据弹窗关闭状态未可靠识别，当前按已点击“确定”且已回读到已选条数放行")
                                        results["第2步-主消费营运区"] = True
                                    else:
                                        print(
                                            "      ⚠️ 营运区确认失败: "
                                            f"reason={confirm_area_result.get('reason','')}, "
                                            f"pickerStillVisible={picker_still_visible}, "
                                            f"selectedCountBefore={before_selected_count}, "
                                            f"selectedCountAfter={selected_count_text or confirm_area_result.get('selectedCount','')}, "
                                            f"selectedNum={selected_num}"
                                        )
                                else:
                                    print(f"      ⚠️ 直接勾选失败: {selected_direct}，请检查第2步页面是否空白/未加载完整")
                        except Exception as e:
                            if "__skip_main_operating_area__" in str(e):
                                pass
                            else:
                                print(f"      ⚠️ 主消费营运区操作失败: {e}")
                    
                    # 第2步：门店信息通用上传（选择数据 -> 上传文件，非必填）
                    # 规则：当主消费营运区已配置且非《书名号引用》时，仅走“区域选择”逻辑，不再执行门店上传兜底。
                    main_area_raw = (data.get("main_operating_area", "") or "").strip()
                    main_area_is_sheet_ref = bool(re.match(r"^《[^》]+》$", main_area_raw))
                    skip_step2_store_upload = bool(main_area_raw) and (not main_area_is_sheet_ref)

                    step2_store_file_path = (data.get("step2_store_file_path", "") or data.get("main_store_file_path", "")).strip()
                    if skip_step2_store_upload and step2_store_file_path:
                        print("   🏬 第2步门店信息文件: ⏭️ 已跳过（主消费营运区走区域选择，不走门店上传）")
                    elif step2_store_file_path:
                        print(f"   🏬 第2步门店信息文件: {step2_store_file_path}")
                        try:
                            store_path = Path(os.path.expanduser(step2_store_file_path))
                            if not store_path.is_absolute():
                                store_path = Path.cwd() / store_path
                            if (not store_path.exists()) or store_path.suffix.lower() not in {".xlsx", ".xls"}:
                                print(f"      ⚠️ 第2步门店信息文件无效: {store_path}")
                            else:
                                # 当文件是《xxx》门店引用时，行类型常默认停留在“主消费营运区”，
                                # 需要先切换到“主消费门店/主要消费门店”，否则会打开树弹窗而非上传弹窗。
                                try:
                                    switch_store_row = await frame.evaluate("""() => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const s = window.getComputedStyle(el);
                                            const r = el.getBoundingClientRect();
                                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                        };
                                        const norm = (s) => (s || '').replace(/\\s+/g, '');
                                        const fire = (el) => {
                                            if (!el) return false;
                                            ['pointerdown','mousedown','mouseup','click'].forEach(t => {
                                                el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                                            });
                                            if (typeof el.click === 'function') el.click();
                                            return true;
                                        };
                                        const rows = Array.from(document.querySelectorAll('.condition, .event-row, .ant-form-item, .ant-row, div'))
                                            .filter(isVisible);
                                        const findPickBtn = (row) =>
                                            Array.from(row.querySelectorAll('button.ant-btn.ant-btn-primary, button.ant-btn'))
                                                .filter(isVisible)
                                                .find(b => norm(b.textContent || '').includes('选择数据'));
                                        const targetRow =
                                            rows.find(r => {
                                                const t = norm(r.textContent || '');
                                                return (t.includes('主消费') || t.includes('主要消费')) && !!findPickBtn(r);
                                            }) ||
                                            rows.find(r => !!findPickBtn(r)) ||
                                            null;
                                        if (!targetRow) return { ok: false, mode: 'row_not_found' };

                                        const currentLabelNode =
                                            targetRow.querySelector('.ant-select-selection-item[title]') ||
                                            targetRow.querySelector('.ant-select-selection-item');
                                        const currentLabel = norm((currentLabelNode?.getAttribute('title') || currentLabelNode?.textContent || ''));
                                        if (currentLabel && currentLabel.includes('门店')) {
                                            return { ok: true, mode: 'already_store', current: currentLabel };
                                        }

                                        const selectBox = targetRow.querySelector('.ant-select-selector, .ant-select');
                                        if (!selectBox) return { ok: false, mode: 'select_not_found', current: currentLabel };
                                        fire(selectBox);

                                        const dropdowns = Array.from(document.querySelectorAll('.ant-select-dropdown')).filter(isVisible);
                                        const dd = dropdowns[dropdowns.length - 1] || null;
                                        if (!dd) return { ok: false, mode: 'dropdown_not_found', current: currentLabel };

                                        const items = Array.from(dd.querySelectorAll('.ant-select-item-option, .ant-select-item'))
                                            .filter(isVisible);
                                        let target = null;
                                        // 优先精确
                                        target = items.find(i => {
                                            const t = norm(i.textContent || '');
                                            return t.includes('主要消费门店') || t.includes('主消费门店');
                                        });
                                        // 兜底：同分组下任一“门店”选项
                                        if (!target) {
                                            target = items.find(i => {
                                                const t = norm(i.textContent || '');
                                                return t.includes('门店') && (t.includes('消费') || t.includes('入会') || t.includes('至尊'));
                                            });
                                        }
                                        if (!target) return { ok: false, mode: 'store_option_not_found', current: currentLabel };
                                        fire(target);
                                        const afterNode =
                                            targetRow.querySelector('.ant-select-selection-item[title]') ||
                                            targetRow.querySelector('.ant-select-selection-item');
                                        const afterLabel = norm((afterNode?.getAttribute('title') || afterNode?.textContent || ''));
                                        return { ok: true, mode: 'switched_to_store', current: currentLabel, after: afterLabel };
                                    }""")
                                    if switch_store_row:
                                        if switch_store_row.get("mode") == "switched_to_store":
                                            print(f"      🧪 门店信息行类型切换: {switch_store_row.get('current','')} -> {switch_store_row.get('after','')}")
                                        elif switch_store_row.get("mode") == "already_store":
                                            print(f"      🧪 门店信息行类型: 已是门店 ({switch_store_row.get('current','')})")
                                except Exception:
                                    pass

                                open_store_picker_info = await frame.evaluate("""() => {
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const s = window.getComputedStyle(el);
                                        const r = el.getBoundingClientRect();
                                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                    };
                                    const norm = (s) => (s || '').replace(/\\s+/g, '');
                                    const fireClick = (el) => {
                                        if (!el) return false;
                                        ['pointerdown','mousedown','mouseup','click'].forEach(t => {
                                            el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                                        });
                                        if (typeof el.click === 'function') el.click();
                                        return true;
                                    };
                                    const visibleModals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root')).filter(isVisible);
                                    const openedModal = visibleModals.find(m => {
                                        const t = norm(m.textContent || '');
                                        return t.includes('选择数据') && t.includes('上传文件');
                                    });
                                    if (openedModal) {
                                        openedModal.setAttribute('data-step2-store-modal', '1');
                                        return { opened: true, source: 'already_open' };
                                    }
                                    const keywordHints = [
                                        '入会门店','入会片区','入会营运区','入会大区','入会省区',
                                        '至尊升级门店','至尊升级片区','至尊升级营运区','至尊升级大区','至尊升级省区',
                                        '至尊续费门店','至尊续费片区','至尊续费营运区','至尊续费大区','至尊续费省区',
                                        '会员通绑定门店','会员通绑定片区','会员通绑定营运区','会员通绑定大区','会员通绑定省区',
                                        '最后消费门店','最后消费片区','最后消费营运区','最后消费大区','最后消费省区',
                                        '主消费门店','主消费片区','主消费营运区','主消费大区','主消费省区',
                                        '主要消费门店','主要消费片区','主要消费营运区','主要消费大区','主要消费省区',
                                        '消费过的门店','消费过的片区','消费过的营运区','消费过的大区','消费过的省区'
                                    ];
                                    const rows = Array.from(document.querySelectorAll('.condition, .event-row, .ant-form-item, .ant-row, div')).filter(isVisible);
                                    for (const row of rows) {
                                        const txt = norm(row.textContent || '');
                                        if (!keywordHints.some(k => txt.includes(norm(k)))) continue;
                                        const btn = Array.from(row.querySelectorAll('button.ant-btn.ant-btn-primary, button.ant-btn'))
                                            .find(b => norm(b.textContent || '').includes('选择数据'));
                                        if (btn) return { opened: fireClick(btn), source: 'keyword_row_button' };
                                    }
                                    // 通用兜底：点击当前可见的第一个“选择数据”按钮（适配任意门店信息类型）
                                    const firstBtn = Array.from(document.querySelectorAll('button.ant-btn.ant-btn-primary, button.ant-btn'))
                                        .filter(isVisible)
                                        .find(b => norm(b.textContent || '').includes('选择数据'));
                                    if (firstBtn) return { opened: fireClick(firstBtn), source: 'first_select_data' };
                                    return { opened: false, source: 'not_found' };
                                }""")
                                if not open_store_picker_info or (not open_store_picker_info.get("opened")):
                                    print("      ⚠️ 未找到门店信息“选择数据”按钮")
                                else:
                                    print(f"      🧪 门店信息选择器来源: {open_store_picker_info.get('source','unknown')}")
                                    await asyncio.sleep(0.6)
                                    modal_pick_info = {"ok": False, "source": "store_modal_not_found"}
                                    for _ in range(20):
                                        modal_pick_info = await frame.evaluate("""() => {
                                            const isVisible = (el) => {
                                                if (!el) return false;
                                                const s = window.getComputedStyle(el);
                                                const r = el.getBoundingClientRect();
                                                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                            };
                                            const norm = (s) => (s || '').replace(/\\s+/g, '');
                                            const visibleModals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root')).filter(isVisible);
                                            const openedModal = visibleModals.find(m => {
                                                const t = norm(m.textContent || '');
                                                return t.includes('选择数据') && t.includes('上传文件');
                                            });
                                            if (openedModal) {
                                                openedModal.setAttribute('data-step2-store-modal', '1');
                                                return { ok: true, source: 'store_select_data_modal' };
                                            }
                                            return { ok: false, source: 'store_modal_not_found' };
                                        }""")
                                        if modal_pick_info and modal_pick_info.get("ok"):
                                            break
                                        await asyncio.sleep(0.15)
                                    # 优先用可见 modal 内的 file input 直接上传
                                    uploaded_store = False
                                    try:
                                        file_input = frame.locator('[data-step2-store-modal=\"1\"] input[type=\"file\"]').last
                                        if await file_input.count() > 0:
                                            await file_input.set_input_files(str(store_path))
                                            uploaded_store = True
                                    except Exception:
                                        uploaded_store = False

                                    if not uploaded_store:
                                        try:
                                            # 兜底：点击“上传文件”后重取 input[type=file]，仅走 set_input_files，不触发系统文件夹
                                            await frame.evaluate("""() => {
                                                const isVisible = (el) => {
                                                    if (!el) return false;
                                                    const s = window.getComputedStyle(el);
                                                    const r = el.getBoundingClientRect();
                                                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                                };
                                                const norm = (s) => (s || '').replace(/\\s+/g, '');
                                                const modal = document.querySelector('[data-step2-store-modal=\"1\"]');
                                                const scope = modal || document;
                                                const btn = Array.from(scope.querySelectorAll('button.ant-btn'))
                                                    .filter(isVisible)
                                                    .find(b => {
                                                        const t = norm(b.textContent || '');
                                                        return t === '上传文件' || t.includes('上传文件');
                                                    });
                                                if (btn) btn.click();
                                            }""")
                                            await asyncio.sleep(0.4)
                                            file_input2 = frame.locator('[data-step2-store-modal=\"1\"] input[type=\"file\"]').last
                                            if await file_input2.count() > 0:
                                                await file_input2.set_input_files(str(store_path))
                                                uploaded_store = True
                                        except Exception:
                                            uploaded_store = False

                                    if not uploaded_store:
                                        print(f"      ⚠️ 主消费门店上传失败: {store_path.name}")
                                    else:
                                        # 上传后等待“已选中(N)”生效，避免过早点击确认导致 N=0
                                        selected_ready = False
                                        selected_text = ""
                                        file_ready = False
                                        for _ in range(40):  # 最多等待约20秒
                                            ready_info = await frame.evaluate("""(fileName) => {
                                                const isVisible = (el) => {
                                                    if (!el) return false;
                                                    const s = window.getComputedStyle(el);
                                                    const r = el.getBoundingClientRect();
                                                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                                };
                                                const norm = (s) => (s || '').replace(/\\s+/g, '');
                                                const modal = document.querySelector('[data-step2-store-modal=\"1\"]');
                                                const scope = modal || document;
                                                const txt = (scope.textContent || '').trim();
                                                const txtNorm = norm(txt);
                                                // 直接从整段文本解析“已选中(数字)”更稳
                                                let selectedText = '';
                                                const m1 = txt.match(/已选中\\s*[（(]\\s*\\d+\\s*[)）]/);
                                                if (m1) selectedText = m1[0];
                                                if (!selectedText) {
                                                    const m2 = txt.match(/已选中\\s*\\d+/);
                                                    if (m2) selectedText = m2[0];
                                                }
                                                const fileNorm = norm(fileName || '');
                                                const fileHit = !!(fileNorm && txtNorm.includes(fileNorm));
                                                return { selectedText, fileHit };
                                            }""", store_path.name)
                                            selected_text = (ready_info or {}).get("selectedText", "")
                                            file_ready = bool((ready_info or {}).get("fileHit"))
                                            m = re.search(r'(\\d+)', selected_text or "")
                                            n = int(m.group(1)) if m else 0
                                            if n > 0 or file_ready:
                                                selected_ready = True
                                                break
                                            await asyncio.sleep(0.5)
                                        if selected_text:
                                            print(f"      🧪 门店信息上传后回读: {selected_text}")
                                        if file_ready:
                                            print("      🧪 门店信息上传后回读: 已检测到上传文件名")
                                        if not selected_ready:
                                            print("      ⚠️ 门店信息已选中数量仍为0，继续尝试点击确认（可能后台仍在处理）")

                                        # 点击选择数据弹窗“确认/确定”
                                        confirm_store = await frame.evaluate("""() => {
                                            const isVisible = (el) => {
                                                if (!el) return false;
                                                const s = window.getComputedStyle(el);
                                                const r = el.getBoundingClientRect();
                                                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                            };
                                            const norm = (s) => (s || '').replace(/\\s+/g, '');
                                            const modal = document.querySelector('[data-step2-store-modal=\"1\"]');
                                            const scope = modal || document;
                                            const primaryBtns = Array.from(scope.querySelectorAll('button.ant-btn.ant-btn-primary')).filter(isVisible);
                                            const btn = primaryBtns.find(b => {
                                                const t = norm(b.textContent || '');
                                                return t === '确认' || t.includes('确认') || t === '确定' || t.includes('确定');
                                            });
                                            if (!btn) return false;
                                            btn.click();
                                            return true;
                                        }""")
                                        if confirm_store:
                                            print(f"      ✅ 第2步门店信息已上传: {store_path.name}")
                                            results["第2步-主消费门店"] = True
                                        else:
                                            print("      ⚠️ 门店信息上传后未找到确认/确定按钮")
                        except Exception as e:
                            print(f"      ⚠️ 第2步门店信息操作失败: {e}")
                    else:
                        results["第2步-主消费门店"] = True

                    # 第2步：商品编码上传（与门店信息同链路：选择数据 -> 直接写 file input -> 确认）
                    step2_product_file_path = (data.get("step2_product_file_path", "") or "").strip()
                    if step2_product_file_path:
                        print(f"   🧾 第2步商品编码文件: {step2_product_file_path}")
                        try:
                            product_path = Path(os.path.expanduser(step2_product_file_path))
                            if not product_path.is_absolute():
                                product_path = Path.cwd() / product_path
                            if (not product_path.exists()) or product_path.suffix.lower() not in {".xlsx", ".xls"}:
                                print(f"      ⚠️ 第2步商品编码文件无效: {product_path}")
                            else:
                                open_product_picker_info = await frame.evaluate("""() => {
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const s = window.getComputedStyle(el);
                                        const r = el.getBoundingClientRect();
                                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                    };
                                    const norm = (s) => (s || '').replace(/\\s+/g, '');
                                    const fireClick = (el) => {
                                        if (!el) return false;
                                        ['pointerdown','mousedown','mouseup','click'].forEach(t => {
                                            el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                                        });
                                        if (typeof el.click === 'function') el.click();
                                        return true;
                                    };
                                    const pickBtnFromRow = (row) => {
                                        if (!row || !isVisible(row)) return null;
                                        const btns = Array.from(row.querySelectorAll('button.ant-btn.ant-btn-primary, button.ant-btn'))
                                            .filter(isVisible)
                                            .filter(b => norm(b.textContent || '').includes('选择数据'));
                                        return btns.length ? btns[0] : null;
                                    };
                                    // 清理历史标记
                                    Array.from(document.querySelectorAll('[data-step2-product-modal="1"]')).forEach(n => n.removeAttribute('data-step2-product-modal'));
                                    // 优先1：从 title="商品编码" 节点反向找最近行，避免误点到“主消费门店”行
                                    const titleNodes = Array.from(document.querySelectorAll('.ant-select-selection-item[title="商品编码"], [title="商品编码"]'))
                                        .filter(isVisible);
                                    const exactRows = [];
                                    for (const node of titleNodes) {
                                        const row = node.closest('.event-row, .condition, .ant-form-item, .ant-row');
                                        if (row && isVisible(row) && !exactRows.includes(row)) exactRows.push(row);
                                    }
                                    // 先点“已选：0”的商品编码行，避免重复点到已选392的门店行
                                    for (const row of exactRows) {
                                        const txt = (row.textContent || '').trim();
                                        if (!/已选[:：]\\s*0/.test(txt)) continue;
                                        const btn = pickBtnFromRow(row);
                                        if (btn) return { opened: fireClick(btn), source: 'product_row_title_selected0' };
                                    }
                                    // 再点任意商品编码行
                                    for (const row of exactRows) {
                                        const btn = pickBtnFromRow(row);
                                        if (btn) return { opened: fireClick(btn), source: 'product_row_title' };
                                    }
                                    // 优先2：文本命中“商品编码”的行（仍限定行级别）
                                    const rows = Array.from(document.querySelectorAll('.event-row, .condition, .ant-form-item, .ant-row')).filter(isVisible);
                                    for (const row of rows) {
                                        const txt = norm(row.textContent || '');
                                        if (!txt.includes('商品编码')) continue;
                                        const btn = pickBtnFromRow(row);
                                        if (btn) return { opened: fireClick(btn), source: 'product_row_text' };
                                    }
                                    return { opened: false, source: 'product_row_not_found' };
                                }""")
                                if not open_product_picker_info or (not open_product_picker_info.get("opened")):
                                    print("      ⚠️ 未找到商品编码“选择数据”按钮")
                                else:
                                    print(f"      🧪 商品编码选择器来源: {open_product_picker_info.get('source','unknown')}")
                                    # 等待“商品编码”弹窗出现（按表头识别，不点击上传按钮，避免系统文件夹）
                                    modal_pick_info = {"ok": False, "source": "wait_visible_modal"}
                                    for _ in range(20):
                                        modal_pick_info = await frame.evaluate("""() => {
                                            const isVisible = (el) => {
                                                if (!el) return false;
                                                const s = window.getComputedStyle(el);
                                                const r = el.getBoundingClientRect();
                                                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                            };
                                            const norm = (s) => (s || '').replace(/\\s+/g, '');
                                            const visibleModals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-root')).filter(isVisible);
                                            const hasHeader = (modal, key) => {
                                                if (!modal || !key) return false;
                                                const nodes = Array.from(modal.querySelectorAll('th, td, label, span, div'));
                                                return nodes.some(n => norm(n.textContent || '').includes(key));
                                            };
                                            const candidates = visibleModals.filter(m => {
                                                const t = norm(m.textContent || '');
                                                if (!(t.includes('选择数据') && t.includes('上传文件'))) return false;
                                                // 商品编码弹窗：必须出现“商品编码”表头/字段；并排除“门店编码”弹窗
                                                const isProduct = hasHeader(m, '商品编码');
                                                const isStore = hasHeader(m, '门店编码');
                                                return isProduct && !isStore;
                                            });
                                            if (!candidates.length) return { ok: false, source: 'wait_visible_modal' };
                                            const modal = candidates[candidates.length - 1];
                                            modal.setAttribute('data-step2-product-modal', '1');
                                            return { ok: true, source: 'product_header_modal' };
                                        }""")
                                        if modal_pick_info.get("ok"):
                                            break
                                        await asyncio.sleep(0.25)

                                    product_modal_count = await frame.locator('[data-step2-product-modal="1"]').count()
                                    if product_modal_count <= 0:
                                        print("      ⚠️ 未识别到商品编码上传弹窗（表头未命中“商品编码”）")
                                    else:
                                        print(f"      🧪 商品编码弹窗识别: {modal_pick_info.get('source','unknown')}")
                                        uploaded_product = False
                                        try:
                                            file_input = frame.locator('[data-step2-product-modal="1"] input[type="file"]').last
                                            if await file_input.count() > 0:
                                                await file_input.set_input_files(str(product_path))
                                                uploaded_product = True
                                        except Exception:
                                            uploaded_product = False

                                        if not uploaded_product:
                                            print(f"      ⚠️ 商品编码上传失败: {product_path.name}")
                                        else:
                                            # 等待弹窗内“已选中(N)”生效
                                            selected_text = ""
                                            for _ in range(40):
                                                selected_text = await frame.evaluate("""() => {
                                                    const modal = document.querySelector('[data-step2-product-modal="1"]');
                                                    const txt = (modal ? modal.textContent : document.textContent) || '';
                                                    const m1 = txt.match(/已选中\\s*[（(]\\s*\\d+\\s*[)）]/);
                                                    if (m1) return m1[0];
                                                    const m2 = txt.match(/已选中\\s*\\d+/);
                                                    return m2 ? m2[0] : '';
                                                }""")
                                                m = re.search(r'(\\d+)', selected_text or "")
                                                n = int(m.group(1)) if m else 0
                                                if n > 0:
                                                    break
                                                await asyncio.sleep(0.5)
                                            if selected_text:
                                                print(f"      🧪 商品编码上传后回读: {selected_text}")

                                            confirm_product = await frame.evaluate("""() => {
                                                const isVisible = (el) => {
                                                    if (!el) return false;
                                                    const s = window.getComputedStyle(el);
                                                    const r = el.getBoundingClientRect();
                                                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                                };
                                                const norm = (s) => (s || '').replace(/\\s+/g, '');
                                                const modal = document.querySelector('[data-step2-product-modal="1"]');
                                                const scope = modal || document;
                                                let btn = Array.from(scope.querySelectorAll('button.ant-btn.ant-btn-primary, button.ant-btn'))
                                                    .filter(isVisible)
                                                    .find(b => {
                                                        const t = norm(b.textContent || '');
                                                        return t === '确认' || t.includes('确认') || t === '确定' || t.includes('确定');
                                                    });
                                                // 兜底：优先点击弹窗 footer 里的主按钮（通常就是“确认/确定”）
                                                if (!btn) {
                                                    const footerPrimary = Array.from(scope.querySelectorAll('.ant-modal-footer button.ant-btn.ant-btn-primary'))
                                                        .filter(isVisible);
                                                    if (footerPrimary.length) btn = footerPrimary[footerPrimary.length - 1];
                                                }
                                                if (!btn) return { ok: false, text: '' };
                                                const txt = (btn.textContent || '').trim();
                                                ['pointerdown','mousedown','mouseup','click'].forEach(t => {
                                                    btn.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window }));
                                                });
                                                if (typeof btn.click === 'function') btn.click();
                                                return { ok: true, text: txt };
                                            }""")
                                            if confirm_product and confirm_product.get("ok"):
                                                print(f"      🧪 商品编码确认动作: 已点击按钮 [{(confirm_product.get('text') or '').strip()}]")
                                                await asyncio.sleep(0.6)
                                                # 只读“商品编码”行本身的“已选”，避免串读其它区域
                                                product_row_selected = ""
                                                n = 0
                                                for _ in range(12):
                                                    product_row_selected = await frame.evaluate("""() => {
                                                        const isVisible = (el) => {
                                                            if (!el) return false;
                                                            const s = window.getComputedStyle(el);
                                                            const r = el.getBoundingClientRect();
                                                            return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                                                        };
                                                        const norm = (s) => (s || '').replace(/\\s+/g, '');
                                                        const rows = Array.from(document.querySelectorAll('.event-row, .condition')).filter(isVisible);
                                                        for (const row of rows) {
                                                            const hasTitle = !!row.querySelector('.ant-select-selection-item[title="商品编码"], [title="商品编码"]');
                                                            const txt = norm(row.textContent || '');
                                                            if (!hasTitle && !txt.includes('商品编码')) continue;
                                                            const direct = row.querySelector('.ml-2');
                                                            const val = (direct && (direct.textContent || '').trim()) || '';
                                                            if (/已选[:：]\\s*\\d+/.test(val)) return val;
                                                        }
                                                        return '';
                                                    }""")
                                                    m = re.search(r'(\\d+)', product_row_selected or "")
                                                    n = int(m.group(1)) if m else 0
                                                    if n > 0:
                                                        break
                                                    await asyncio.sleep(0.3)
                                                if product_row_selected:
                                                    print(f"      🧪 商品编码行回读: {product_row_selected}")
                                                if n > 0:
                                                    print(f"      ✅ 第2步商品编码已上传: {product_path.name}")
                                                    results["第2步-商品编码"] = True
                                                else:
                                                    print("      ⚠️ 商品编码行回读为0，判定未生效")
                                            else:
                                                print("      ⚠️ 商品编码上传后未找到确认/确定按钮")
                        except Exception as e:
                            print(f"      ⚠️ 第2步商品编码操作失败: {e}")
                    else:
                        results["第2步-商品编码"] = True

                    # 在 iframe 内填充券规则ID（按标签就近定位 + 回读）
                    if data.get("coupon_ids"):
                        print(f"   🎫 券规则ID: {data['coupon_ids']}")
                        if not step2_has_coupon_row:
                            print("      ⏭️ 当前页面未检测到“券规则ID”字段，自动跳过")
                            results["第2步-券规则ID"] = True
                        else:
                            try:
                                coupon_val = data["coupon_ids"]
                                coupon_result = await frame.evaluate("""(val) => {
                                    const isVisible = (el) => {
                                        if (!el) return false;
                                        const style = window.getComputedStyle(el);
                                        const rect = el.getBoundingClientRect();
                                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                                    };
                                    const write = (inp, v) => {
                                        if (!inp) return '';
                                        try { inp.scrollIntoView({ block: 'center' }); } catch(e) {}
                                        inp.focus();
                                        inp.value = v;
                                        inp.setAttribute('value', v);
                                        inp.dispatchEvent(new Event('input', { bubbles: true }));
                                        inp.dispatchEvent(new Event('keyup', { bubbles: true }));
                                        inp.dispatchEvent(new Event('change', { bubbles: true }));
                                        inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                                        inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
                                        inp.blur();
                                        return ((inp.value || '').trim());
                                    };
                                    const targets = [];
                                    const pushUnique = (inp) => {
                                        if (!inp) return;
                                        if (targets.includes(inp)) return;
                                        if (inp.disabled || inp.readOnly) return;
                                        targets.push(inp);
                                    };
                                    // 优先：精准命中“券规则ID”对应的 event-row，收集全部输入框
                                    const preciseRows = Array.from(document.querySelectorAll('.event-row'))
                                        .filter(r => isVisible(r) && r.querySelector('.ant-select-selection-item[title="券规则ID"]'));
                                    for (const row of preciseRows) {
                                        const rowInputs = Array.from(row.querySelectorAll('.box input.ant-input, .box input[type="text"], .box input, input.ant-input, input[type="text"], input'));
                                        rowInputs.forEach(pushUnique);
                                    }
                                    if (!targets.length) {
                                        // 兜底：在含“券规则ID”文本的可见块内找可写 input，并全部写入
                                        const rows = Array.from(document.querySelectorAll('.event-row, .ant-row, .ant-form-item, div')).filter(isVisible);
                                        for (const row of rows) {
                                            const txt = (row.textContent || '').replace(/\\s+/g, '');
                                            if (!txt.includes('券规则ID')) continue;
                                            const inputs = Array.from(row.querySelectorAll('input.ant-input, input[type="text"], input'))
                                                .filter(inp => !inp.disabled && !inp.readOnly);
                                            inputs.forEach(pushUnique);
                                        }
                                    }
                                    if (!targets.length) return { ok: false, readback: '', mode: 'not_found', total: 0, success: 0 };

                                    const readbacks = [];
                                    for (const inp of targets) {
                                        const rb = write(inp, val);
                                        readbacks.push(rb || '');
                                    }
                                    const success = readbacks.filter(x => (x || '').trim() === (val || '').trim()).length;
                                    const mode = preciseRows.length ? 'precise_event_row' : 'fallback_row';
                                    return { ok: success === targets.length, readback: readbacks.join(' | '), mode, total: targets.length, success };
                                }""", coupon_val)
                                coupon_ok = bool(coupon_result and coupon_result.get("ok"))
                                if coupon_ok:
                                    total = coupon_result.get("total", 1)
                                    print(f"      ✅ 已填充券规则ID（共{total}处）")
                                    results["第2步-券规则ID"] = True
                                else:
                                    if (coupon_result or {}).get("mode") == "not_found":
                                        print("      ⏭️ 券规则ID字段未找到，自动跳过")
                                        results["第2步-券规则ID"] = True
                                    else:
                                        print(
                                            f"      ⚠️ 券规则ID回读不一致: mode={coupon_result.get('mode','')}, "
                                            f"success={coupon_result.get('success',0)}/{coupon_result.get('total',0)}, "
                                            f"readback={coupon_result.get('readback','')}"
                                        )
                            except Exception as e:
                                print(f"      ⚠️ 券规则ID填充失败: {e}")

                else:
                    print("   ⚠️ 无法获取 frame 内容")
            else:
                print("   ⚠️ 未找到 iframe 元素")
        except Exception as e:
            print(f"   ⚠️ iframe 操作失败: {e}")
            step2_error = str(e)
    else:
        print("   ⚠️ 未检测到 iframe，使用普通方式填充")
        print("   📝 名称: ⏭️ 已跳过自动填充")
        await select_radio(page, "更新方式", data.get("update_type", "自动更新"))
        results["第2步-更新方式"] = True
        if data.get("coupon_ids"):
            ok_coupon = await fill_input(page, "券规则ID", data["coupon_ids"])
            if ok_coupon:
                results["第2步-券规则ID"] = True
            else:
                print("      ⏭️ 当前页面未检测到“券规则ID”字段，自动跳过")
                results["第2步-券规则ID"] = True
        else:
            results["第2步-券规则ID"] = True

    # 严格模式下，第2步异常直接终止当前计划；默认先放行便于联调全流程。
    if step2_error:
        if strict_step2:
            raise RuntimeError(f"第2步失败: {step2_error}")
        print(f"   ⚠️ 第2步异常已记录，当前为非严格模式，继续后续流程: {step2_error}")

    # 预跑按钮
    print("   🔍 点击预跑...")
    try:
        if iframe_info:
            frame_handle = await page.query_selector('iframe')
            if frame_handle:
                frame = await frame_handle.content_frame()
            else:
                frame = None
            if frame:
                prerun_clicked = await frame.evaluate('''() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
                    };
                    const btns = Array.from(document.querySelectorAll('button')).filter(isVisible);
                    const hit = btns.find(btn => {
                        const t = (btn.textContent || '').replace(/\\s+/g, '');
                        return t.includes('预跑');
                    });
                    if (hit) {
                        hit.click();
                        return true;
                    }
                    return false;
                }''')
            else:
                prerun_clicked = False
        else:
            prerun_clicked = await page.evaluate('''() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.includes('预跑') || btn.textContent.includes('预览')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')
        if prerun_clicked:
            print("      ✅ 已点击预跑")
            results["第2步-预跑按钮"] = True
            await wait_and_log(page, 3, "预跑执行中...")
        else:
            print("      ⏭️ 未检测到预跑按钮，自动跳过")
            results["第2步-预跑按钮"] = True
    except Exception as e:
        print(f"      ⚠️ 预跑点击失败: {e}")

    # 门店信息通用回读：只要出现“已选：N/已选中(N)”且 N>0 即认为门店信息条件生效。
    try:
        if iframe_info:
            frame_handle = await page.query_selector('iframe')
            if frame_handle:
                frame_probe = await frame_handle.content_frame()
            else:
                frame_probe = None
            if frame_probe:
                selected_info_text = await frame_probe.evaluate("""() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const s = window.getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const nodes = Array.from(document.querySelectorAll('span,div,b,strong')).filter(isVisible);
                    const hit = nodes.find(n => {
                        const t = (n.textContent || '').replace(/\\s+/g, '');
                        return /已选[:：]\\d+/.test(t) || /已选中[（(]\\d+[)）]/.test(t);
                    });
                    return hit ? (hit.textContent || '').trim() : '';
                }""")
                m = re.search(r'(\\d+)', selected_info_text or "")
                n = int(m.group(1)) if m else 0
                if n > 0:
                    results["第2步-门店信息已选"] = True
                    print(f"      ✅ 门店信息回读通过: {selected_info_text}")
                elif selected_info_text:
                    print(f"      ⚠️ 门店信息回读为0: {selected_info_text}")
    except Exception:
        pass

    # 严格模式下，字段级回读失败也要终止，避免“日志看着成功”。
    if strict_step2:
        required_keys = ["第2步-编辑按钮", "第2步-弹窗可见", "第2步-更新方式", "第2步-预跑按钮"]
        has_main_area_cfg = bool((data.get("main_operating_area", "") or "").strip())
        has_main_store_cfg = bool(
            (data.get("step2_store_file_path", "") or "").strip()
            or (data.get("main_store_file_path", "") or "").strip()
        )
        has_product_cfg = bool((data.get("step2_product_file_path", "") or "").strip())
        has_store_cfg = has_main_area_cfg or has_main_store_cfg or has_product_cfg
        # 通用放行规则：门店信息相关配置时，只要“主消费营运区/主消费门店/门店信息回读”任一成功即放行。
        # 适配“入会门店/主要消费门店/主要消费片区/主要消费营运区/主要消费大区/主要消费省区”等类型。
        if has_store_cfg:
            store_ok = any([
                results.get("第2步-主消费营运区", False),
                results.get("第2步-主消费门店", False),
                results.get("第2步-商品编码", False),
                results.get("第2步-门店信息已选", False),
            ])
            if not store_ok:
                required_keys.append("第2步-主消费营运区")
        if data.get("coupon_ids"):
            required_keys.append("第2步-券规则ID")
        failed = [k for k in required_keys if not results.get(k, False)]
        if has_store_cfg and not failed:
            print("      ✅ 第2步门店信息按通用规则放行（至少一项成功）")
        if failed:
            raise RuntimeError(f"第2步字段回读未通过: {failed}")
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-modal-filled.png')
    
    print("\n   ✅ 第2步完成")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-after-main.png')
    
    print("   ⏭️  点击下一步...")
    clicked = await click_step2_next_button(page)
    if not clicked:
        raise RuntimeError("第2步完成后未能点击“下一步”")
    print("      ✅ 点击成功")
    results["第2步-下一步按钮"] = True
    
    await wait_and_log(page, 2, "跳转到第3步...")
    try:
        still_on_step2 = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const text = Array.from(document.querySelectorAll('body *')).filter(isVisible).map(n => n.textContent || '').join(' ');
            return text.includes('目标分群') || text.includes('编辑分群') || text.includes('预跑');
        }""")
        if still_on_step2:
            print("      ⚠️ 点击后仍停留在第2步，执行一次补点...")
            clicked_retry = await click_step2_next_button(page)
            if clicked_retry:
                await wait_and_log(page, 2, "再次尝试跳转到第3步...")
    except Exception:
        pass
    return results

async def skip_step2(page, data: dict | None = None):
    """跳过第2步内容，仅点击下一步进入第3步。"""
    print("\n📋 第2步：目标分群（跳过模式）")
    print("=" * 50)
    await wait_and_log(page, 2, "等待第2步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-skipped.png')

    print("   ⏭️  跳过第2步内容，直接点击下一步...")
    clicked = await click_button_with_text(page, "下一步")

    if not clicked:
        data = data or {}
        channels = (data.get("channels", "") or "")
        create_url = (data.get("create_url", "") or "")
        # 通用单页模式：若已能识别第3步字段，则无需强制点“下一步”
        try:
            step3_like = await page.evaluate("""() => {
                const txt = (document.body?.innerText || '').replace(/\\s+/g, '');
                return (
                    txt.includes('短信内容') ||
                    txt.includes('结束时间') ||
                    txt.includes('员工任务结束时间') ||
                    txt.includes('执行员工') ||
                    txt.includes('发送内容') ||
                    txt.includes('社群群发')
                );
            }""")
            if step3_like:
                print("      ⏭️ 单页模式：已识别第3步字段，无需点击“下一步”")
                return {"第2步-跳过下一步按钮": True}
        except Exception:
            pass
        if ("会员通-发送社群" in channels) or ("addcommunityPlan" in create_url):
            print("      ⏭️ 社群单页模式：第2步跳过无需点击“下一步”，继续第3步")
            return {"第2步-跳过下一步按钮": True}
        raise RuntimeError("跳过第2步失败：未找到可点击的“下一步”按钮")

    print("      ✅ 已进入第3步")
    await wait_and_log(page, 2, "跳转到第3步...")
    return {"第2步-跳过下一步按钮": True}

# ============ 第3步：触达内容 ============

async def fill_step3(
    page,
    data: dict,
    manual_executor_mode: bool = False,
    executor_check_override: str = "",
    step3_channels_override: str = "",
    executor_include_franchise_override: bool = False,
):
    """填充第3步：触达内容/短信内容"""
    print("\n📋 第3步：短信内容")
    print("="*50)
    
    await wait_and_log(page, 2, "等待第3步加载...")
    async def get_step3_signals() -> dict:
        return await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const visibleNodes = Array.from(document.querySelectorAll('body *')).filter(isVisible);
            const text = visibleNodes.map(n => (n.textContent || '').trim()).join(' ');
            const placeholders = Array.from(document.querySelectorAll('input, textarea'))
                .filter(isVisible)
                .map(i => i.getAttribute('placeholder') || '')
                .filter(Boolean);
            const hasCascader = Array.from(document.querySelectorAll('.el-cascader, .el-cascader-panel')).some(isVisible);
            const hasEditable = Array.from(document.querySelectorAll('[contenteditable="true"]')).some(isVisible);
            const strongSignals = [
                '发送限制', '分配方式', '执行员工', '任务详情',
                '发送内容', '短信内容', '添加图片', '结束时间'
            ];
            const hitSignals = strongSignals.filter(s => text.includes(s));
            return { text, placeholders, hasCascader, hasEditable, hitSignals };
        }""")

    async def detect_step3_ready() -> bool:
        sig = await get_step3_signals()
        # 必须至少命中两个第3步强信号，避免把第1步/第2步误判成第3步
        return len(sig.get("hitSignals", [])) >= 2

    async def wait_step3_ready(max_seconds: int = 30, interval: float = 0.5) -> bool:
        loops = int(max_seconds / interval)
        for i in range(loops):
            if await detect_step3_ready():
                return True
            # 每 5 秒打一条等待日志，便于观察慢加载
            if i > 0 and i % int(5 / interval) == 0:
                print(f"   ⏳ 第3步仍在加载中... ({int(i * interval)}s)")
            await asyncio.sleep(interval)
        return False

    ready = await wait_step3_ready(max_seconds=45)
    if not ready:
        print("   ⚠️ 未检测到第3步字段，尝试再次点击“下一步”...")
        clicked_next = await click_button_with_text(page, "下一步")
        if clicked_next:
            await wait_and_log(page, 2, "重试进入第3步...")
            ready = await wait_step3_ready(max_seconds=30)
    if not ready:
        sig = await get_step3_signals()
        debug = {
            "url": await page.evaluate("() => location.href"),
            "hitSignals": sig.get("hitSignals", []),
            "placeholders": sig.get("placeholders", [])[:20],
        }
        raise RuntimeError(f"未进入第3步页面，停止执行。诊断={debug}")

    await asyncio.sleep(0.2)
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-before.png')
    
    results = {}
    selected_channels = resolve_channels_for_plan(data, step3_channels_override)
    if (len(selected_channels) > 1) and (not parse_step3_channels(str(data.get("channels", "") or ""))):
        inferred = infer_channels_from_create_url(str(data.get("create_url", "") or ""))
        if inferred:
            selected_channels = inferred
            print(f"   🧪 渠道收敛: 未读取到计划行渠道，按创建链接推断为 {'、'.join(selected_channels)}")
    if selected_channels:
        print(f"   📡 渠道选择: {'、'.join(selected_channels)}")
    else:
        print("   📡 渠道选择: 未指定（按当前页面自动识别）")

    # AB-B 分支：恢复“先切渠道再填字段”的行为，避免停留在默认渠道导致字段不可见。
    if selected_channels:
        primary_channel = selected_channels[0]
        switched_primary = await switch_step3_channel(page, primary_channel)
        print(f"   🔀 渠道切换(主): {primary_channel} -> {'成功' if switched_primary else '未命中(继续兜底)'}")
        await asyncio.sleep(0.4)

    has_sms_editor = await page.evaluate("""() => {
        const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
        };
        const items = Array.from(document.querySelectorAll('.item, .el-form-item, .ant-form-item')).filter(isVisible);
        for (const it of items) {
            const txt = (it.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('短信内容')) continue;
            const ed = Array.from(it.querySelectorAll('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]')).find(isVisible);
            if (ed) return true;
        }
        return false;
    }""")
    has_channel_filter = bool(selected_channels)
    sms_required = ("短信" in selected_channels) if has_channel_filter else bool(has_sms_editor)
    customer_msg_required = ("会员通-发客户消息" in selected_channels) if has_channel_filter else True
    community_required = ("会员通-发送社群" in selected_channels) if has_channel_filter else False
    moments_required = ("会员通-发客户朋友圈" in selected_channels) if has_channel_filter else True

    print("   📝 短信内容...")
    sms_content = data.get("sms_content", "测试短信内容")
    sms_content_clean = sanitize_sms_content(sms_content)
    if sms_content_clean != sms_content:
        print(f"      ⚠️ 短信文案已自动清洗非法字符: {sms_content} -> {sms_content_clean}")
    sms_content = sms_content_clean
    if sms_required:
        if has_channel_filter:
            switched_sms = await switch_step3_channel(page, "短信")
            print(f"      🧪 切换到短信渠道: {'成功' if switched_sms else '未命中'}")
            await asyncio.sleep(0.3)
        try:
            sms_ok = await fill_step3_sms_content(page, sms_content)
            if not sms_ok:
                raise RuntimeError("未找到可写入的短信内容输入框")
            print(f"      ✅ 已填充: {sms_content[:30]}...")
            results["第3步-短信内容"] = True
        except Exception as e:
            print(f"      ⚠️ 填充失败: {e}")
            results["第3步-短信内容"] = False
    else:
        print("      ⏭️ 当前所选渠道无需短信内容，已跳过")
        results["第3步-短信内容"] = True

    # 会员通-发客户消息 / 会员通-发客户朋友圈 共用字段
    step3_end_time = data.get("step3_end_time") or data.get("end_time")
    executor_vals = data.get("executor_employees", "")
    # 优先使用网页勾选项；未勾选时再按任务文件字段判断（默认关闭）。
    executor_include_franchise = executor_include_franchise_override or parse_bool_flag(
        data.get("executor_include_franchise", "否"), default=False
    )
    send_content = data.get("send_content", "")
    moments_add_images = parse_bool_flag(data.get("moments_add_images", "否"), default=False)
    moments_image_paths = data.get("moments_image_paths", "")
    upload_stores = parse_bool_flag(data.get("upload_stores", "否"), default=False)
    store_file_path = data.get("store_file_path", "")
    msg_add_mini_program = parse_bool_flag(data.get("msg_add_mini_program", "否"), default=False)
    msg_mini_program_name = data.get("msg_mini_program_name", "大参林健康")
    msg_mini_program_title = data.get("msg_mini_program_title", "")
    msg_mini_program_cover_path = data.get("msg_mini_program_cover_path", "")
    msg_mini_program_page_path = data.get("msg_mini_program_page_path", "")
    group_send_name = (data.get("group_send_name", "") or "福利").strip()
    moments_gate_ok = True
    moments_gate_errors = []
    message_like_required = customer_msg_required or moments_required or community_required
    image_upload_enabled = False
    if message_like_required:
        if has_channel_filter:
            if community_required:
                target_msg_channel = "会员通-发送社群"
            elif moments_required:
                target_msg_channel = "会员通-发客户朋友圈"
            else:
                target_msg_channel = "会员通-发客户消息"
            switched_msg = await switch_step3_channel(page, target_msg_channel)
            print(f"   🔀 渠道切换(会员通): {target_msg_channel} -> {'成功' if switched_msg else '未命中(按当前页继续)'}")
            await asyncio.sleep(0.4)
        print(f"   📅 员工任务结束时间: {step3_end_time}")
        end_ok = await fill_step3_end_time(page, step3_end_time, section_hint=("社群群发" if community_required else ""))
        print(f"      {'✅' if end_ok else '⚠️'} 员工任务结束时间{'已填充' if end_ok else '未匹配到字段'}")
        results["第3步-结束时间"] = end_ok
        if not end_ok:
            moments_gate_ok = False
            moments_gate_errors.append("结束时间")

        if community_required:
            print(f"   👥 下发群名: {group_send_name}")
            group_ok = await fill_step3_group_name(page, group_send_name, section_hint="社群群发")
            print(f"      {'✅' if group_ok else '⚠️'} 下发群名{'已填充' if group_ok else '未匹配到字段'}")
            results["第3步-下发群名"] = group_ok
            if not group_ok:
                moments_gate_ok = False
                moments_gate_errors.append("下发群名")

        distribution_mode = (data.get("distribution_mode", "") or "").strip()
        if not distribution_mode:
            if community_required:
                distribution_mode = "导入门店" if upload_stores else "按条件筛选客户群"
            else:
                distribution_mode = "指定门店分配"
        mode_norm = distribution_mode.replace(" ", "")
        community_condition_mode = community_required and ("按条件筛选客户" in mode_norm or "按条件筛选客户群" in mode_norm)
        community_import_mode = community_required and ("导入门店" in mode_norm or "选中门店" in mode_norm)
        # 社群“按条件筛选客户群”默认同步加盟区域，避免 Windows 端遗漏导致与 Mac 行为不一致
        if community_condition_mode and not executor_include_franchise:
            executor_include_franchise = True
            print("   🧩 社群按条件筛选：已自动开启“包含加盟区域”")

        effective_upload_stores = bool(upload_stores or community_import_mode)
        # 客户消息/朋友圈：若走“上传门店”则不再强制执行员工文本选择
        need_executor = (
            (customer_msg_required or moments_required) and (not effective_upload_stores)
        ) or community_condition_mode
        # 分配方式强校验仅用于社群渠道；1对1/朋友圈页面若不存在该控件不阻断。
        mode_ok = True
        if need_executor or community_required:
            mode_ok = await set_step3_distribution_mode(
                page,
                distribution_mode,
                section_hint=("社群群发" if community_required else ""),
            )
            print(f"   ⚙️ 社群任务分配方式: {distribution_mode if mode_ok else '未找到分配方式控件'}")
            if community_required and (not mode_ok):
                moments_gate_ok = False
                moments_gate_errors.append("分配方式")

        if need_executor:
            print(f"   👥 执行员工: {executor_vals}")
            if executor_include_franchise:
                print("      🧩 包含加盟区域: 是")
            if manual_executor_mode:
                print("      ⏸️ 手动模式：请在浏览器中手工勾选执行员工后，回到终端按回车继续...")
                await asyncio.to_thread(input, "Press Enter to continue after manual executor selection...")
                debug_data = await dump_executor_debug(page)
                targets = split_multi_values(executor_check_override) if executor_check_override else split_multi_values(executor_vals)
                overlap_msg = detect_executor_overlap_conflict(debug_data, targets)
                if overlap_msg:
                    print(f"      ⚠️ {overlap_msg}（当前按业务场景仅提示，不阻断保存）")
                haystack = " ".join([
                    debug_data.get("inputValue", ""),
                    " ".join(debug_data.get("tags", [])),
                    " ".join([n.get("text", "") for n in debug_data.get("checked", []) if isinstance(n, dict)]),
                ])
                manual_ok = all(t in haystack for t in targets)
                if not manual_ok:
                    print(f"      ⚠️ 手动执行员工校验失败：当前未匹配目标 {targets}")
                else:
                    print("      ✅ 手动执行员工校验通过")
                results["第3步-执行员工"] = manual_ok
                if not manual_ok:
                    moments_gate_ok = False
                    moments_gate_errors.append("执行员工")
            else:
                if ("按条件筛选客户" in mode_norm) or ("按条件筛选客户群" in mode_norm):
                    exec_ok = await fill_step3_executor_by_condition(
                        page,
                        executor_vals,
                        include_franchise=(True if community_condition_mode else executor_include_franchise),
                    )
                else:
                    exec_ok = await fill_step3_executor(
                        page, executor_vals, include_franchise=executor_include_franchise
                    )
                print(f"      {'✅' if exec_ok else '⚠️'} 执行员工{'已选择' if exec_ok else '未完整选择'}")
                results["第3步-执行员工"] = exec_ok
                if not exec_ok:
                    moments_gate_ok = False
                    moments_gate_errors.append("执行员工")
                debug_data = await dump_executor_debug(page)
                targets = split_multi_values(executor_vals)
                overlap_msg = detect_executor_overlap_conflict(debug_data, targets)
                if overlap_msg:
                    print(f"      ⚠️ {overlap_msg}（当前按业务场景仅提示，不阻断保存）")
        else:
            if community_import_mode:
                print("   👥 执行员工: ⏭️ 当前为“导入门店/选中门店”，无需选择员工")
            else:
                print("   👥 执行员工: ⏭️ 社群渠道无需填写，已跳过")
            results["第3步-执行员工"] = True

        print(f"   📝 发送内容: {send_content}")
        send_ok = await fill_step3_send_content(page, send_content)
        print(f"      {'✅' if send_ok else '⚠️'} 发送内容{'已填充' if send_ok else '未匹配到字段'}")
        results["第3步-发送内容"] = send_ok
        if not send_ok:
            moments_gate_ok = False
            moments_gate_errors.append("发送内容")

        print(f"   🏬 上传门店: {'需要上传' if effective_upload_stores else '不上传'}")
        if effective_upload_stores:
            store_ok, store_msg = await upload_step3_store_file(page, store_file_path)
            print(f"      {'✅' if store_ok else '⚠️'} {store_msg}")
            results["第3步-上传门店"] = store_ok
            if not store_ok:
                moments_gate_ok = False
                moments_gate_errors.append("上传门店")
        else:
            print("      ⏭️ 未勾选上传门店，已跳过")
            results["第3步-上传门店"] = True

        if customer_msg_required or community_required:
            print(f"   🧩 添加小程序: {'需要配置' if msg_add_mini_program else '不配置'}")
            if msg_add_mini_program:
                mini_ok, mini_msg = await fill_step3_message_mini_program(
                    page,
                    msg_mini_program_name,
                    msg_mini_program_title,
                    msg_mini_program_cover_path,
                    msg_mini_program_page_path,
                )
                print(f"      {'✅' if mini_ok else '⚠️'} {mini_msg}")
                results["第3步-添加小程序"] = mini_ok
                if not mini_ok:
                    moments_gate_ok = False
                    moments_gate_errors.append("添加小程序")
            else:
                print("      ⏭️ 未勾选添加小程序，已跳过")
                results["第3步-添加小程序"] = True
        else:
            print("   🧩 添加小程序: ⏭️ 当前所选渠道无需填写，已跳过")
            results["第3步-添加小程序"] = True

        image_upload_required = moments_required or community_required or customer_msg_required
        image_upload_enabled = bool(image_upload_required and moments_add_images)
        if image_upload_required:
            print(f"   🖼️ 朋友圈图片: {'需要上传' if moments_add_images else '不上传'}")
            if moments_add_images:
                img_ok, img_msg = await upload_step3_moments_images(page, moments_image_paths)
                print(f"      {'✅' if img_ok else '⚠️'} {img_msg}")
                results["第3步-朋友圈图片"] = img_ok
                if not img_ok:
                    moments_gate_ok = False
                    moments_gate_errors.append("朋友圈图片")
            else:
                print("      ⏭️ 未勾选图片上传，已跳过")
                results["第3步-朋友圈图片"] = True
        else:
            print("   🖼️ 朋友圈图片: ⏭️ 当前所选渠道无需填写，已跳过")
            results["第3步-朋友圈图片"] = True
    else:
        print("   📅 员工任务结束时间: ⏭️ 当前所选渠道无需填写，已跳过")
        print("   👥 执行员工: ⏭️ 当前所选渠道无需填写，已跳过")
        print("   📝 发送内容: ⏭️ 当前所选渠道无需填写，已跳过")
        print("   🏬 上传门店: ⏭️ 当前所选渠道无需填写，已跳过")
        print("   🧩 添加小程序: ⏭️ 当前所选渠道无需填写，已跳过")
        print("   🖼️ 朋友圈图片: ⏭️ 当前所选渠道无需填写，已跳过")
        results["第3步-结束时间"] = True
        results["第3步-执行员工"] = True
        results["第3步-发送内容"] = True
        results["第3步-上传门店"] = True
        results["第3步-添加小程序"] = True
        results["第3步-朋友圈图片"] = True

    # 显式约束：会员通-发客户消息始终要求结束时间/执行员工/发送内容都成功
    if customer_msg_required:
        must_keys = ["第3步-结束时间", "第3步-发送内容"]
        if not effective_upload_stores:
            must_keys.append("第3步-执行员工")
        missing = [k.replace("第3步-", "") for k in must_keys if not results.get(k, False)]
        if missing:
            moments_gate_ok = False
            for m in missing:
                if m not in moments_gate_errors:
                    moments_gate_errors.append(m)
    if community_required:
        must_keys = ["第3步-结束时间", "第3步-下发群名", "第3步-发送内容"]
        if upload_stores:
            must_keys.append("第3步-上传门店")
        missing = [k.replace("第3步-", "") for k in must_keys if not results.get(k, False)]
        if missing:
            moments_gate_ok = False
            for m in missing:
                if m not in moments_gate_errors:
                    moments_gate_errors.append(m)

    # 会员通消息/朋友圈渠道下，共用必填失败直接中断；朋友圈额外校验图片
    if message_like_required and (not moments_gate_ok):
        raise RuntimeError(f"会员通渠道必填项未完成: {','.join(moments_gate_errors)}")

    # 通知配置场景：将当前配置复制到其他地区，避免部分地区短信为空导致 P1114。
    # 默认不自动执行“渠道信息复制”，避免在部分页面触发内容重置副作用。
    print("   📎 渠道信息复制: ⏭️ 默认关闭（避免副作用）")
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-after.png')
    
    print("\n   ✅ 第3步完成")
    
    print("   💾 点击保存...")
    if image_upload_enabled:
        settle = max(2.5, min(6.0, MOMENTS_UPLOAD_WAIT_SECONDS * 0.6))
        print(f"      ⏳ 图片上传稳态等待 {settle:.1f}s（避免接口并发限流）...")
        await asyncio.sleep(settle)
    sms_before_save = await read_step3_sms_text(page) if sms_required else ""
    if sms_required and len(sms_before_save) == 0 and sms_content:
        print("      ⚠️ 保存前短信为空，执行一次重填...")
        refill_ok = await fill_step3_sms_content(page, sms_content)
        print(f"      {'✅' if refill_ok else '⚠️'} 重填短信{'成功' if refill_ok else '失败'}")
        sms_before_save = await read_step3_sms_text(page)
    if sms_required:
        print(f"      🧪 保存前短信回读长度: {len(sms_before_save)}")
    else:
        print("      🧪 保存前短信回读: 已跳过（当前渠道无需短信）")
    send_before_save = await read_step3_send_text(page) if message_like_required else ""
    if message_like_required and len(send_before_save) == 0 and send_content:
        print("      ⚠️ 保存前发送内容为空，执行一次重填...")
        refill_send_ok = await fill_step3_send_content(page, send_content)
        print(f"      {'✅' if refill_send_ok else '⚠️'} 重填发送内容{'成功' if refill_send_ok else '失败'}")
        send_before_save = await read_step3_send_text(page)
    if message_like_required:
        print(f"      🧪 保存前发送内容回读长度: {len(send_before_save)}")
    else:
        print("      🧪 保存前发送内容回读: 已跳过（当前渠道无需发送内容）")
    loop = asyncio.get_running_loop()
    save_resp_task = loop.create_future()
    save_resp_candidates = []
    save_req_candidates = []

    def _is_core_save_api(url: str) -> bool:
        u = (url or "").lower()
        return (
            "/api/v1/precision/content-rights-setting/batch-create/v2" in u
            or "/api/v1/precision/community-admin/activity/addorupdate" in u
        )

    def _on_response(r):
        try:
            url_l = (r.url or "").lower()
            if r.request.method in ("POST", "PUT", "PATCH"):
                save_resp_candidates.append((r.request.method, r.url))
            matched = (
                r.request.method in ("POST", "PUT", "PATCH")
                and _is_core_save_api(url_l)
            )
            if matched and (not save_resp_task.done()):
                save_resp_task.set_result(r)
        except Exception:
            pass

    def _on_request(req):
        try:
            m = req.method or ""
            if m in ("POST", "PUT", "PATCH"):
                save_req_candidates.append((m, req.url))
        except Exception:
            pass

    page.on("response", _on_response)
    page.on("request", _on_request)
    save_start_url = page.url
    clicked = await click_step3_save_button(page)
    if not clicked:
        if not save_resp_task.done():
            save_resp_task.set_result(None)
        raise RuntimeError("第3步未能点击“保存”")
    print("      ✅ 点击保存成功")
    results["第3步-保存按钮"] = True
    
    await wait_and_log(page, 2, "保存中...")
    sms_after_click = await read_step3_sms_text(page) if sms_required else ""
    if sms_required:
        print(f"      🧪 点击保存后短信回读长度: {len(sms_after_click)}")
    else:
        print("      🧪 点击保存后短信回读: 已跳过（当前渠道无需短信）")
    send_after_click = await read_step3_send_text(page) if message_like_required else ""
    if message_like_required:
        print(f"      🧪 点击保存后发送内容回读长度: {len(send_after_click)}")
    else:
        print("      🧪 点击保存后发送内容回读: 已跳过（当前渠道无需发送内容）")
    if save_req_candidates:
        print(f"      🧪 保存阶段请求候选: {[u for _, u in save_req_candidates[-10:]]}")
    if save_resp_candidates:
        print(f"      🧪 保存阶段POST候选: {[u for _, u in save_resp_candidates[:8]]}")
    saved_ok = await ensure_step3_saved(page, save_resp_task=save_resp_task, before_url=save_start_url)
    community_like = "addcommunityPlan" in (save_start_url or "")

    async def _has_visible_save_error() -> bool:
        try:
            return bool(await page.evaluate("""() => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const s = window.getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                };
                const bad = /(失败|错误|非法|不能为空|未通过|重复|不能选择历史时间|目标不可重复)/;
                const nodes = Array.from(document.querySelectorAll(
                    '.el-form-item__error, .ant-form-item-explain-error, .el-message__content, .ant-message-custom-content, .el-message-box__message, .ant-notification-notice-message, [role="alert"]'
                )).filter(isVisible);
                return nodes.some(n => bad.test((n.textContent || '').trim()));
            }"""))
        except Exception:
            return False

    # 保存判定兜底：若已命中核心保存接口请求，但页面偶发切到 about:blank/新标签导致响应捕获丢失，
    # 且页面无可见错误提示，则按弱成功放行，避免误判失败。
    # 注意：朋友圈图片上传场景必须强校验，不允许弱放行。
    if (not saved_ok) and save_req_candidates:
        core_req_hit = any(_is_core_save_api(u) for _, u in save_req_candidates)
        if core_req_hit:
            has_visible_error = await _has_visible_save_error()
            if not has_visible_error:
                if image_upload_enabled:
                    print("      ⚠️ 图片上传场景：已命中核心保存请求且未检测到失败信号，按已提交放行")
                elif community_like:
                    print("      ⚠️ 社群页已命中核心保存请求，且未检测到可见错误提示：按弱成功放行（防止about:blank误判）")
                else:
                    print("      ⚠️ 已命中核心保存请求，且未检测到可见错误提示：按弱成功放行（防止CDP标签页切换导致误判）")
                saved_ok = True
            else:
                print("      ⚠️ 已捕获保存请求，但页面存在错误提示，仍按失败处理")
        elif not community_like:
            print("      ⚠️ 已捕获保存请求，但未命中核心保存接口，按失败处理")
    try:
        page.remove_listener("response", _on_response)
    except Exception:
        pass
    try:
        page.remove_listener("request", _on_request)
    except Exception:
        pass
    if (not saved_ok) and (not community_like):
        # 兜底：补点“主保存”并重试判定。图片上传场景增加多轮重试，降低接口并发限流导致的假失败。
        retry_rounds = 3 if image_upload_enabled else 1
        for attempt in range(1, retry_rounds + 1):
            if image_upload_enabled:
                wait_s = MOMENTS_UPLOAD_WAIT_SECONDS + (attempt - 1) * 2.0
                print(f"      ⚠️ 图片上传强校验：第{attempt}/{retry_rounds}次重试前等待{wait_s:.1f}s...")
                await wait_and_log(page, wait_s, "图片上传后等待稳定...")
            elif attempt == 1:
                print("      ⚠️ 首次保存未确认成功，补点一次主保存后重试判定...")

            retry_task = asyncio.get_running_loop().create_future()
            def _on_response_retry(r):
                try:
                    url_l = (r.url or "").lower()
                    matched = (
                        r.request.method in ("POST", "PUT", "PATCH")
                        and (
                            ("precision.dslyy.com" in url_l)
                            or "marketingtemplate" in url_l
                            or "template" in url_l
                            or "save" in url_l
                        )
                    )
                    if matched and (not retry_task.done()):
                        retry_task.set_result(r)
                except Exception:
                    pass
            page.on("response", _on_response_retry)
            try:
                clicked_retry = await click_step3_save_button(page)
                if clicked_retry:
                    await wait_and_log(page, 1.6, f"补点保存中(第{attempt}次)...")
                    saved_ok = await ensure_step3_saved(page, save_resp_task=retry_task, before_url=save_start_url)
                if saved_ok:
                    break
            finally:
                try:
                    page.remove_listener("response", _on_response_retry)
                except Exception:
                    pass
    elif (not saved_ok) and community_like:
        # 社群页保护性二次提交：仅在当前仍停留正常社群编辑页时重试一次。
        curr = page.url or ""
        if ("addcommunityPlan" in curr) and (not curr.startswith("about:blank")):
            print("      ⚠️ 社群页首次保存未确认成功，执行一次保护性补点...")
            retry_task = asyncio.get_running_loop().create_future()
            def _on_response_retry(r):
                try:
                    url_l = (r.url or "").lower()
                    matched = (
                        r.request.method in ("POST", "PUT", "PATCH")
                        and (
                            ("precision.dslyy.com" in url_l)
                            or "marketingtemplate" in url_l
                            or "marketingplan" in url_l
                            or "template" in url_l
                            or "save" in url_l
                        )
                    )
                    if matched and (not retry_task.done()):
                        retry_task.set_result(r)
                except Exception:
                    pass
            page.on("response", _on_response_retry)
            try:
                try:
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
                clicked_retry = await click_step3_save_button(page)
                if clicked_retry:
                    await wait_and_log(page, 1.6, "补点保存中...")
                    saved_ok = await ensure_step3_saved(page, save_resp_task=retry_task, before_url=save_start_url)
            finally:
                try:
                    page.remove_listener("response", _on_response_retry)
                except Exception:
                    pass
        else:
            print("      ⚠️ 社群页首次保存未确认成功，且当前URL异常，跳过补点")
    if not saved_ok:
        raise RuntimeError(f"保存未真正提交（未检测到成功提示/跳转），当前URL={page.url}")
    print("      ✅ 已检测到保存成功")
    return results

async def dump_executor_debug(page):
    """打印执行员工级联选择的调试信息（无需 DevTools）。"""
    data = await page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        let item = null;
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (txt.includes('执行员工')) {
                item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
                break;
            }
        }
        const root = item ? item.querySelector('.el-cascader') : null;
        const panel = document.querySelector('.el-cascader-panel');
        const checked = panel
            ? Array.from(panel.querySelectorAll('.el-cascader-node'))
                .filter(n => n.querySelector('.el-checkbox__input.is-checked'))
                .map(n => ({
                    text: (n.querySelector('.el-cascader-node__label')?.textContent || '').trim(),
                    id: n.id || '',
                    cls: n.className || '',
                    cbCls: (n.querySelector('.el-checkbox__input')?.className || '')
                }))
            : [];

        const inputValue = root?.querySelector('input.el-input__inner')?.value || '';
        const tags = root
            ? Array.from(root.querySelectorAll('.el-tag .el-tag__content, .el-cascader__tags span'))
                .map(n => (n.textContent || '').trim())
                .filter(Boolean)
            : [];
        return { checked, inputValue, tags };
    }""")
    print("   🧪 执行员工调试信息:")
    print(f"      inputValue: {data.get('inputValue', '')}")
    print(f"      tags: {data.get('tags', [])}")
    print(f"      checkedNodes: {data.get('checked', [])}")
    return data

def detect_executor_overlap_conflict(debug_data: dict, targets: list) -> str:
    """检测执行员工选择是否存在“全国 + 子区域”重叠冲突。"""
    if not isinstance(debug_data, dict):
        return ""
    checked = debug_data.get("checked", []) or []
    tags = debug_data.get("tags", []) or []
    has_country_checked = False
    for n in checked:
        if not isinstance(n, dict):
            continue
        txt = str(n.get("text", "")).strip()
        cb_cls = str(n.get("cbCls", "")).strip()
        if txt != "全国":
            continue
        # 仅把“全国全选”视为冲突；半选(is-indeterminate)不算冲突
        if ("is-checked" in cb_cls) and ("is-indeterminate" not in cb_cls):
            has_country_checked = True
            break
    # tags 里出现“全国 / xxx”代表选择了全国下的子层级路径
    has_child_path = any("全国 /" in str(t) for t in tags)
    targets = targets or []
    target_has_country = any("全国" == str(t).strip() for t in targets)
    if has_country_checked and has_child_path and not target_has_country:
        return "执行员工疑似重叠：已勾选“全国”同时又勾选其子区域（如 大区/省区/门店），保存会触发“目标不可重复”"
    return ""

# ============ 浏览器连接 ============

async def connect_browser(p, connect_cdp: bool, cdp_endpoint: str):
    """连接浏览器：本地启动或接管已有 Chrome(CDP)。"""
    if connect_cdp:
        print(f"   🔌 通过 CDP 接管已有浏览器: {cdp_endpoint}")
        last_err = None
        for i in range(3):
            try:
                browser = await p.chromium.connect_over_cdp(cdp_endpoint)
                if not browser.contexts:
                    # CDP 模式下通常至少有 1 个默认上下文，这里兜底。
                    await browser.new_context()
                return browser
            except Exception as e:
                last_err = e
                print(f"   ⚠️ CDP 连接失败({i+1}/3): {e}")
                await asyncio.sleep(1.2 * (i + 1))
        raise RuntimeError(f"CDP 连接失败（重试3次后仍失败）: {last_err}")

    print("   🚀 启动新浏览器会话")
    return await p.chromium.launch(
        headless=HEADLESS,
        slow_mo=SLOW_MO,
        args=[
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-infobars',
            '--disable-blink-features=AutomationControlled'
        ]
    )

async def ensure_login(browser, connect_cdp: bool):
    """确保登录状态。CDP 模式默认复用已有登录，不再强制扫码。"""
    if connect_cdp:
        print("   ✅ CDP 模式：复用当前 Chrome 登录态")
        return

    login_page = await browser.new_page()
    await login_page.goto("https://precision.dslyy.com/admin")
    await asyncio.sleep(3)

    if 'login' in login_page.url or 'sso' in login_page.url:
        print("   📱 请用企业微信扫码登录...")
        logged_in = False
        for i in range(60):
            await asyncio.sleep(5)
            if 'admin' in login_page.url and 'login' not in login_page.url:
                print("   ✅ 登录成功")
                logged_in = True
                break
            print(f"   等待中... ({i + 1}/60)")

        if not logged_in:
            print("   ❌ 登录超时")
            sys.exit(1)
    else:
        print("   ✅ 已登录")

    await login_page.close()

# ============ 并发处理 ============

async def process_single_plan(
    browser,
    plan: dict,
    plan_index: int,
    semaphore: asyncio.Semaphore,
    connect_cdp: bool = False,
    strict_step2: bool = False,
    skip_step2_mode: bool = False,
    manual_executor_mode: bool = False,
    executor_check_override: str = "",
    step3_channels_override: str = "",
    create_url_override: str = "",
    executor_include_franchise_override: bool = False,
) -> bool:
    """使用信号量控制并发，处理单个计划"""
    async with semaphore:
        print(f"\n{'='*60}")
        print(f"📋 计划 {plan_index}: {plan['name']}")
        print(f"{'='*60}")

        context = browser.contexts[0] if connect_cdp and browser.contexts else await browser.new_context()
        owns_context = not (connect_cdp and browser.contexts)
        page = await context.new_page()
        field_results = {}

        for attempt in range(MAX_RETRIES):
            try:
                current_base_url, primary_channel = resolve_base_url_by_channel(
                    plan, step3_channels_override, create_url_override
                )
                if primary_channel:
                    print(f"   🔗 创建链接: 渠道={primary_channel} -> {current_base_url}")
                else:
                    print(f"   🔗 创建链接: 默认 -> {current_base_url}")
                if not (current_base_url or "").strip():
                    raise RuntimeError("缺少创建链接：当前渠道不提供默认链接，请在Excel“创建链接”字段填写后再执行")
                await page.goto(current_base_url)
                await wait_and_log(page, 2, "页面加载中...")

                selected_channels_for_plan = resolve_channels_for_plan(plan, step3_channels_override)
                if parse_step3_channels(step3_channels_override) and parse_step3_channels(plan.get("channels", "")):
                    print("   🧪 渠道来源: 使用任务文件 channels（忽略全局 --step3-channels 覆盖）")
                community_only = bool(selected_channels_for_plan) and all(c == "会员通-发送社群" for c in selected_channels_for_plan)
                community_url = (create_url_override or plan.get("create_url", "") or current_base_url or "")
                auto_skip_step2_for_community = community_only or ("addcommunityPlan" in community_url)
                allow_manual_skip_step2 = bool(skip_step2_mode and community_only)

                # 规则：--skip-step2 仅社群渠道可跳过；其他渠道不允许手动跳过。
                if skip_step2_mode and (not community_only):
                    print("   ⚠️ --skip-step2 仅社群渠道可用；当前渠道将执行第2步")

                if allow_manual_skip_step2 or auto_skip_step2_for_community:
                    if auto_skip_step2_for_community and (not allow_manual_skip_step2):
                        print("   ⏭️  社群渠道模式：自动跳过第2步，直接进入第3步")
                    field_results.update(await fill_step1(page, plan, auto_next=True))
                    field_results.update(await skip_step2(page, plan))
                else:
                    field_results.update(await fill_step1(page, plan, auto_next=False))
                    field_results.update(await fill_step2(page, plan, strict_step2=strict_step2))
                field_results.update(await fill_step3(
                    page,
                    plan,
                    manual_executor_mode=manual_executor_mode,
                    executor_check_override=executor_check_override,
                    step3_channels_override=step3_channels_override,
                    executor_include_franchise_override=executor_include_franchise_override,
                ))
                
                print(f"\n   ✅ 计划 {plan_index} 完成！")
                print("   📌 字段结果清单:")
                has_store_cfg_for_summary = bool(
                    (plan.get("main_operating_area", "") or "").strip()
                    or (plan.get("step2_store_file_path", "") or "").strip()
                    or (plan.get("main_store_file_path", "") or "").strip()
                    or (plan.get("step2_product_file_path", "") or "").strip()
                )
                store_ok_for_summary = any([
                    field_results.get("第2步-主消费营运区", False),
                    field_results.get("第2步-主消费门店", False),
                    field_results.get("第2步-商品编码", False),
                    field_results.get("第2步-门店信息已选", False),
                ])
                step2_optional_when_store_ok = {
                    "第2步-主消费营运区",
                    "第2步-主消费门店",
                    "第2步-商品编码",
                    "第2步-门店信息已选",
                }
                for k in sorted(field_results.keys()):
                    if field_results[k]:
                        mark = "✅"
                    elif has_store_cfg_for_summary and store_ok_for_summary and k in step2_optional_when_store_ok:
                        mark = "⚪"
                    else:
                        mark = "❌"
                    print(f"      {mark} {k}")
                await page.close()
                if owns_context:
                    await context.close()
                return (plan_index, True, plan['name'])

            except Exception as e:
                print(f"\n   ❌ 计划 {plan_index} 失败 (尝试 {attempt+1}/{MAX_RETRIES})")
                print(f"      错误: {e}")
                err_text = str(e)
                non_retryable = any(k in err_text for k in [
                    "目标不可重复",
                    "保存失败提示",
                    "保存被页面校验拦截",
                    "保存未真正提交",
                    "第2步字段回读未通过",
                    "第2步失败",
                ])
                if "目标不可重复" in err_text:
                    print("      ℹ️ 业务校验失败：当前页面存在重复目标，需先人工去重后再执行。")

                if (attempt < MAX_RETRIES - 1) and (not non_retryable):
                    print("      🔄 重试中...")
                    await asyncio.sleep(3)
                else:
                    try:
                        await page.screenshot(path=f'/Users/liminrong/.openclaw/workspace/memory/error-plan-{plan_index}.png')
                        print(f"      📸 错误截图: error-plan-{plan_index}.png")
                    except:
                        print(f"      ⚠️ 截图失败")
                    try:
                        await page.close()
                    except:
                        pass
                    if owns_context:
                        try:
                            await context.close()
                        except:
                            pass
                    return (plan_index, False, plan['name'])

# ============ 主流程 ============

async def main():
    """主流程"""
    parser = argparse.ArgumentParser(description='精准营销自动化 - 批量版')
    parser.add_argument('--test', action='store_true', help='运行单条测试')
    parser.add_argument('--csv', type=str, help='CSV 文件路径')
    parser.add_argument('--start', type=int, help='开始行号（从1开始）')
    parser.add_argument('--end', type=int, help='结束行号')
    parser.add_argument('--concurrent', type=int, default=MAX_CONCURRENT, help='并发数')
    parser.add_argument('--connect-cdp', action='store_true', help='通过 CDP 接管已登录 Chrome（推荐内网场景）')
    parser.add_argument('--cdp-endpoint', type=str, default=DEFAULT_CDP_ENDPOINT, help='CDP 地址，默认 http://127.0.0.1:9222')
    parser.add_argument('--hold-seconds', type=int, default=0, help='完成后保留浏览器秒数，默认 0')
    parser.add_argument('--strict-step2', action='store_true', help='开启第2步严格校验（异常直接失败）')
    parser.add_argument('--skip-step2', action='store_true', help='跳过第2步内容（仅联调第1步和第3步）')
    parser.add_argument('--manual-executor', action='store_true', help='第3步执行员工改为手动勾选（终端回车后继续）')
    parser.add_argument('--executor-check-only', type=str, default='', help='仅校验指定执行员工目标（例如 湖北省区）')
    parser.add_argument('--executor-include-franchise', action='store_true', help='执行员工自动包含加盟区域（如 广佛省区 -> 广佛省区加盟）')
    parser.add_argument(
        '--step3-channels',
        type=str,
        default='',
        help='第3步渠道多选（逗号分隔），如: 会员通-发客户消息,会员通-发客户朋友圈',
    )
    parser.add_argument('--create-url', type=str, default='', help='手动指定创建链接（优先级最高）')
    args = parser.parse_args()
    
    # 加载数据
    if args.csv:
        plans = load_plans_from_csv(args.csv, args.start, args.end)
        print(f"\n📊 从 CSV 加载了 {len(plans)} 条计划")
    elif args.test:
        plans = [DEFAULT_PLAN]
        print(f"\n🧪 运行单条测试")
    else:
        print("请指定 --test 或 --csv <文件路径>")
        sys.exit(1)
    
    start_time = datetime.now()
    
    print("\n" + "="*60)
    print("🚀 精准营销自动化 - 并发批量版")
    print("="*60)
    print(f"   时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   计划数: {len(plans)}")
    if args.connect_cdp and args.concurrent > 1:
        print("   ⚠️ CDP 接管模式下强制串行，已将并发数调整为 1")
        args.concurrent = 1
    print(f"   并发数: {args.concurrent}")
    print("="*60)
    
    # 发送开始通知
    await send_notification(
        "批量处理开始",
        f"📊 开始处理 {len(plans)} 条计划\n并发数: {args.concurrent}"
    )
    
    async with async_playwright() as p:
        browser = await connect_browser(p, args.connect_cdp, args.cdp_endpoint)
        await ensure_login(browser, args.connect_cdp)

        # 并发处理
        semaphore = asyncio.Semaphore(args.concurrent)
        tasks = []

        for i in range(len(plans)):
            task = process_single_plan(
                browser,
                plans[i],
                i + 1,
                semaphore,
                args.connect_cdp,
                args.strict_step2,
                args.skip_step2,
                args.manual_executor,
                args.executor_check_only,
                args.step3_channels,
                args.create_url,
                args.executor_include_franchise,
            )
            tasks.append(task)

        # 等待所有任务完成
        results = await asyncio.gather(*tasks)
        
        # 统计结果
        success_count = 0
        failed_count = 0
        failed_plans = []
        
        for plan_index, success, plan_name in results:
            if success:
                success_count += 1
            else:
                failed_count += 1
                failed_plans.append((plan_index, plan_name))
            
            # 进度通知（每5条）
            if plan_index % 5 == 0 or plan_index == len(plans):
                await send_notification(
                    "批量处理进度",
                    f"📊 已处理 {plan_index}/{len(plans)} 条\n✅ 成功: {success_count}\n❌ 失败: {failed_count}"
                )
        
        # 完成通知
        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()
        
        summary = f"✅ 成功: {success_count}\n❌ 失败: {failed_count}\n总耗时: {total_time:.1f}秒"
        
        await send_notification("批量处理完成", summary)
        
        if failed_plans:
            detail = "\n失败的计划:\n"
            for idx, name in failed_plans:
                detail += f"  {idx}. {name}\n"
            await send_notification("失败详情", detail)
        
        print("\n" + "="*60)
        print("🎉 批量处理完成！")
        print("="*60)
        print(f"   ✅ 成功: {success_count}")
        print(f"   ❌ 失败: {failed_count}")
        
        if failed_plans:
            print("\n   失败的计划:")
            for idx, name in failed_plans:
                print(f"      {idx}. {name}")

        print("="*60)

        if args.hold_seconds > 0:
            print(f"\n⏸️  浏览器保持打开 {args.hold_seconds} 秒...")
            await asyncio.sleep(args.hold_seconds)

if __name__ == "__main__":
    asyncio.run(main())
