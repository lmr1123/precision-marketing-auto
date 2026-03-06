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
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ============ 配置 ============

BASE_URL = "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=594094287227023360"

# 默认测试数据
DEFAULT_PLAN = {
    "name": "测试-广佛省区-3月会员活动",
    "region": "省区",
    "theme": "其他",
    "use_recommend": "否",
    "start_time": "2026-03-01 08:00",
    "end_time": "2026-03-01 08:00",
    "trigger_type": "定时-单次任务",
    "send_time": "2026-03-01 08:00",
    "global_limit": "不限制",
    "set_target": "否",
    "group_name": "测试-≥20积分会员（未绑客）",
    "update_type": "自动更新",
    "main_operating_area": "广佛省区",
    "coupon_ids": "1-20000005475",
    "sms_content": "短信内容测试",
    "step3_end_time": "2026-03-08 08:00",
    "executor_employees": "西北大区、湖北省区",
    "send_content": "企微1对1内容测试",
}

HEADLESS = False
SLOW_MO = 100
MAX_RETRIES = 2
MAX_CONCURRENT = 3
FEISHU_USER_ID = "ou_ed20f9990c63fa5448a0f2cd613ecf30"
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"

# ============ 工具函数 ============

def load_plans_from_csv(csv_path: str, start: int = None, end: int = None) -> list:
    """从 CSV 加载计划数据"""
    plans = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            if start and i < start:
                continue
            if end and i > end:
                break
            plan = {
                "name": row.get("name", "").strip(),
                "region": row.get("region", "").strip(),
                "theme": row.get("theme", "").strip(),
                "use_recommend": row.get("use_recommend", "").strip(),
                "start_time": row.get("start_time", "").strip(),
                "end_time": row.get("end_time", "").strip(),
                "trigger_type": row.get("trigger_type", "").strip(),
                "send_time": row.get("send_time", "").strip(),
                "global_limit": row.get("global_limit", "").strip(),
                "set_target": row.get("set_target", "").strip(),
                "group_name": row.get("group_name", "").strip(),
                "update_type": row.get("update_type", "").strip(),
                "main_operating_area": row.get("main_operating_area", "").strip(),
                "coupon_ids": row.get("coupon_ids", "").strip(),
                "sms_content": row.get("sms_content", "").strip(),
                "step3_end_time": row.get("step3_end_time", "").strip(),
                "executor_employees": row.get("executor_employees", "").strip(),
                "send_content": row.get("send_content", "").strip(),
            }
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
    for i in range(count):
        item = form_items.nth(i)
        label_el = item.locator('.el-form-item__label, .ant-form-item-label label').first
        try:
            text = (await label_el.text_content() or "").strip().replace("：", "").replace(":", "")
            if text == label or label in text:
                return item
        except:
            continue
    return None

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

    item = await get_form_item_by_label(page, label)
    if item:
        try:
            # 三步走：点击输入框 -> 等待弹层 -> 点击文本
            await item.locator(
                '.el-input__inner, .el-select .el-input, .ant-select-selector, .ant-select-selection-item'
            ).first.click(force=True)
            await page.locator('.el-select-dropdown:visible, .ant-select-dropdown:visible').first.wait_for(timeout=3000)

            option = page.locator(
                '.el-select-dropdown__item:visible, .ant-select-item-option:visible, .ant-select-item:visible'
            ).filter(has_text=value).first
            if await option.count() > 0:
                await option.click(force=True)
                print(f"      ✅ 已选择: {value}")
                await asyncio.sleep(0.2)
                return True
        except:
            pass

    # 兜底：直接按文本点击可见选项
    options = page.locator('.el-select-dropdown__item:visible, .ant-select-item:visible')
    opt_count = await options.count()
    for j in range(opt_count):
        try:
            opt_text = (await options.nth(j).text_content() or "").strip()
            if value in opt_text or opt_text in value:
                await options.nth(j).click(force=True)
                print(f"      ✅ 已选择: {opt_text}")
                await asyncio.sleep(0.2)
                return True
        except:
            continue

    print(f"      ⚠️ 未找到字段: {label}")
    return False

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

def split_datetime(raw: str):
    """将 YYYY-MM-DD HH:MM[:SS] 拆分为 (date, time) 并标准化为 HH:MM:SS。"""
    raw = (raw or "").strip()
    if " " in raw:
        date_part, time_part = raw.split(" ", 1)
    else:
        date_part, time_part = raw, "00:00:00"
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

