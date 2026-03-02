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
}

HEADLESS = False
SLOW_MO = 100
MAX_RETRIES = 2
MAX_CONCURRENT = 3
FEISHU_USER_ID = "ou_ed20f9990c63fa5448a0f2cd613ecf30"

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
                "name": row["name"],
                "region": row["region"],
                "theme": row["theme"],
                "use_recommend": row["use_recommend"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "trigger_type": row["trigger_type"],
                "send_time": row["send_time"],
                "global_limit": row["global_limit"],
                "set_target": row["set_target"],
                "group_name": row["group_name"],
                "update_type": row["update_type"],
                "coupon_ids": row["coupon_ids"],
                "sms_content": row["sms_content"],
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

async def select_option(page, label: str, value: str, is_multi: bool = False):
    """选择下拉选项（Element UI / Ant Design）"""
    print(f"   🏷️  {label}: {value}")
    
    form_items = page.locator('.el-form-item, .ant-form-item')
    count = await form_items.count()
    
    for i in range(count):
        item = form_items.nth(i)
        label_el = item.locator('.el-form-item__label, .ant-form-item-label label')
        try:
            text = await label_el.text_content()
            if text.strip() == label or label in text and len(text.strip()) < len(label) + 5:
                input_el = item.locator('.el-input__inner, .ant-input, .ant-select-selector').first
                await input_el.click(force=True)
                await asyncio.sleep(0.8)
                
                options = page.locator('.el-select-dropdown__item:visible, .ant-select-item:visible')
                opt_count = await options.count()
                
                if opt_count > 0:
                    all_options = []
                    for j in range(min(opt_count, 10)):
                        try:
                            opt_text = await options.nth(j).text_content()
                            all_options.append(opt_text.strip())
                        except:
                            pass
                    print(f"      可选项: {all_options[:5]}")
                
                for j in range(opt_count):
                    opt_text = await options.nth(j).text_content()
                    clean_text = opt_text.strip()
                    if value in clean_text or clean_text in value:
                        await options.nth(j).click(force=True)
                        print(f"      ✅ 已选择: {clean_text}")
                        await asyncio.sleep(0.3)
                        return
                
                print(f"      ⚠️ 未找到选项: {value}")
                await page.keyboard.press('Escape')
                await asyncio.sleep(0.3)
                return
        except:
            continue
    
    print(f"      ⚠️ 未找到字段: {label}")

async def fill_input(page, label: str, value: str):
    """填充文本输入框"""
    print(f"   📝 {label}: {value}")
    
    try:
        input_el = page.locator(f'input[placeholder*="{label}"]').first
        await input_el.fill(value)
        await input_el.blur()
        return
    except:
        pass
    
    form_items = page.locator('.el-form-item, .ant-form-item')
    count = await form_items.count()
    
    for i in range(count):
        item = form_items.nth(i)
        label_el = item.locator('.el-form-item__label, .ant-form-item-label label')
        try:
            text = await label_el.text_content()
            if label in text:
                input_el = item.locator('input[type="text"], input:not([type])').first
                await input_el.fill(value)
                await input_el.blur()
                print(f"      ✅ 已填充")
                return
        except:
            continue

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

# ============ 第1步：基础信息 ============

async def fill_step1(page, data: dict):
    """填充第1步"""
    print("\n📋 第1步：基础信息")
    print("="*50)
    
    await page.wait_for_selector('.el-form, .ant-form', timeout=10000)
    await wait_and_log(page, 2, "页面加载中...")
    
    await fill_input(page, "计划名称", data["name"])
    await select_option(page, "计划区域", data["region"])
    await select_option(page, "营销主题", data.get("theme", "其他"))
    
    print("   ⏭️  场景类型、计划类型: 跳过（已预设）")
    print("   ⏭️  营销模板: 跳过")
    
    await select_radio(page, "推荐算法", data["use_recommend"])
    await fill_input(page, "开始日期", data["start_time"])
    await fill_input(page, "结束日期", data["end_time"])
    await select_radio(page, "触发方式", data["trigger_type"])
    await fill_input(page, "发送时间", data["send_time"])
    await select_radio(page, "触达限制", data["global_limit"])
    await select_radio(page, "设置目标", data["set_target"])
    
    print("\n   ✅ 第1步完成")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step1-after.png')
    
    print("   ⏭️  点击下一步...")
    try:
        await page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('下一步')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')
        print("      ✅ 点击成功")
    except Exception as e:
        print(f"      ⚠️ 点击失败: {e}")
    
    await wait_and_log(page, 3, "等待页面跳转...")

# ============ 第2步：目标分群 ============

async def fill_step2(page, data: dict):
    """填充第2步：目标分群"""
    print("\n📋 第2步：目标分群")
    print("="*50)
    
    await wait_and_log(page, 2, "等待第2步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-before.png')
    
    print("   🖱️  点击分群的编辑按钮...")
    try:
        await page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('编辑')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')
        print("      ✅ JavaScript点击成功")
    except Exception as e:
        print(f"      ⚠️ 点击失败: {e}")
    
    await wait_and_log(page, 3, "弹窗加载中...")
    
    # 处理可能的浏览器弹窗（如本地网络权限）
    try:
        page.on('dialog', lambda dialog: dialog.accept())
    except:
        pass
    
    # 检测弹窗内是否有 iframe
    print("   🔍 检测弹窗内的 iframe...")
    iframe_info = await page.evaluate('''() => {
        const iframes = document.querySelectorAll('iframe');
        const info = [];
        iframes.forEach((iframe, i) => {
            info.push({
                index: i,
                src: iframe.src || '',
                id: iframe.id || '',
                name: iframe.name || ''
            });
        });
        return info;
    }''')
    print(f"      找到 {len(iframe_info)} 个 iframe")
    
    # 等待弹窗/iframe 内容加载 - 增加等待时间
    print("   ⏳ 等待 iframe 内容加载...")
    await asyncio.sleep(5)  # 增加到5秒
    
    if iframe_info:
        print("   🔧 在 iframe 内执行操作...")
        try:
            # 获取 frame 对象
            frame_handle = await page.query_selector('iframe')
            if frame_handle:
                frame = await frame_handle.content_frame()
                if frame:
                    # 在 iframe 内填充名称
                    print("   📝 名称: " + data.get("group_name", "测试分群"))
                    try:
                        name_input = frame.locator('input[placeholder*="名称"], input[placeholder*="请输入"]').first
                        if await name_input.count() > 0:
                            await name_input.fill(data.get("group_name", "测试分群"))
                            print("      ✅ 已填充名称")
                    except Exception as e:
                        print(f"      ⚠️ 填充名称失败: {e}")
                    
                    # 在 iframe 内选择更新方式 - 用 JavaScript 绕过可见性检查
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
                            print("      ✅ 已选择自动更新")
                    except Exception as e:
                        print(f"      ⚠️ 更新方式选择失败: {e}")
                    
                    # 在 iframe 内点击选择数据按钮
                    if data.get("main_operating_area"):
                        print(f"   🏢 主消费营运区: {data['main_operating_area']}")
                        try:
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
                                    const allNodes = document.querySelectorAll('.ant-tree-node-content-wrapper, .ant-tree-title, [title]');
                                    for (const node of allNodes) {
                                        if (node.textContent.includes(targetArea)) {
                                            const parent = node.closest('.ant-tree-treenode') || node.parentElement;
                                            const checkbox = parent ? parent.querySelector('.ant-checkbox') : null;
                                            if (checkbox && !checkbox.classList.contains('ant-checkbox-checked')) {
                                                checkbox.click();
                                                return 'checked';
                                            }
                                            return 'already_checked';
                                        }
                                    }
                                    return 'not_found';
                                }
                                """
                                selected = await frame.evaluate(js_find_node)
                                
                                if selected in ['checked', 'already_checked']:
                                    print(f"      ✅ 已选择营运区: {area}")
                                    # 点击确定
                                    await frame.evaluate('''() => {
                                        const btns = document.querySelectorAll('button');
                                        for (const btn of btns) {
                                            if (btn.textContent.includes('确定')) {
                                                btn.click();
                                            }
                                        }
                                    }''')
                                else:
                                    print(f"      ⚠️ 仍未找到: {area}")
                            else:
                                print("      ⚠️ 未找到选择数据按钮")
                        except Exception as e:
                            print(f"      ⚠️ 主消费营运区操作失败: {e}")
                    
                    # 在 iframe 内填充券规则ID
                    if data.get("coupon_ids"):
                        print(f"   🎫 券规则ID: {data['coupon_ids']}")
                        try:
                            coupon_input = frame.locator('input[placeholder*="券规则"]').first
                            if await coupon_input.count() > 0:
                                await coupon_input.fill(data["coupon_ids"])
                                print("      ✅ 已填充券规则ID")
                        except Exception as e:
                            print(f"      ⚠️ 券规则ID填充失败: {e}")
                else:
                    print("   ⚠️ 无法获取 frame 内容")
            else:
                print("   ⚠️ 未找到 iframe 元素")
        except Exception as e:
            print(f"   ⚠️ iframe 操作失败: {e}")
    else:
        print("   ⚠️ 未检测到 iframe，使用普通方式填充")
        await fill_input(page, "名称", data.get("group_name", "测试分群"))
        await select_radio(page, "更新方式", data.get("update_type", "自动更新"))
        if data.get("coupon_ids"):
            await fill_input(page, "券规则ID", data["coupon_ids"])
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step2-modal-filled.png')
    
    # 预跑按钮
    print("   🔍 点击预跑...")
    try:
        await page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('预跑') || btn.textContent.includes('预览')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')
        print("      ✅ 已点击预跑")
        await wait_and_log(page, 3, "预跑执行中...")
    except Exception as e:
        print(f"      ⚠️ 预跑点击失败: {e}")
    
    print("\n   ✅ 第2步完成")
    
    print("   ⏭️  点击下一步...")
    try:
        await page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('下一步')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')
        print("      ✅ JavaScript点击成功")
    except Exception as e:
        print(f"      ⚠️ 点击失败: {e}")
    
    await wait_and_log(page, 2, "跳转到第3步...")

# ============ 第3步：触达内容 ============

async def fill_step3(page, data: dict):
    """填充第3步：触达内容/短信内容"""
    print("\n📋 第3步：短信内容")
    print("="*50)
    
    await wait_and_log(page, 2, "等待第3步加载...")
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-before.png')
    
    print("   📝 短信内容...")
    sms_content = data.get("sms_content", "测试短信内容")
    
    try:
        await page.evaluate(f'''() => {{
            const labels = document.querySelectorAll('label, .label, span');
            for (const label of labels) {{
                if (label.textContent.includes('短信内容')) {{
                    const container = label.closest('.el-form-item, .ant-form-item, .sms-content-input-container') || label.parentElement;
                    const textarea = container ? container.querySelector('textarea') : null;
                    if (textarea) {{
                        textarea.value = '{sms_content}';
                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        return true;
                    }}
                }}
            }}
            const textareas = document.querySelectorAll('textarea');
            if (textareas.length > 0) {{
                textareas[0].value = '{sms_content}';
                textareas[0].dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }}''')
        print(f"      ✅ 已填充: {sms_content[:30]}...")
    except Exception as e:
        print(f"      ⚠️ 填充失败: {e}")
    
    await page.screenshot(path='/Users/liminrong/.openclaw/workspace/memory/step3-after.png')
    
    print("\n   ✅ 第3步完成")
    
    print("   💾 点击保存...")
    try:
        await page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('保存') && !btn.textContent.includes('取消')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }''')
        print("      ✅ JavaScript点击保存成功")
    except Exception as e:
        print(f"      ⚠️ 点击失败: {e}")
    
    await wait_and_log(page, 2, "保存中...")

# ============ 并发处理 ============

async def process_single_plan(browser, plan: dict, plan_index: int, semaphore: asyncio.Semaphore) -> bool:
    """使用信号量控制并发，处理单个计划"""
    async with semaphore:
        print(f"\n{'='*60}")
        print(f"📋 计划 {plan_index}: {plan['name']}")
        print(f"{'='*60}")
        
        context = await browser.new_context()
        page = await context.new_page()
        
        for attempt in range(MAX_RETRIES):
            try:
                await page.goto(BASE_URL)
                await wait_and_log(page, 2, "页面加载中...")
                
                await fill_step1(page, plan)
                await fill_step2(page, plan)
                await fill_step3(page, plan)
                
                print(f"\n   ✅ 计划 {plan_index} 完成！")
                await context.close()
                return (plan_index, True, plan['name'])
            
            except Exception as e:
                print(f"\n   ❌ 计划 {plan_index} 失败 (尝试 {attempt+1}/{MAX_RETRIES})")
                print(f"      错误: {e}")
                
                if attempt < MAX_RETRIES - 1:
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
    print(f"   并发数: {args.concurrent}")
    print("="*60)
    
    # 发送开始通知
    await send_notification(
        "批量处理开始",
        f"📊 开始处理 {len(plans)} 条计划\n并发数: {args.concurrent}"
    )
    
    async with async_playwright() as p:
        # 添加启动参数禁用权限提示
        browser = await p.chromium.launch(
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
        
        # 登录（只需一次）
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
                print(f"   等待中... ({i+1}/60)")
            
            if not logged_in:
                print("   ❌ 登录超时")
                sys.exit(1)
        else:
            print("   ✅ 已登录")
        
        await login_page.close()
        
        # 并发处理
        semaphore = asyncio.Semaphore(args.concurrent)
        tasks = []
        
        for i in range(len(plans)):
            task = process_single_plan(browser, plans[i], i + 1, semaphore)
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
        
        print("\n⏸️  浏览器保持打开  按 Ctrl+C 退出...")
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