async def fill_step3_end_time(page, end_time: str) -> bool:
    """第3步结束时间：填入并确认日期面板。"""
    date_part, _ = split_datetime(end_time)
    item = page.locator(".item", has_text="结束时间").first
    input_el = None
    if await item.count() > 0:
        cand = item.locator('input[placeholder*="结束"], input[placeholder*="请选择结束"], input[placeholder*="日期"], input.el-input__inner, input').first
        if await cand.count() > 0:
            input_el = cand

    # 兜底1：全局可见 placeholder
    if input_el is None:
        cand = page.locator('input[placeholder*="请选择结束日期"], input[placeholder*="结束日期"], input[placeholder*="请选择结束"]').first
        if await cand.count() > 0:
            input_el = cand

    # 兜底2：按“结束时间”文本就近寻找 input
    if input_el is None:
        ok = await page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const labels = Array.from(document.querySelectorAll('span,label,div')).filter(n => /结束时间/.test((n.textContent||'')));
            for (const l of labels) {
                const scope = l.closest('.item, .el-form-item, .ant-form-item') || l.parentElement;
                if (!scope) continue;
                const inp = scope.querySelector('input[placeholder*="结束"], input[placeholder*="日期"], input.el-input__inner');
                if (inp && isVisible(inp)) {
                    inp.setAttribute('data-step3-endtime-target', '1');
                    return true;
                }
            }
            return false;
        }""")
        if ok:
            cand = page.locator('input[data-step3-endtime-target="1"]').first
            if await cand.count() > 0:
                input_el = cand

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
        await item.evaluate("""(node) => {
            const input = node.querySelector('input');
            if (!input) return;
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

async def fill_step3_send_content(page, content: str) -> bool:
    """第3步发送内容：固定写入“发送内容”对应编辑器，并清除默认值。"""
    item = page.locator('.item', has=page.locator('span.label', has_text='发送内容')).first
    if await item.count() == 0:
        item = page.locator('.item', has_text='发送内容').first
        if await item.count() == 0:
            return False
    editable = item.locator('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]').first
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
    item = page.locator('.item', has=page.locator('span.label.required', has_text='短信内容')).first
    if await item.count() == 0:
        item = page.locator('.item', has_text='短信内容').first
        if await item.count() == 0:
            return False
    editable = item.locator('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]').first
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
        length_el = item.locator(".length").first
        if await length_el.count() > 0:
            length_text = ((await length_el.text_content()) or "").strip()
            m = re.search(r"(\\d+)\\s*/", length_text)
            if m and int(m.group(1)) <= 0:
                return False
    except:
        pass
    return True

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

async def ensure_step3_saved(page, save_resp_task=None) -> bool:
    """确保第3步保存真正提交：处理确认弹窗并等待成功提示。"""
    # 某些页面点击“保存”后会弹二次确认，先尝试确认。
    confirm_selectors = [
        '.el-message-box__btns button:has-text("确定")',
        '.el-message-box__btns button:has-text("确认")',
        '.el-dialog__footer button:has-text("确定")',
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

    # 读取保存接口响应，输出 status/code/message 便于后端定位。
    api_diag = ""
    if save_resp_task is not None:
        try:
            resp = await asyncio.wait_for(save_resp_task, timeout=12)
            if resp is not None:
                body = await resp.text()
                code, msg = extract_api_code_message(body)
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
                api_diag = f"url={resp.url}, status={resp.status}, code={code}, msg={msg}, reqLen={len(post_data or '')}, req={post_excerpt}"
                print(f"      🧪 保存接口响应: {api_diag}")
                content_diag = summarize_content_fields_from_payload(post_data)
                if content_diag:
                    print(f"      🧪 请求体内容字段诊断: {content_diag}")
        except asyncio.TimeoutError:
            pass
        except Exception:
            api_diag = ""

    # 等待成功提示；同屏失败提示也要拦截。
    try:
        toast = page.locator(".el-message__content, .ant-message-custom-content").first
        await toast.wait_for(timeout=7000)
        msg = ((await toast.text_content()) or "").strip()
        if any(k in msg for k in ["成功", "已保存", "保存完成"]):
            return True
        if any(k in msg for k in ["失败", "错误", "重复", "不能为空", "请先", "未通过"]):
            suffix = f" | {api_diag}" if api_diag else ""
            raise RuntimeError(f"保存失败提示: {msg}{suffix}")
    except PlaywrightTimeout:
        pass

    # 无 toast 时，回退到 URL 变化判定。
    moved = ("marketingTemplate/use" not in page.url) or ("limitList" in page.url)
    if (not moved) and api_diag:
        print(f"      ⚠️ 未检测到成功跳转，接口信息: {api_diag}")
    if not moved:
        await asyncio.sleep(0.6)
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

    # 策略1：Playwright 定位主按钮并强制点击
    try:
        save_btn = page.locator("button.el-button.el-button--primary.el-button--small:visible").filter(has_text="保存").first
        if await save_btn.count() > 0:
            await save_btn.scroll_into_view_if_needed()
            await save_btn.click(force=True)
            return True
    except:
        pass

    # 策略2：JS 直接 click（基于你提供的 class + 文案）
    try:
        clicked_js = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button.el-button.el-button--primary.el-button--small'));
            for (const btn of btns) {
                const txt = (btn.textContent || '').trim();
                const style = window.getComputedStyle(btn);
                const rect = btn.getBoundingClientRect();
                if (!txt.includes('保存')) continue;
                if (style.display === 'none' || style.visibility === 'hidden' || rect.width <= 0 || rect.height <= 0) continue;
                btn.click();
                return true;
            }
            return false;
        }""")
        if clicked_js:
            return True
    except:
        pass

    # 策略3：按文本兜底
    return await click_button_with_text(page, "保存", exclude_text="取消")

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
        item = page.locator('.item', has=page.locator('span.label.required', has_text='短信内容')).first
        if await item.count() == 0:
            item = page.locator('.item', has_text='短信内容').first
            if await item.count() == 0:
                return ""
        editable = item.locator('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]').first
        if await editable.count() == 0:
            return ""
        txt = (await editable.inner_text()) or ""
        return txt.strip()
    except Exception:
        return ""

async def read_step3_send_text(page) -> str:
    """读取第3步发送内容编辑器文本。"""
    try:
        item = page.locator('.item', has=page.locator('span.label', has_text='发送内容')).first
        if await item.count() == 0:
            item = page.locator('.item', has_text='发送内容').first
            if await item.count() == 0:
                return ""
        editable = item.locator('.div-editable .editable[contenteditable="true"], .editable[contenteditable="true"]').first
        if await editable.count() == 0:
            return ""
        txt = (await editable.inner_text()) or ""
        return txt.strip()
    except Exception:
        return ""

async def set_step3_distribution_mode(page, mode_text: str = "指定门店分配") -> bool:
    """第3步分配方式：点击单选文本。"""
    return await page.evaluate(
        """(modeText) => {
            const labels = Array.from(document.querySelectorAll('label, span, div'));
            for (const el of labels) {
                const txt = (el.textContent || '').replace(/\\s+/g, '');
                if (txt.includes(modeText)) {
                    (el.closest('label') || el).click();
                    return true;
                }
            }
            return false;
        }""",
        mode_text
    )

async def fill_step3_executor(page, raw_values: str) -> bool:
    """第3步执行员工：按级联面板（全国->大区->省区/门店）多选。"""
    targets = split_multi_values(raw_values)
    if not targets:
        return True

    opened = await page.evaluate("""() => {
        const labels = Array.from(document.querySelectorAll('.item .label, .el-form-item__label, .ant-form-item-label label'));
        for (const label of labels) {
            const txt = (label.textContent || '').replace(/\\s+/g, '');
            if (!txt.includes('执行员工')) continue;
            const item = label.closest('.item, .el-form-item, .ant-form-item') || label.parentElement;
            if (!item) continue;
            const input = item.querySelector('input.el-input__inner[placeholder*="请选择"], input[placeholder*="请选择"], .el-cascader input.el-input__inner');
            if (input) {
                input.click();
                return true;
            }
        }
        return false;
    }""")
    if not opened:
        return False
    await asyncio.sleep(0.3)

    panel = page.locator(".el-cascader-panel:visible").first
    menus = panel.locator(".el-cascader-menu")

    async def expand_in_menu(menu_index: int, target: str) -> bool:
        menu = menus.nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            if txt != target and target not in txt:
                continue
            await label.scroll_into_view_if_needed()
            postfix = node.locator(".el-cascader-node__postfix").first
            if await postfix.count() > 0:
                await postfix.hover()
                await postfix.click(force=True)
            else:
                await label.hover()
            await asyncio.sleep(0.2)
            return True
        return False

    async def check_in_menu(menu_index: int, target: str) -> bool:
        menu = menus.nth(menu_index)
        nodes = menu.locator(".el-cascader-node")
        count = await nodes.count()
        for i in range(count):
            node = nodes.nth(i)
            label = node.locator(".el-cascader-node__label").first
            if await label.count() == 0:
                continue
            txt = ((await label.text_content()) or "").strip()
            if txt != target and target not in txt:
                continue
            checkbox = node.locator(".el-checkbox__input").first
            if await checkbox.count() == 0:
                continue
            await checkbox.scroll_into_view_if_needed()
            cls = (await checkbox.get_attribute("class")) or ""
            if "is-checked" not in cls:
                await checkbox.click(force=True)
                await asyncio.sleep(0.15)
            return True
        return False

    # 先点全国，展开大区列
    await expand_in_menu(0, "全国")

    selected = {t: False for t in targets}
    region_targets = [t for t in targets if "大区" in t]
    province_targets = [t for t in targets if "省区" in t or "营运区" in t or "店" in t]

    # 先选大区目标（例如西北大区）
    for rt in region_targets:
        selected[rt] = await check_in_menu(1, rt)

    # 再跨大区选省区目标（例如湖北省区）
    region_nodes = menus.nth(1).locator(".el-cascader-node .el-cascader-node__label")
    region_count = await region_nodes.count()
    region_names = []
    for i in range(region_count):
        txt = ((await region_nodes.nth(i).text_content()) or "").strip()
        if txt.endswith("大区"):
            region_names.append(txt)

    for region in region_names:
        await expand_in_menu(1, region)
        for pt in province_targets:
            if selected.get(pt):
                continue
            if await check_in_menu(2, pt):
                selected[pt] = True

    selected_labels = await page.evaluate("""() => {
        const panel = document.querySelector('.el-cascader-panel');
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

    print(f"      🧪 执行员工回读文本: {readback}")
    return all(selected.values())

async def set_plan_time_range(page, start_time: str, end_time: str):
    """设置 Element 日期范围并点击确定，避免值未提交。"""
    s_date, s_time = split_datetime(start_time)
    e_date, e_time = split_datetime(end_time)
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
    theme_ok = await select_option(page, "营销主题", data.get("theme", "其他"))
    if not theme_ok:
        await asyncio.sleep(0.5)
        theme_ok = await select_option(page, "营销主题", data.get("theme", "其他"))
    if not theme_ok:
        raise RuntimeError("第1步失败：营销主题未选择成功")
    results["第1步-营销主题"] = True
    
    print("   ⏭️  场景类型、计划类型: 跳过（已预设）")
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
        if not clicked:
            raise RuntimeError("第1步完成后未能点击“下一步”")
        print("      ✅ 点击成功")
        results["第1步-下一步按钮"] = True
        await wait_and_log(page, 3, "等待页面跳转...")
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
        "第2步-主页面回读": False,
        "第2步-分群名称": False,
        "第2步-更新方式": False,
        "第2步-主消费营运区": False,
        "第2步-券规则ID": False,
        "第2步-预跑按钮": False,
        "第2步-弹窗确认": False,
        "第2步-下一步按钮": False,
    }
    
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
                    # 内网/代理异常时常见现象：iframe 空白或加载失败，提前抛错避免“假成功”。
                    frame_diag = await frame.evaluate("""() => {
                        const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').trim();
                        return {
                            href: location.href || '',
                            title: document.title || '',
                            textLen: bodyText.length,
                            hasErrKeyword: /ERR_|无法访问|无法连接|network|proxy|超时/i.test(bodyText + ' ' + (document.title || ''))
                        };
                    }""")
                    print(f"      iframe诊断: href={frame_diag.get('href','')}, title={frame_diag.get('title','')}, textLen={frame_diag.get('textLen',0)}")
                    if frame_diag.get("textLen", 0) == 0 or frame_diag.get("hasErrKeyword"):
                        raise RuntimeError("第2步 iframe 内容为空或疑似网络/代理异常，请检查 VPN/代理并重试")

                    # 在 iframe 内填充名称（按标签就近定位 + 回读）
                    print("   📝 名称: " + data.get("group_name", "测试分群"))
                    try:
                        group_name_val = data.get("group_name", "测试分群")
                        name_ok = await frame.evaluate("""(val) => {
                            const labels = Array.from(document.querySelectorAll('label, span, div'));
                            const write = (inp, v) => {
                                if (!inp) return false;
                                inp.focus();
                                inp.value = v;
                                inp.dispatchEvent(new Event('input', { bubbles: true }));
                                inp.dispatchEvent(new Event('change', { bubbles: true }));
                                inp.blur();
                                return (inp.value || '').includes(v);
                            };
                            for (const lb of labels) {
                                const t = (lb.textContent || '').replace(/\\s+/g, '');
                                if (!t.includes('名称')) continue;
                                const scope = lb.closest('.ant-form-item, .el-form-item, .item') || lb.parentElement;
                                if (!scope) continue;
                                const inp = scope.querySelector('input');
                                if (write(inp, val)) return true;
                            }
                            const fallback = document.querySelector('input[placeholder*="名称"], input[placeholder*="请输入"]');
                            return write(fallback, val);
                        }""", group_name_val)
                        if name_ok:
                            print("      ✅ 已填充名称")
                            results["第2步-分群名称"] = True
                        else:
                            print("      ⚠️ 名称回读不一致")
                    except Exception as e:
                        print(f"      ⚠️ 填充名称失败: {e}")
                    
                    # 在 iframe 内选择更新方式（回读校验）
                    print("   ⚪ 更新方式: " + data.get("update_type", "自动更新"))
                    try:
                        if "自动" in data.get("update_type", ""):
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
                    except Exception as e:
                        print(f"      ⚠️ 更新方式选择失败: {e}")
                    
                    # 在 iframe 内点击选择数据按钮
                    if data.get("main_operating_area"):
                        print(f"   🏢 主消费营运区: {data['main_operating_area']}")
                        try:
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
                                
                                # 在树形选择器中选择营运区
                                area = data['main_operating_area']
                                print(f"      🔍 选择营运区: {area}")
                                
                                # 先找到包含"华南"的父节点并展开
                                parent_keyword = "华南"  # 广佛省区的父节点
                                print(f"      📂 先展开父节点: {parent_keyword}")
                                
                                expand_result = await frame.evaluate("""
                                () => {
                                    const keyword = '""" + parent_keyword + """';
                                    const nodes = document.querySelectorAll('.ant-tree-treenode');
                                    for (const node of nodes) {
                                        const title = node.querySelector('.ant-tree-title');
                                        if (title && title.textContent.includes(keyword)) {
                                            const switcher = node.querySelector('.ant-tree-switcher');
                                            if (switcher && !switcher.classList.contains('ant-tree-switcher_open')) {
                                                switcher.click();
                                                return 'expanded_' + title.textContent;
                                            }
                                            return 'already_open_' + title.textContent;
                                        }
                                    }
                                    return 'not_found';
                                }
                                """)
                                print(f"         展开结果: {expand_result}")
                                
                                await asyncio.sleep(1.5)
                                
                                # 使用字符串拼接避免 f-string 问题
                                js_find_node = """
                                () => {
                                    const targetArea = '""" + area + """';
                                    const nodes = Array.from(document.querySelectorAll('.ant-tree-treenode'));
                                    const findNode = () => {
                                        for (const n of nodes) {
                                            const title = n.querySelector('.ant-tree-title') || n.querySelector('[title]');
                                            const txt = (title?.textContent || '').trim();
                                            if (txt.includes(targetArea)) return n;
                                        }
                                        return null;
                                    };
                                    const node = findNode();
                                    if (!node) return 'not_found';
                                    const checkbox = node.querySelector('.ant-tree-checkbox');
                                    if (!checkbox) return 'checkbox_not_found';
                                    if (checkbox.classList.contains('ant-tree-checkbox-checked')) return 'already_checked';
                                    checkbox.click();
                                    if (!checkbox.classList.contains('ant-tree-checkbox-checked')) {
                                        const inner = checkbox.querySelector('.ant-tree-checkbox-inner');
                                        if (inner) inner.click();
                                    }
                                    return checkbox.classList.contains('ant-tree-checkbox-checked') ? 'checked' : 'click_no_effect';
                                }
                                """
                                selected = await frame.evaluate(js_find_node)
                                
                                if selected in ['checked', 'already_checked']:
                                    print(f"      ✅ 已选择营运区: {area}")
                                    # 只关闭“选择数据”小弹窗，不关闭“编辑分群”大弹窗。
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
                                    if confirm_area_result.get("ok") and not picker_still_visible and selected_count_text:
                                        print(f"      ✅ 营运区已确认: {selected_count_text}")
                                        results["第2步-主消费营运区"] = True
                                    else:
                                        print(
                                            "      ⚠️ 营运区确认失败: "
                                            f"reason={confirm_area_result.get('reason','')}, "
                                            f"pickerStillVisible={picker_still_visible}, "
                                            f"selectedCount={selected_count_text or confirm_area_result.get('selectedCount','')}"
                                        )
                                else:
                                    print(f"      ⚠️ 营运区勾选失败: {area} ({selected})")
                            else:
                                # 兜底2：某些页面树已默认展开，直接尝试勾选
                                print("      ⚠️ 未找到选择数据按钮，尝试直接在当前树中勾选...")
                                area = data['main_operating_area']
                                selected_direct = await frame.evaluate("""
                                () => {
                                    const targetArea = '""" + area_escaped + """';
                                    const nodes = Array.from(document.querySelectorAll('.ant-tree-treenode'));
                                    for (const n of nodes) {
                                        const title = n.querySelector('.ant-tree-title') || n.querySelector('[title]');
                                        const txt = (title?.textContent || '').trim();
                                        if (!txt.includes(targetArea)) continue;
                                        const cb = n.querySelector('.ant-tree-checkbox');
                                        if (!cb) return 'checkbox_not_found';
                                        if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                            cb.click();
                                            if (!cb.classList.contains('ant-tree-checkbox-checked')) {
                                                const inner = cb.querySelector('.ant-tree-checkbox-inner');
                                                if (inner) inner.click();
                                            }
                                        }
                                        return cb.classList.contains('ant-tree-checkbox-checked') ? 'checked' : 'click_no_effect';
                                    }
                                    return 'not_found';
                                }
                                """)
                                if selected_direct == "checked":
                                    print(f"      ✅ 已直接勾选营运区: {area}")
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
                                    if confirm_area_result.get("ok") and not picker_still_visible and selected_count_text:
                                        print(f"      ✅ 营运区已确认: {selected_count_text}")
                                        results["第2步-主消费营运区"] = True
                                    else:
                                        print(
                                            "      ⚠️ 营运区确认失败: "
                                            f"reason={confirm_area_result.get('reason','')}, "
                                            f"pickerStillVisible={picker_still_visible}, "
                                            f"selectedCount={selected_count_text or confirm_area_result.get('selectedCount','')}"
                                        )
                                else:
                                    print(f"      ⚠️ 直接勾选失败: {selected_direct}，请检查第2步页面是否空白/未加载完整")
                        except Exception as e:
                            print(f"      ⚠️ 主消费营运区操作失败: {e}")
                    
                    # 在 iframe 内填充券规则ID（按标签就近定位 + 回读）
                    if data.get("coupon_ids"):
                        print(f"   🎫 券规则ID: {data['coupon_ids']}")
                        try:
                            coupon_val = data["coupon_ids"]
                            coupon_ok = await frame.evaluate("""(val) => {
                                const labels = Array.from(document.querySelectorAll('label, span, div'));
                                const write = (inp, v) => {
                                    if (!inp) return false;
                                    inp.focus();
                                    inp.value = v;
                                    inp.dispatchEvent(new Event('input', { bubbles: true }));
                                    inp.dispatchEvent(new Event('change', { bubbles: true }));
                                    inp.blur();
                                    return (inp.value || '').includes(v);
                                };
                                for (const lb of labels) {
                                    const t = (lb.textContent || '').replace(/\\s+/g, '');
                                    if (!t.includes('券规则ID') && !t.includes('券规则')) continue;
                                    const scope = lb.closest('.ant-form-item, .el-form-item, .item') || lb.parentElement;
                                    if (!scope) continue;
                                    const inp = scope.querySelector('input');
                                    if (write(inp, val)) return true;
                                }
                                const fallback = document.querySelector('input[placeholder*="券规则"]');
                                return write(fallback, val);
                            }""", coupon_val)
                            if coupon_ok:
                                print("      ✅ 已填充券规则ID")
                                results["第2步-券规则ID"] = True
                            else:
                                print("      ⚠️ 券规则ID回读不一致")
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
        await fill_input(page, "名称", data.get("group_name", "测试分群"))
        results["第2步-分群名称"] = True
        await select_radio(page, "更新方式", data.get("update_type", "自动更新"))
        results["第2步-更新方式"] = True
        if data.get("coupon_ids"):
            await fill_input(page, "券规则ID", data["coupon_ids"])
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
            print("      ⚠️ 未找到预跑按钮")
    except Exception as e:
        print(f"      ⚠️ 预跑点击失败: {e}")

    # 大弹窗保存分群并关闭
    print("   ✅ 弹窗内确认保存分群...")
    try:
        if not results.get("第2步-主消费营运区"):
            raise RuntimeError("主消费营运区未真正勾选，禁止确认弹窗")
        frame_handle = await page.query_selector('iframe')
        frame = await frame_handle.content_frame() if frame_handle else None
        if not frame:
            raise RuntimeError("未找到编辑分群 iframe")
        confirmed = await frame.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            };
            const btns = Array.from(document.querySelectorAll('button')).filter(isVisible);
            const hit = btns.find(b => ((b.textContent || '').replace(/\\s+/g, '')).includes('保存'));
            if (hit) {
                hit.click();
                return true;
            }
            return false;
        }""")
        if confirmed:
            await asyncio.sleep(1.0)
            iframe_count_after = await page.locator("iframe").count()
            if iframe_count_after == 0:
                print("      ✅ 编辑分群弹窗已关闭")
                results["第2步-弹窗确认"] = True
            else:
                print(f"      ⚠️ 编辑分群弹窗未关闭（iframe={iframe_count_after}）")
        else:
            print("      ⚠️ 未找到编辑分群弹窗保存按钮")
    except Exception as e:
        print(f"      ⚠️ 弹窗确认失败: {e}")

    # 主页面回读：确认分群信息已带回（名称或营运区至少一项出现）
    try:
        await asyncio.sleep(0.8)
        group_name_val = data.get("group_name", "")
        area_val = data.get("main_operating_area", "")
        main_readback_ok = await page.evaluate("""(payload) => {
            const groupName = payload.groupName || '';
            const areaName = payload.areaName || '';
            const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
            const hasGroup = groupName ? bodyText.includes(groupName) : false;
            const hasArea = areaName ? bodyText.includes(areaName) : false;
            return hasGroup || hasArea;
        }""", {"groupName": group_name_val, "areaName": area_val})
        if main_readback_ok:
            print("      ✅ 主页面回读通过（分群信息已带回）")
            results["第2步-主页面回读"] = True
        else:
            print("      ⚠️ 主页面回读失败（未检测到分群名称/营运区）")
    except Exception as e:
        print(f"      ⚠️ 主页面回读异常: {e}")

    # 严格模式下，字段级回读失败也要终止，避免“日志看着成功”。
    if strict_step2:
        required_keys = ["第2步-编辑按钮", "第2步-弹窗可见", "第2步-分群名称", "第2步-更新方式", "第2步-主消费营运区", "第2步-券规则ID", "第2步-预跑按钮", "第2步-弹窗确认", "第2步-主页面回读"]
        failed = [k for k in required_keys if not results.get(k, False)]
        if failed:
            raise RuntimeError(f"第2步字段回读未通过: {failed}")
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-modal-filled.png')
    
    print("\n   ✅ 第2步完成")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-after-main.png')
    
    print("   ⏭️  点击下一步...")
    clicked = await click_button_with_text(page, "下一步")
    if not clicked:
        raise RuntimeError("第2步完成后未能点击“下一步”")
    print("      ✅ 点击成功")
    results["第2步-下一步按钮"] = True
    
    await wait_and_log(page, 2, "跳转到第3步...")
    return results

async def skip_step2(page):
    """跳过第2步内容，仅点击下一步进入第3步。"""
    print("\n📋 第2步：目标分群（跳过模式）")
    print("=" * 50)
    await wait_and_log(page, 2, "等待第2步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-skipped.png')

    print("   ⏭️  跳过第2步内容，直接点击下一步...")
    clicked = await click_button_with_text(page, "下一步")

    if not clicked:
        raise RuntimeError("跳过第2步失败：未找到可点击的“下一步”按钮")

    print("      ✅ 已进入第3步")
    await wait_and_log(page, 2, "跳转到第3步...")
    return {"第2步-跳过下一步按钮": True}

# ============ 第3步：触达内容 ============

async def fill_step3(page, data: dict, manual_executor_mode: bool = False, executor_check_override: str = ""):
    """填充第3步：触达内容/短信内容"""
    print("\n📋 第3步：短信内容")
    print("="*50)
    
    await wait_and_log(page, 2, "等待第3步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-before.png')
    
    results = {}
    print("   📝 短信内容...")
    sms_content = data.get("sms_content", "测试短信内容")
    sms_content_clean = sanitize_sms_content(sms_content)
    if sms_content_clean != sms_content:
        print(f"      ⚠️ 短信文案已自动清洗非法字符: {sms_content} -> {sms_content_clean}")
    sms_content = sms_content_clean
    try:
        sms_ok = await fill_step3_sms_content(page, sms_content)
        if not sms_ok:
            raise RuntimeError("未找到可写入的短信内容输入框")
        print(f"      ✅ 已填充: {sms_content[:30]}...")
        results["第3步-短信内容"] = True
    except Exception as e:
        print(f"      ⚠️ 填充失败: {e}")
        results["第3步-短信内容"] = False

    # 新增字段：结束时间
    step3_end_time = data.get("step3_end_time") or data.get("end_time")
    print(f"   📅 结束时间: {step3_end_time}")
    end_ok = await fill_step3_end_time(page, step3_end_time)
    print(f"      {'✅' if end_ok else '⚠️'} 结束时间{'已填充' if end_ok else '未匹配到字段'}")
    results["第3步-结束时间"] = end_ok

    # 新增字段：执行员工（多选）
    executor_vals = data.get("executor_employees", "")
    mode_ok = await set_step3_distribution_mode(page, "指定门店分配")
    print(f"   ⚙️ 分配方式: {'指定门店分配' if mode_ok else '未找到分配方式控件'}")
    print(f"   👥 执行员工: {executor_vals}")
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
    else:
        exec_ok = await fill_step3_executor(page, executor_vals)
        print(f"      {'✅' if exec_ok else '⚠️'} 执行员工{'已选择' if exec_ok else '未完整选择'}")
        results["第3步-执行员工"] = exec_ok
        debug_data = await dump_executor_debug(page)
        targets = split_multi_values(executor_vals)
        overlap_msg = detect_executor_overlap_conflict(debug_data, targets)
        if overlap_msg:
            print(f"      ⚠️ {overlap_msg}（当前按业务场景仅提示，不阻断保存）")

    # 新增字段：发送内容
    send_content = data.get("send_content", "")
    print(f"   📝 发送内容: {send_content}")
    send_ok = await fill_step3_send_content(page, send_content)
    print(f"      {'✅' if send_ok else '⚠️'} 发送内容{'已填充' if send_ok else '未匹配到字段'}")
    results["第3步-发送内容"] = send_ok

    # 通知配置场景：将当前配置复制到其他地区，避免部分地区短信为空导致 P1114。
    # 默认不自动执行“渠道信息复制”，避免在部分页面触发内容重置副作用。
    print("   📎 渠道信息复制: ⏭️ 默认关闭（避免副作用）")
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-after.png')
    
    print("\n   ✅ 第3步完成")
    
    print("   💾 点击保存...")
    sms_before_save = await read_step3_sms_text(page)
    if len(sms_before_save) == 0 and sms_content:
        print("      ⚠️ 保存前短信为空，执行一次重填...")
        refill_ok = await fill_step3_sms_content(page, sms_content)
        print(f"      {'✅' if refill_ok else '⚠️'} 重填短信{'成功' if refill_ok else '失败'}")
        sms_before_save = await read_step3_sms_text(page)
    print(f"      🧪 保存前短信回读长度: {len(sms_before_save)}")
    send_before_save = await read_step3_send_text(page)
    if len(send_before_save) == 0 and send_content:
        print("      ⚠️ 保存前发送内容为空，执行一次重填...")
        refill_send_ok = await fill_step3_send_content(page, send_content)
        print(f"      {'✅' if refill_send_ok else '⚠️'} 重填发送内容{'成功' if refill_send_ok else '失败'}")
        send_before_save = await read_step3_send_text(page)
    print(f"      🧪 保存前发送内容回读长度: {len(send_before_save)}")
    loop = asyncio.get_running_loop()
    save_resp_task = loop.create_future()

    def _on_response(r):
        try:
            url_l = (r.url or "").lower()
            matched = (
                r.request.method in ("POST", "PUT")
                and (
                    ("/api/" in url_l and "precision.dslyy.com" in url_l)
                    or "marketingtemplate" in url_l
                    or "template" in url_l
                    or "save" in url_l
                )
            )
            if matched and (not save_resp_task.done()):
                save_resp_task.set_result(r)
        except Exception:
            pass

    page.on("response", _on_response)
    clicked = await click_step3_save_button(page)
    if not clicked:
        if not save_resp_task.done():
            save_resp_task.set_result(None)
        raise RuntimeError("第3步未能点击“保存”")
    print("      ✅ 点击保存成功")
    results["第3步-保存按钮"] = True
    
    await wait_and_log(page, 2, "保存中...")
    sms_after_click = await read_step3_sms_text(page)
    print(f"      🧪 点击保存后短信回读长度: {len(sms_after_click)}")
    send_after_click = await read_step3_send_text(page)
    print(f"      🧪 点击保存后发送内容回读长度: {len(send_after_click)}")
    saved_ok = await ensure_step3_saved(page, save_resp_task=save_resp_task)
    try:
        page.remove_listener("response", _on_response)
    except Exception:
        pass
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
                    cls: n.className || ''
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
    checked_texts = [str(n.get("text", "")).strip() for n in checked if isinstance(n, dict)]
    has_country_checked = any(t == "全国" for t in checked_texts)
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
        browser = await p.chromium.connect_over_cdp(cdp_endpoint)
        if not browser.contexts:
            # CDP 模式下通常至少有 1 个默认上下文，这里兜底。
            await browser.new_context()
        return browser

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
    executor_check_override: str = ""
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
                await page.goto(BASE_URL)
                await wait_and_log(page, 2, "页面加载中...")

                if skip_step2_mode:
                    field_results.update(await fill_step1(page, plan, auto_next=True))
                    field_results.update(await skip_step2(page))
                else:
                    field_results.update(await fill_step1(page, plan, auto_next=False))
                    field_results.update(await fill_step2(page, plan, strict_step2=strict_step2))
                field_results.update(await fill_step3(
                    page,
                    plan,
                    manual_executor_mode=manual_executor_mode,
                    executor_check_override=executor_check_override
                ))
                
                print(f"\n   ✅ 计划 {plan_index} 完成！")
                print("   📌 字段结果清单:")
                for k in sorted(field_results.keys()):
                    mark = "✅" if field_results[k] else "❌"
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
                args.executor_check_only
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
