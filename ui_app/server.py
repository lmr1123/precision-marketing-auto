import asyncio
import csv
import json
import getpass
import io
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

try:
    from openpyxl import Workbook, load_workbook
except Exception:
    Workbook = None
    load_workbook = None


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "precision-auto-playwright-batch.py"
UPLOAD_DIR = ROOT / "ui_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DATA_CSV = ROOT / "data" / "plans.csv"


HEADER_EN_TO_CN: Dict[str, str] = {
    "name": "计划名称",
    "region": "计划区域",
    "theme": "营销主题",
    "scene_type": "场景类型",
    "plan_type": "计划类型",
    "push_content": "推送内容",
    "start_time": "计划开始时间",
    "end_time": "计划结束时间",
    "trigger_type": "触发方式",
    "send_time": "发送时间",
    "global_limit": "全局触达限制",
    "create_url": "创建链接",
    "group_name": "分群名称",
    "main_operating_area": "主消费营运区",
    "main_store_file_path": "主消费门店文件路径",
    "step2_store_file_path": "第2步门店信息文件路径",
    "step2_product_file_path": "第2步商品编码文件路径",
    "coupon_ids": "券规则ID",
    "coupon_ids_sheet_ref": "已领或已使用券规则ID",
    "purchase_target_product_code": "购买目标商品编码",
    "sms_content": "短信内容",
    "step3_end_time": "员工任务结束时间",
    "distribution_mode": "社群任务分配方式",
    "executor_employees": "执行员工",
    "send_content": "发送内容",
    "group_send_name": "下发群名",
    "channels": "发送渠道",
    "moments_add_images": "朋友圈是否上传图片",
    "moments_image_paths": "朋友圈图片路径(用|分隔)",
    "upload_stores": "是否上传门店",
    "store_file_path": "门店文件路径",
    "msg_add_mini_program": "会员通消息是否添加小程序",
    "msg_mini_program_name": "1对1-小程序名称",
    "msg_mini_program_title": "1对1-小程序标题",
    "msg_mini_program_cover_path": "小程序封面路径",
    "msg_mini_program_page_path": "1对1-小程序链接",
}
HEADER_CN_TO_EN: Dict[str, str] = {v: k for k, v in HEADER_EN_TO_CN.items()}
HEADER_CN_TO_EN.update({
    "第3步结束时间": "step3_end_time",
    "分配方式": "distribution_mode",
    "发送内容": "send_content",
    "短信内容": "sms_content",
    "主消费运营区": "main_operating_area",
})

CHANNEL_CODE_TO_NAME: Dict[str, str] = {
    "1": "短信",
    "2": "会员通-发客户消息",
    "3": "会员通-发客户朋友圈",
    "4": "会员通-发送社群",
}
CHANNEL_ALIAS_TO_NAME: Dict[str, str] = {
    "短信": "短信",
    "会员通-发客户消息": "会员通-发客户消息",
    "会员通发客户消息": "会员通-发客户消息",
    "会员通-发客户朋友圈": "会员通-发客户朋友圈",
    "会员通客户朋友圈": "会员通-发客户朋友圈",
    "会员通发客户朋友圈": "会员通-发客户朋友圈",
    "会员通-发送社群": "会员通-发送社群",
    "会员通发送社群": "会员通-发送社群",
}
TEMPLATE_HIDE_FIELDS = {
    "group_name",
    "moments_add_images",
    "moments_image_paths",
    "upload_stores",
    "store_file_path",
    "main_store_file_path",
    "step2_store_file_path",
    "step2_product_file_path",
    "msg_add_mini_program",
    "msg_mini_program_cover_path",
    "coupon_ids",
    "use_recommend",
    "set_target",
    "update_type",
    "sms_content",
    "send_content",
    "group_name",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_int(val: str, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


def _default_headers() -> List[str]:
    return [
        "name",
        "region",
        "theme",
        "scene_type",
        "plan_type",
        "push_content",
        "start_time",
        "end_time",
        "trigger_type",
        "send_time",
        "global_limit",
        "create_url",
        "main_operating_area",
        "main_store_file_path",
        "step2_store_file_path",
        "step2_product_file_path",
        "purchase_target_product_code",
        "coupon_ids",
        "coupon_ids_sheet_ref",
        "sms_content",
        "step3_end_time",
        "distribution_mode",
        "executor_employees",
        "group_send_name",
        "send_content",
        "channels",
        "moments_add_images",
        "moments_image_paths",
        "upload_stores",
        "store_file_path",
        "msg_add_mini_program",
        "msg_mini_program_name",
        "msg_mini_program_title",
        "msg_mini_program_cover_path",
        "msg_mini_program_page_path",
    ]


def load_template_headers_and_sample() -> tuple[List[str], List[str]]:
    # 模板字段固定使用系统标准字段，避免受本地旧CSV表头污染（导致下载模板出现英文/脏字段）
    headers = _default_headers()
    sample_map: Dict[str, str] = {}
    if DEFAULT_DATA_CSV.exists():
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with DEFAULT_DATA_CSV.open("r", encoding=enc, newline="") as f:
                    rows = list(csv.reader(f))
                if not rows:
                    continue
                raw_headers = [str(x or "").strip() for x in rows[0]]
                raw_sample = [str(x or "").strip() for x in (rows[1] if len(rows) > 1 else [""] * len(raw_headers))]
                norm_headers = [HEADER_CN_TO_EN.get(h, h) for h in raw_headers]
                sample_map = {
                    h: (raw_sample[idx] if idx < len(raw_sample) else "")
                    for idx, h in enumerate(norm_headers)
                }
                break
            except Exception:
                continue
    sample = [sample_map.get(h, "") for h in headers]
    return headers, sample


def _filter_template_fields(headers: List[str], sample: List[str]) -> tuple[List[str], List[str]]:
    keep = [idx for idx, h in enumerate(headers) if h not in TEMPLATE_HIDE_FIELDS]
    out_headers = [headers[idx] for idx in keep]
    out_sample = [sample[idx] if idx < len(sample) else "" for idx in keep]
    # 业务引导示例：第1步营销主题支持多选填写
    if "theme" in out_headers:
        idx = out_headers.index("theme")
        out_sample[idx] = "其他、26年3月积分换券"
    if "channels" in out_headers:
        idx = out_headers.index("channels")
        out_sample[idx] = "短信、会员通-发客户消息"
    if "create_url" in out_headers:
        idx = out_headers.index("create_url")
        out_sample[idx] = "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=600035736992907264"
    if "push_content" in out_headers:
        idx = out_headers.index("push_content")
        out_sample[idx] = "示例推送内容（按发送渠道自动映射到短信内容或发送内容）"
    # 业务引导示例：第2步主消费营运区支持多区域填写
    if "main_operating_area" in out_headers:
        idx = out_headers.index("main_operating_area")
        out_sample[idx] = "辽宁省区、九江、南昌、广州二"
    if "executor_employees" in out_headers:
        idx = out_headers.index("executor_employees")
        out_sample[idx] = "《目标门店 1》"
    if "purchase_target_product_code" in out_headers:
        idx = out_headers.index("purchase_target_product_code")
        out_sample[idx] = "《目标商品 1》"
    if "coupon_ids_sheet_ref" in out_headers:
        idx = out_headers.index("coupon_ids_sheet_ref")
        out_sample[idx] = "《券规则 ID 1》"
    return out_headers, out_sample


def write_template_csv(path: Path) -> None:
    headers, sample = load_template_headers_and_sample()
    headers, sample = _filter_template_fields(headers, sample)
    cn_headers = [HEADER_EN_TO_CN.get(h, h) for h in headers]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cn_headers)
        writer.writerow(sample)


def write_template_xlsx(path: Path) -> None:
    if Workbook is None:
        raise RuntimeError("openpyxl is not installed")
    headers, sample = load_template_headers_and_sample()
    headers, sample = _filter_template_fields(headers, sample)
    cn_headers = [HEADER_EN_TO_CN.get(h, h) for h in headers]
    wb = Workbook()
    ws = wb.active
    ws.title = "任务文件"
    ws.append(cn_headers)
    ws.append(sample)
    # 业务示例：用于给非技术同事直接参考填写（不参与程序逻辑判断）
    ws_example = wb.create_sheet("任务文件（示例）")
    ws_example.append(cn_headers)
    ws_example.append([
        "测试1-社群", "营运区", "其他、会员生日礼", "会员营销", "会员权益",
        "测试1-社群", "2026-03-16 08:00:00", "2026-03-30 08:00:00",
        "定时-单次任务", "2026-03-28 08:00:00", "限制",
        "https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=add",
        "辽宁省区、九江、南昌、广州二", "《目标商品 1》", "",
        "2026-03-30 08:00:00", "导入门店", "《目标门店1》", "福利",
        "会员通-发送社群", "大参林健康", "测试1-卡片",
        "apps/member/integralMall/pages/home/index",
    ])
    ws_example.append([
        "测试2-企微1对1", "省区", "其他、26年3月积分换券", "", "",
        "测试2-企微1对1", "2026-03-16 08:00:00", "2026-03-30 08:00:00",
        "定时-单次任务", "2026-03-28 08:00:00", "限制",
        "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=594094287227023360",
        "《目标门店1》", "", "《券规则ID1》",
        "2026-03-30 08:00:00", "", "西北大区、湖北省区", "",
        "会员通-发客户消息", "大参林健康", "测试1-卡片",
        "apps/member/integralMall/pages/home/index",
    ])
    ws_example.append([
        "测试3-朋友圈", "省区", "其他、26年3月积分换券", "", "",
        "测试3-朋友圈", "2026-03-16 08:00:00", "2026-03-30 08:00:00",
        "定时-单次任务", "2026-03-28 08:00:00", "限制",
        "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=599702926159527936",
        "华南大区", "", "《券规则ID1》",
        "2026-03-30 08:00:00", "", "黑龙江省区、武汉营运区", "",
        "会员通-发客户朋友圈", "", "", "",
    ])
    ws_example.append([
        "测试4-短信", "省区", "其他、26年3月积分换券", "", "",
        "测试4-短信", "2026-03-16 08:00:00", "2026-03-30 08:00:00",
        "定时-单次任务", "2026-03-28 08:00:00", "限制",
        "https://precision.dslyy.com/admin#/marketingTemplate/use?useId=599702746907561984",
        "来宾、华中大区", "《目标商品 1》", "《券规则ID1》",
        "", "", "", "", "短信", "", "", "",
    ])
    ws_store_1 = wb.create_sheet("目标门店 1")
    ws_store_1.append(["门店编码"])
    ws_store_1.append(["1001010022"])
    ws_store_1.append(["1001010026"])
    ws_product_1 = wb.create_sheet("目标商品 1")
    ws_product_1.append(["商品编码"])
    ws_product_1.append(["1010002"])
    ws_product_1.append(["1012058"])
    ws_coupon = wb.create_sheet("券规则 ID 1")
    ws_coupon.append(["券规则ID"])
    ws_coupon.append(["1-20000005313"])
    ws_coupon.append(["1-20000005475"])
    wb.save(path)
    wb.close()


def write_community_template_xlsx(path: Path) -> None:
    """社群专用模板：单Excel多sheet（任务文件/目标门店），仅保留社群最小必填字段。"""
    if Workbook is None:
        raise RuntimeError("openpyxl is not installed")
    wb = Workbook()
    ws = wb.active
    ws.title = "任务文件"
    headers = [
        "计划名称", "计划区域", "营销主题", "场景类型", "计划类型",
        "计划开始时间", "计划结束时间", "发送时间", "第3步结束时间",
        "分配方式", "执行员工", "下发群名", "发送内容", "发送渠道", "创建链接",
        "1对1-小程序名称", "1对1-小程序标题", "1对1-小程序链接",
    ]
    ws.append(headers)
    ws.append([
        "专属社群测试模板（自动化）", "营运区", "其他、会员生日礼", "会员营销", "会员权益",
        "2026-03-20 00:00:00", "2026-03-31 23:59:59", "2026-03-22 08:00:00",
        "2026-03-31 23:59:59", "按条件筛选客户群", "黑龙江省区、武汉营运区", "福利", "社群自动化测试内容",
        "会员通-发送社群", "https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=add",
        "大参林健康", "社群小程序示例", "pages/index/index",
    ])
    ws_store = wb.create_sheet("目标门店 1")
    ws_store.append(["门店编码"])
    ws_store.append(["2000081179"])
    ws_product = wb.create_sheet("目标商品 1")
    ws_product.append(["商品编码"])
    ws_product.append(["1012058"])
    wb.save(path)
    wb.close()


def normalize_uploaded_csv_headers(dst_csv: Path) -> None:
    """将上传文件中的中文表头标准化为脚本内部英文表头。"""
    try:
        with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            return
        raw_headers = [str(x or "").strip() for x in rows[0]]
        normalized: List[str] = []
        for h in raw_headers:
            if h == "第3步渠道(可多选)":
                normalized.append("channels")
            else:
                normalized.append(HEADER_CN_TO_EN.get(h, h))
        if normalized == raw_headers:
            return
        rows[0] = normalized
        with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    except Exception:
        # 不阻断上传；后续由脚本校验字段
        return


def _normalize_channel_text(raw: str) -> str:
    parts = [p.strip() for p in re.split(r"[|,，、/]+", str(raw or "")) if p.strip()]
    out: List[str] = []
    for p in parts:
        v = CHANNEL_CODE_TO_NAME.get(p) or CHANNEL_ALIAS_TO_NAME.get(p) or p
        if v not in out:
            out.append(v)
    return "、".join(out)


def normalize_channels_in_csv(dst_csv: Path) -> None:
    """支持文件中发送渠道填写序号（1/2/3/4），统一标准化为中文渠道名称。"""
    try:
        with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = list(reader.fieldnames or [])
        if not headers or "channels" not in headers:
            return
        changed = False
        for row in rows:
            old = str(row.get("channels", "") or "")
            new = _normalize_channel_text(old)
            if new and new != old:
                row["channels"] = new
                changed = True
        if not changed:
            return
        with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in headers})
    except Exception:
        return


def _norm_sheet_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).strip().lower()


def _extract_book_title_ref(raw: str) -> str:
    m = re.search(r"《\s*([^》]+?)\s*》", str(raw or ""))
    return (m.group(1).strip() if m else "")


def _collect_sheet_first_col_values(values: List[List[str]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for i, row in enumerate(values):
        if not row:
            continue
        first = str(row[0] or "").strip()
        if not first:
            continue
        if i == 0 and ("券规则" in first or "id" in first.lower()):
            continue
        if first not in out:
            out.append(first)
    return out


def apply_unified_field_mapping_and_refs(
    dst_csv: Path,
    task_id: str,
    step3_channels: str,
    sheet_assets: Dict[str, dict],
) -> None:
    """
    统一模板字段映射与书名号sheet引用处理：
    - 推送内容 -> 按发送渠道映射到 sms_content / send_content
    - 执行员工《目标门店X》 -> 自动映射 store_file_path + upload_stores=是
    - 购买目标商品编码《目标商品X》 -> step2_product_file_path
    - 已领或已使用券规则ID《券规则IDX》 -> coupon_ids（用/拼接）
    - 创建链接规则：社群空值自动补默认；非社群空值报错阻断
    """
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return

    for col in (
        "sms_content",
        "send_content",
        "upload_stores",
        "store_file_path",
        "main_store_file_path",
        "step2_store_file_path",
        "step2_product_file_path",
        "coupon_ids",
        "channels",
        "create_url",
        "msg_add_mini_program",
        "msg_mini_program_cover_path",
    ):
        if col not in headers:
            headers.append(col)

    ui_channels = _normalize_channel_text(step3_channels or "")
    community_default = "https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=add"

    def _pick_default_mini_cover() -> str:
        patterns = ("cover_*.JPG", "cover_*.jpg", "cover_*.jpeg", "cover_*.png")
        files: List[Path] = []
        for pat in patterns:
            files.extend(UPLOAD_DIR.glob(f"*_mini_program/{pat}"))
        if not files:
            return ""
        files = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
        return str(files[0].resolve())

    def _save_sheet_blob_for_store(sheet_title: str, row_no: int) -> str:
        asset = sheet_assets.get(_norm_sheet_name(sheet_title))
        if not asset:
            raise HTTPException(status_code=400, detail=f"第{row_no}行：未找到sheet《{sheet_title}》")
        return save_uploaded_store_file(f"{task_id}_r{row_no}", (asset["filename"], asset["bytes"]))

    def _save_sheet_blob_for_step2_product(sheet_title: str, row_no: int) -> str:
        asset = sheet_assets.get(_norm_sheet_name(sheet_title))
        if not asset:
            raise HTTPException(status_code=400, detail=f"第{row_no}行：未找到sheet《{sheet_title}》")
        return save_uploaded_main_store_file(f"{task_id}_r{row_no}", (asset["filename"], asset["bytes"]))

    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        # 跳过 Excel 末尾空行（避免误报“发送渠道不能为空”）
        if not any(str(v or "").strip() for v in row.values()):
            continue
        normalized_rows.append(row)

    for idx, row in enumerate(normalized_rows, 1):
        row_channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
        channel_scope = row_channels or ui_channels
        parts = [p.strip() for p in re.split(r"[|,，、/]+", channel_scope) if p.strip()]
        is_community = "会员通-发送社群" in parts

        # 发送渠道严格校验
        if not parts:
            raise HTTPException(status_code=400, detail=f"第{idx}行：发送渠道不能为空")

        # 创建链接规则：社群可默认；其他渠道必须填写
        create_url = str(row.get("create_url", "") or "").strip()
        has_non_community = any(p != "会员通-发送社群" for p in parts)
        if has_non_community and (not create_url):
            raise HTTPException(status_code=400, detail=f"第{idx}行：非社群渠道必须填写“创建链接”")
        if is_community and (not create_url):
            row["create_url"] = community_default

        # 推送内容路由
        push_content = str(row.get("push_content", "") or "").strip()
        if push_content:
            if "短信" in parts:
                row["sms_content"] = push_content
            if any(p in {"会员通-发客户消息", "会员通-发客户朋友圈", "会员通-发送社群"} for p in parts):
                row["send_content"] = push_content

        # 主消费营运区书名号引用 -> 第2步门店信息sheet（兼容用户把《目标门店X》写在该字段）
        main_area_ref = _extract_book_title_ref(row.get("main_operating_area", ""))
        if main_area_ref:
            step2_store_path = _save_sheet_blob_for_store(main_area_ref, idx)
            row["main_store_file_path"] = step2_store_path
            row["step2_store_file_path"] = step2_store_path
            # 书名号引用场景下不再走“主消费营运区树节点选择”
            row["main_operating_area"] = ""

        # 执行员工书名号引用 -> 目标门店sheet（第3步上传门店）
        emp_ref = _extract_book_title_ref(row.get("executor_employees", ""))
        if emp_ref:
            store_path = _save_sheet_blob_for_store(emp_ref, idx)
            row["upload_stores"] = "是"
            row["store_file_path"] = store_path
            # 会员通消息/朋友圈渠道下，执行员工仍为必填：用主消费营运区做兜底，避免仅书名号导致执行员工为空
            if any(p in {"会员通-发客户消息", "会员通-发客户朋友圈"} for p in parts):
                fallback_exec = str(row.get("main_operating_area", "") or "").strip()
                if fallback_exec:
                    row["executor_employees"] = fallback_exec

        # 购买目标商品编码书名号引用 -> 商品编码上传sheet
        product_ref = _extract_book_title_ref(row.get("purchase_target_product_code", ""))
        if product_ref:
            row["step2_product_file_path"] = _save_sheet_blob_for_step2_product(product_ref, idx)

        # 已领或已使用券规则ID书名号引用 -> 券规则ID文本（/拼接）
        coupon_ref = _extract_book_title_ref(row.get("coupon_ids_sheet_ref", ""))
        if coupon_ref:
            asset = sheet_assets.get(_norm_sheet_name(coupon_ref))
            if not asset:
                raise HTTPException(status_code=400, detail=f"第{idx}行：未找到sheet《{coupon_ref}》")
            values = _collect_sheet_first_col_values(asset.get("rows", []))
            if not values:
                raise HTTPException(status_code=400, detail=f"第{idx}行：sheet《{coupon_ref}》未找到有效券规则ID")
            row["coupon_ids"] = "/".join(values)

        # 小程序自动判定：有名称/标题/链接任一字段，自动开启添加小程序；
        # 若封面路径缺失，则自动复用最近一次已上传的封面图用于测试验证。
        mp_name = str(row.get("msg_mini_program_name", "") or "").strip()
        mp_title = str(row.get("msg_mini_program_title", "") or "").strip()
        mp_link = str(row.get("msg_mini_program_page_path", "") or "").strip()
        if mp_name or mp_title or mp_link:
            row["msg_add_mini_program"] = "是"
            if not str(row.get("msg_mini_program_cover_path", "") or "").strip():
                default_cover = _pick_default_mini_cover()
                if default_cover:
                    row["msg_mini_program_cover_path"] = default_cover

    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in normalized_rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def convert_uploaded_xlsx_to_csv(upload: UploadFile, dst_csv: Path) -> None:
    if load_workbook is None:
        raise HTTPException(status_code=500, detail="Server missing openpyxl. Please install requirements-ui.txt")
    upload.file.seek(0)
    wb = load_workbook(upload.file, read_only=True, data_only=True)
    ws = wb.active
    with dst_csv.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if v is None else str(v) for v in row])
    wb.close()


def _pick_sheet_name(sheet_names: List[str], candidates: List[str], fallback_keywords: List[str]) -> Optional[str]:
    """按候选名/关键字匹配sheet名称（忽略空格和大小写）。"""
    norm = {re.sub(r"\s+", "", n).lower(): n for n in sheet_names}
    for c in candidates:
        key = re.sub(r"\s+", "", c).lower()
        if key in norm:
            return norm[key]
    for name in sheet_names:
        n = re.sub(r"\s+", "", name).lower()
        if any(k in n for k in fallback_keywords):
            return name
    return None


def _write_sheet_to_csv(ws, dst_csv: Path) -> None:
    with dst_csv.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if v is None else str(v) for v in row])


def _sheet_to_xlsx_blob(ws_title: str, ws) -> Tuple[str, bytes]:
    if Workbook is None:
        raise HTTPException(status_code=500, detail="Server missing openpyxl. Please install requirements-ui.txt")
    out_wb = Workbook()
    out_ws = out_wb.active
    out_ws.title = ws_title[:31] if ws_title else "Sheet1"
    for row in ws.iter_rows(values_only=True):
        out_ws.append(list(row))
    bio = io.BytesIO()
    out_wb.save(bio)
    out_wb.close()
    return f"{ws_title or 'sheet'}.xlsx", bio.getvalue()


def convert_uploaded_xlsx_multi_sheet_from_bytes(
    xlsx_bytes: bytes, dst_csv: Path
) -> Tuple[Optional[Tuple[str, bytes]], Optional[Tuple[str, bytes]], Dict[str, dict]]:
    """
    一个Excel多sheet模式：
    - 任务文件sheet -> 转CSV
    - 目标门店sheet -> 返回xlsx blob
    - 目标商品sheet -> 返回xlsx blob
    """
    if load_workbook is None:
        raise HTTPException(status_code=500, detail="Server missing openpyxl. Please install requirements-ui.txt")
    wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    names = list(wb.sheetnames)

    task_sheet = _pick_sheet_name(
        names,
        candidates=["任务文件", "任务", "plans", "plan", "计划"],
        fallback_keywords=["任务", "plan", "plans", "计划"],
    ) or (names[0] if names else None)
    if not task_sheet:
        wb.close()
        raise HTTPException(status_code=400, detail=f"Excel未找到可用sheet: {upload.filename}")
    _write_sheet_to_csv(wb[task_sheet], dst_csv)

    store_sheet = _pick_sheet_name(
        names,
        candidates=["目标门店", "门店", "主消费门店", "step2_main_store"],
        fallback_keywords=["目标门店", "门店"],
    )
    product_sheet = _pick_sheet_name(
        names,
        candidates=["目标商品", "商品编码", "商品", "step2_product"],
        fallback_keywords=["目标商品", "商品编码", "商品"],
    )

    store_blob: Optional[Tuple[str, bytes]] = None
    product_blob: Optional[Tuple[str, bytes]] = None
    sheet_assets: Dict[str, dict] = {}
    if store_sheet:
        store_blob = _sheet_to_xlsx_blob(store_sheet, wb[store_sheet])
    if product_sheet:
        product_blob = _sheet_to_xlsx_blob(product_sheet, wb[product_sheet])
    for n in names:
        ws = wb[n]
        blob_name, blob_bytes = _sheet_to_xlsx_blob(n, ws)
        rows = [["" if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)]
        sheet_assets[_norm_sheet_name(n)] = {
            "title": n,
            "filename": blob_name,
            "bytes": blob_bytes,
            "rows": rows,
        }
    wb.close()
    return store_blob, product_blob, sheet_assets

def _is_valid_jpeg_png_bytes(data: bytes) -> bool:
    """校验图片真实格式（避免仅后缀正确但内容非法/加密）。"""
    if not data or len(data) < 16:
        return False
    # JPEG: starts with SOI(FFD8), and contains EOI(FFD9) later.
    # 不强制 EOI 在最后两个字节，避免被尾部扩展数据误伤。
    if data.startswith(b"\xff\xd8") and (b"\xff\xd9" in data[2:]):
        return True
    # PNG: signature + tail has IEND
    if data.startswith(b"\x89PNG\r\n\x1a\n") and (b"IEND" in data[-128:]):
        return True
    return False


def save_uploaded_moments_images(task_id: str, images: List[tuple[str, bytes]]) -> List[str]:
    """保存UI上传的朋友圈图片，返回本地绝对路径（按上传顺序）。"""
    if not images:
        return []
    out_dir = UPLOAD_DIR / f"{task_id}_images"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[str] = []
    for idx, (name, data) in enumerate(images, 1):
        ext = Path(name).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            raise HTTPException(status_code=400, detail=f"朋友圈图片格式仅支持 jpg/png: {name}")
        if len(data) >= 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"朋友圈图片需小于10MB: {name}")
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).name)
        dst = out_dir / f"{idx:02d}_{safe}"
        with dst.open("wb") as f:
            f.write(data)
        out_paths.append(str(dst.resolve()))
    if len(out_paths) > 9:
        raise HTTPException(status_code=400, detail=f"朋友圈图片最多9张，当前{len(out_paths)}张")
    return out_paths


def save_uploaded_mini_program_cover(task_id: str, image: tuple[str, bytes]) -> str:
    """保存UI上传的小程序封面，返回本地绝对路径。"""
    name, data = image
    out_dir = UPLOAD_DIR / f"{task_id}_mini_program"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail=f"小程序封面格式仅支持 jpg/png: {name}")
    if len(data) >= 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"小程序封面需小于10MB: {name}")
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).name)
    dst = out_dir / f"cover_{safe}"
    with dst.open("wb") as f:
        f.write(data)
    return str(dst.resolve())


def save_uploaded_store_file(task_id: str, store_file: tuple[str, bytes]) -> str:
    """保存UI上传的门店文件，返回本地绝对路径。"""
    name, data = store_file
    out_dir = UPLOAD_DIR / f"{task_id}_store_file"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail=f"门店文件格式仅支持 xlsx/xls: {name}")
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).name)
    dst = out_dir / f"store_{safe}"
    with dst.open("wb") as f:
        f.write(data)
    return str(dst.resolve())


def save_uploaded_main_store_file(task_id: str, store_file: tuple[str, bytes]) -> str:
    """保存第2步主消费门店上传文件，返回本地绝对路径。"""
    name, data = store_file
    out_dir = UPLOAD_DIR / f"{task_id}_step2_main_store"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(name).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail=f"主消费门店文件格式仅支持 xlsx/xls: {name}")
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).name)
    dst = out_dir / f"step2_main_store_{safe}"
    with dst.open("wb") as f:
        f.write(data)
    return str(dst.resolve())


def inject_moments_images_to_csv(dst_csv: Path, image_paths: List[str], step3_channels: str) -> None:
    """将上传图片信息回写到任务CSV（覆盖朋友圈场景行）。"""
    if not image_paths:
        return
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return

    for col in ("moments_add_images", "moments_image_paths", "channels"):
        if col not in headers:
            headers.append(col)

    ui_channels = _normalize_channel_text(step3_channels or "")
    for row in rows:
        row_channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
        channel_scope = row_channels or ui_channels
        if ("会员通-发客户朋友圈" not in channel_scope) and ("会员通-发送社群" not in channel_scope):
            continue
        row["moments_add_images"] = "是"
        row["moments_image_paths"] = "|".join(image_paths)

    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def inject_message_mini_program_to_csv(
    dst_csv: Path,
    step3_channels: str,
    enabled: bool,
    program_name: str,
    title: str,
    cover_path: str,
    page_path: str,
) -> None:
    """将会员通消息类渠道（发客户消息/发送社群）的小程序配置回写到任务CSV。"""
    if not enabled:
        return
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return

    for col in (
        "msg_add_mini_program",
        "msg_mini_program_name",
        "msg_mini_program_title",
        "msg_mini_program_cover_path",
        "msg_mini_program_page_path",
        "channels",
    ):
        if col not in headers:
            headers.append(col)

    ui_channels = _normalize_channel_text(step3_channels or "")
    for row in rows:
        row_channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
        channel_scope = row_channels or ui_channels
        if ("会员通-发客户消息" not in channel_scope) and ("会员通-发送社群" not in channel_scope):
            continue
        row["msg_add_mini_program"] = "是"
        row["msg_mini_program_name"] = program_name or row.get("msg_mini_program_name", "") or "大参林健康"
        row["msg_mini_program_title"] = title or row.get("msg_mini_program_title", "") or ""
        row["msg_mini_program_cover_path"] = cover_path or ""
        row["msg_mini_program_page_path"] = page_path or row.get("msg_mini_program_page_path", "") or ""

    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def inject_store_file_to_csv(
    dst_csv: Path,
    step3_channels: str,
    enabled: bool,
    store_file_path: str,
) -> None:
    """将上传门店配置回写到任务CSV（会员通消息/朋友圈渠道）。"""
    if not enabled:
        return
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return

    for col in ("upload_stores", "store_file_path", "channels"):
        if col not in headers:
            headers.append(col)

    ui_channels = _normalize_channel_text(step3_channels or "")
    for row in rows:
        row_channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
        channel_scope = row_channels or ui_channels
        if ("会员通-发客户消息" not in channel_scope) and ("会员通-发送社群" not in channel_scope) and ("会员通-发客户朋友圈" not in channel_scope):
            continue
        row["upload_stores"] = "是"
        row["store_file_path"] = store_file_path or ""

    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def inject_step2_main_store_file_to_csv(
    dst_csv: Path,
    main_store_file_path: str,
) -> None:
    """将第2步主消费门店上传文件路径注入任务CSV。"""
    if not main_store_file_path:
        return
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return
    if "main_store_file_path" not in headers:
        headers.append("main_store_file_path")
    if "step2_store_file_path" not in headers:
        headers.append("step2_store_file_path")
    for row in rows:
        row["main_store_file_path"] = main_store_file_path
        row["step2_store_file_path"] = main_store_file_path
    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def inject_step2_product_file_to_csv(
    dst_csv: Path,
    product_file_path: str,
) -> None:
    """将第2步商品编码上传文件路径注入任务CSV。"""
    if not product_file_path:
        return
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return
    if "step2_product_file_path" not in headers:
        headers.append("step2_product_file_path")
    for row in rows:
        row["step2_product_file_path"] = product_file_path
    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


def normalize_community_create_url_in_csv(dst_csv: Path, step3_channels: str) -> None:
    """
    社群任务创建链接标准化：
    - 若命中社群渠道且 create_url 为空 -> 填充 checkType=add 默认链接
    - 若命中社群渠道且 create_url 为旧 edit 链接 -> 转为 checkType=add
    """
    with dst_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return
    if "create_url" not in headers:
        headers.append("create_url")
    if "channels" not in headers:
        headers.append("channels")

    default_add_url = "https://precision.dslyy.com/admin#/marketingPlan/addcommunityPlan?checkType=add"
    changed = False
    ui_channels = _normalize_channel_text(step3_channels or "")
    for row in rows:
        # 空白行不做任何默认链接注入，避免被误拆分为额外任务
        row_has_real_data = any(
            str(v or "").strip()
            for k, v in row.items()
            if k not in {"create_url"}
        )
        if not row_has_real_data:
            continue
        row_channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
        channel_scope = row_channels or ui_channels
        if "会员通-发送社群" not in channel_scope:
            continue
        old_url = str(row.get("create_url", "") or "").strip()
        new_url = old_url
        if not old_url:
            new_url = default_add_url
        elif "addcommunityPlan" in old_url and "checkType=edit" in old_url:
            new_url = re.sub(r"checkType=edit", "checkType=add", old_url)
        elif "addcommunityPlan" in old_url and "checkType=add" not in old_url:
            if "?" in old_url:
                new_url = f"{old_url}&checkType=add"
            else:
                new_url = f"{old_url}?checkType=add"
        if new_url != old_url:
            row["create_url"] = new_url
            changed = True

    if not changed:
        return
    with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})


@dataclass
class TaskOptions:
    connect_cdp: bool = True
    cdp_endpoint: str = "http://127.0.0.1:18800"
    strict_step2: bool = True
    skip_step2: bool = False
    concurrent: int = 1
    start: Optional[int] = None
    end: Optional[int] = None
    hold_seconds: int = 2
    step3_channels: str = ""
    create_url: str = ""
    executor_include_franchise: bool = False


@dataclass
class Task:
    id: str
    filename: str
    file_path: str
    options: TaskOptions
    operator: str = ""
    created_at: str = field(default_factory=now_iso)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    status: str = "pending"
    total_plans: int = 0
    completed_plans: int = 0
    success_count: int = 0
    fail_count: int = 0
    eta: Optional[str] = None
    duration_sec: Optional[float] = None
    error: str = ""
    logs: List[str] = field(default_factory=list)
    generated_links: List[str] = field(default_factory=list)
    plan_name_display: str = ""
    channel_display: str = ""
    queued: bool = False
    paused: bool = False
    deleted: bool = False

    def _latest_link_for_ui(self) -> str:
        # 优先给业务展示真正可复核的 viewPlan 链接，其次 editPlan。
        for u in reversed(self.generated_links):
            if "#/marketingPlan/viewPlan?" in u:
                return u
        for u in reversed(self.generated_links):
            if "#/marketingPlan/editPlan?" in u:
                return u
        return self.generated_links[-1] if self.generated_links else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "file_path": self.file_path,
            "operator": self.operator,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "total_plans": self.total_plans,
            "completed_plans": self.completed_plans,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "eta": self.eta,
            "duration_sec": self.duration_sec,
            "error": self.error,
            "logs_count": len(self.logs),
            "generated_links": self.generated_links,
            "latest_link": self._latest_link_for_ui(),
            "plan_name": self.plan_name_display,
            "send_channels": self.channel_display,
            "queued": self.queued,
            "paused": self.paused,
            "options": {
                "connect_cdp": self.options.connect_cdp,
                "cdp_endpoint": self.options.cdp_endpoint,
                "strict_step2": self.options.strict_step2,
                "skip_step2": self.options.skip_step2,
                "concurrent": self.options.concurrent,
                "start": self.options.start,
                "end": self.options.end,
                "hold_seconds": self.options.hold_seconds,
                "step3_channels": self.options.step3_channels,
                "create_url": self.options.create_url,
                "executor_include_franchise": self.options.executor_include_franchise,
            },
        }


def summarize_csv_meta(csv_path: Path) -> tuple[str, str]:
    names: List[str] = []
    channels: List[str] = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                n = (row.get("name", "") or "").strip()
                c = _normalize_channel_text((row.get("channels", "") or "").strip())
                if n and n not in names:
                    names.append(n)
                if c:
                    for p in re.split(r"[|,，、/]+", c):
                        p = (p or "").strip()
                        if p and p not in channels:
                            channels.append(p)
                if i >= 30:
                    break
    except Exception:
        return "", ""
    if not names:
        plan_name = ""
    elif len(names) == 1:
        plan_name = names[0]
    else:
        plan_name = f"{names[0]} +{len(names)-1}"
    return plan_name, "、".join(channels)


def parse_task_plans(csv_path: Path) -> List[dict]:
    plans: List[dict] = []
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                name = str(row.get("name", "") or "").strip() or f"计划{idx+1}"
                channels = _normalize_channel_text(str(row.get("channels", "") or "").strip())
                plans.append(
                    {
                        "index": idx,
                        "name": name,
                        "channels": channels,
                        "msg_add_mini_program": str(row.get("msg_add_mini_program", "") or "").strip() in {"是", "true", "True", "1"},
                        "moments_add_images": str(row.get("moments_add_images", "") or "").strip() in {"是", "true", "True", "1"},
                        "msg_mini_program_cover_path": str(row.get("msg_mini_program_cover_path", "") or "").strip(),
                        "moments_image_paths": str(row.get("moments_image_paths", "") or "").strip(),
                    }
                )
    except Exception:
        return plans
    return plans


def split_csv_to_single_plan_files(src_csv: Path, stem: str) -> List[Path]:
    """将一个任务CSV按计划行拆分为多个单计划CSV文件。"""
    with src_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return [src_csv]

    def _row_has_plan_data(row: dict) -> bool:
        # 只把有业务内容的行视为计划，过滤 Excel 末尾空行/占位行
        keys = [
            "name",
            "channels",
            "region",
            "theme",
            "push_content",
            "send_time",
            "end_time",
        ]
        for k in keys:
            v = str(row.get(k, "") or "").strip()
            if v:
                return True
        # create_url / 文件路径等附属字段不单独作为“有效计划行”判定
        return False

    valid_rows = [r for r in rows if _row_has_plan_data(r)]
    if len(valid_rows) <= 1:
        return [src_csv]

    out_paths: List[Path] = []
    for i, row in enumerate(valid_rows, 1):
        tid = str(uuid.uuid4())
        out = UPLOAD_DIR / f"{tid}_{stem}_plan{i}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as fw:
            w = csv.DictWriter(fw, fieldnames=headers)
            w.writeheader()
            w.writerow({k: row.get(k, "") for k in headers})
        out_paths.append(out)
    return out_paths


def apply_task_materials_to_csv(csv_path: Path, specs: List[dict]) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])
    if not headers:
        return 0

    required = [
        "msg_add_mini_program",
        "msg_mini_program_name",
        "msg_mini_program_title",
        "msg_mini_program_cover_path",
        "msg_mini_program_page_path",
        "moments_add_images",
        "moments_image_paths",
    ]
    for col in required:
        if col not in headers:
            headers.append(col)

    touched = 0
    spec_map = {}
    for s in specs:
        try:
            spec_map[int(s.get("index"))] = s
        except Exception:
            continue

    for idx, row in enumerate(rows):
        s = spec_map.get(idx)
        if not s:
            continue
        touched += 1
        if "msg_add_mini_program" in s:
            row["msg_add_mini_program"] = "是" if bool(s.get("msg_add_mini_program")) else "否"
        if s.get("msg_mini_program_name") is not None:
            row["msg_mini_program_name"] = str(s.get("msg_mini_program_name") or "")
        if s.get("msg_mini_program_title") is not None:
            row["msg_mini_program_title"] = str(s.get("msg_mini_program_title") or "")
        if s.get("msg_mini_program_page_path") is not None:
            row["msg_mini_program_page_path"] = str(s.get("msg_mini_program_page_path") or "")
        if s.get("msg_mini_program_cover_path") is not None:
            row["msg_mini_program_cover_path"] = str(s.get("msg_mini_program_cover_path") or "")

        if "moments_add_images" in s:
            row["moments_add_images"] = "是" if bool(s.get("moments_add_images")) else "否"
        if s.get("moments_image_paths") is not None:
            row["moments_image_paths"] = str(s.get("moments_image_paths") or "")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in headers})
    return touched


def _parse_channel_list(raw: str) -> List[str]:
    return [p.strip() for p in re.split(r"[|,，、/]+", str(raw or "")) if p.strip()]


def _is_community_only_channels(raw: str) -> bool:
    ch = _parse_channel_list(raw)
    return bool(ch) and all(c == "会员通-发送社群" for c in ch)


class TaskRunner:
    def __init__(self, workers: int = 2):
        self.tasks: Dict[str, Task] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.workers = max(1, workers)
        self.worker_tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        if self.worker_tasks:
            return
        for i in range(self.workers):
            self.worker_tasks.append(asyncio.create_task(self._worker_loop(i + 1)))

    async def add_task(self, task: Task, auto_start: bool = True) -> None:
        async with self.lock:
            self.tasks[task.id] = task
        if auto_start:
            await self.enqueue_task(task.id)

    async def enqueue_task(self, task_id: str) -> bool:
        async with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.deleted or task.paused:
                return False
            if task.status != "pending":
                return False
            if task.queued:
                return False
            task.queued = True
        await self.queue.put(task_id)
        return True

    async def pause_task(self, task_id: str) -> Optional[Task]:
        async with self.lock:
            task = self.tasks.get(task_id)
            if not task or task.deleted:
                return None
            if task.status == "running":
                return task
            task.paused = True
            task.queued = False
            return task

    async def resume_task(self, task_id: str) -> Optional[Task]:
        async with self.lock:
            task = self.tasks.get(task_id)
            if not task or task.deleted:
                return None
            task.paused = False
            return task

    async def delete_task(self, task_id: str) -> bool:
        async with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status == "running":
                return False
            task.deleted = True
            task.queued = False
            return True

    async def batch_pause_tasks(self, ids: List[str]) -> dict:
        changed = 0
        ignored = 0
        for tid in ids:
            t = await self.pause_task(tid)
            if t is None:
                ignored += 1
            elif t.status == "running":
                ignored += 1
            else:
                changed += 1
        return {"changed": changed, "ignored": ignored}

    async def batch_delete_tasks(self, ids: List[str]) -> dict:
        changed = 0
        ignored = 0
        for tid in ids:
            ok = await self.delete_task(tid)
            if ok:
                changed += 1
            else:
                ignored += 1
        return {"changed": changed, "ignored": ignored}

    async def retry_task(self, task_id: str) -> Task:
        async with self.lock:
            old = self.tasks.get(task_id)
            if not old or old.deleted:
                raise HTTPException(status_code=404, detail="Task not found")
            new_id = str(uuid.uuid4())
            new_task = Task(
                id=new_id,
                filename=old.filename,
                file_path=old.file_path,
                options=old.options,
                operator=old.operator,
            )
            self.tasks[new_id] = new_task
        await self.enqueue_task(new_id)
        return new_task

    async def start_pending(self) -> List[str]:
        async with self.lock:
            ids = [
                tid
                for tid, t in self.tasks.items()
                if t.status == "pending" and not t.queued and not t.paused and not t.deleted
            ]
        started: List[str] = []
        for tid in ids:
            ok = await self.enqueue_task(tid)
            if ok:
                started.append(tid)
        return started

    async def start_task(self, task_id: str) -> bool:
        return await self.enqueue_task(task_id)

    async def retry_failed(self) -> List[str]:
        async with self.lock:
            failed_ids = [tid for tid, t in self.tasks.items() if t.status == "failed" and not t.deleted]
        new_ids = []
        for tid in failed_ids:
            t = await self.retry_task(tid)
            new_ids.append(t.id)
        return new_ids

    async def list_tasks(self) -> List[dict]:
        async with self.lock:
            tasks = [t for t in self.tasks.values() if not t.deleted]
        tasks.sort(key=lambda x: x.created_at, reverse=True)
        return [t.to_dict() for t in tasks]

    async def get_task(self, task_id: str) -> Task:
        async with self.lock:
            t = self.tasks.get(task_id)
        if not t or t.deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        return t

    async def append_log(self, task: Task, line: str) -> None:
        task.logs.append(line.rstrip("\n"))
        if len(task.logs) > 5000:
            task.logs = task.logs[-5000:]
        self._parse_progress(task, line)

    def _parse_progress(self, task: Task, line: str) -> None:
        m_total = re.search(r"计划数:\s*(\d+)", line)
        if m_total:
            task.total_plans = int(m_total.group(1))
        m_success = re.search(r"✅\s*成功:\s*(\d+)", line)
        if m_success:
            task.success_count = int(m_success.group(1))
        m_fail = re.search(r"❌\s*失败:\s*(\d+)", line)
        if m_fail:
            task.fail_count = int(m_fail.group(1))
        if "✅ 计划 " in line and " 完成！" in line:
            task.completed_plans += 1
        if "❌ 计划 " in line and " 失败 " in line:
            task.completed_plans += 1
        self._parse_generated_links(task, line)
        self._update_eta(task)

    def _parse_generated_links(self, task: Task, line: str) -> None:
        # Extract review links from runtime logs for business users.
        urls = re.findall(r"(https?://[^\s]+)", line)
        for u in urls:
            u = u.strip().rstrip(".,)")
            if "precision.dslyy.com" not in u:
                continue
            if (
                "#/marketingPlan/viewPlan?" in u
                or "#/marketingPlan/editPlan?" in u
                or "#/marketingTemplate/use?" in u
                or "useId=" in u
                or "#/marketingTemplate/" in u
            ):
                if u not in task.generated_links:
                    task.generated_links.append(u)
                    if len(task.generated_links) > 20:
                        task.generated_links = task.generated_links[-20:]

    def _update_eta(self, task: Task) -> None:
        if not task.started_at:
            return
        if task.total_plans <= 0 or task.completed_plans <= 0:
            task.eta = None
            return
        started = datetime.fromisoformat(task.started_at)
        elapsed = (datetime.now() - started).total_seconds()
        speed = task.completed_plans / max(elapsed, 1)
        remaining = max(task.total_plans - task.completed_plans, 0)
        eta = datetime.now() + timedelta(seconds=(remaining / max(speed, 1e-6)))
        task.eta = eta.isoformat(timespec="seconds")

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            task_id = await self.queue.get()
            try:
                async with self.lock:
                    task = self.tasks.get(task_id)
                if not task or task.deleted:
                    continue
                if task.paused or task.status != "pending":
                    task.queued = False
                    continue
                await self._run_task(task, worker_id)
            finally:
                self.queue.task_done()

    async def _run_task(self, task: Task, worker_id: int) -> None:
        task.status = "running"
        task.queued = False
        task.started_at = now_iso()
        task.error = ""
        task.logs = []
        await self.append_log(task, f"[worker-{worker_id}] task started: {task.filename}")

        # 双保险：worker侧再做一次社群自动策略兜底，避免上传侧策略未命中
        worker_community_only = _is_community_only_channels(task.options.step3_channels or task.channel_display)
        if worker_community_only:
            task.options.strict_step2 = False
            task.options.skip_step2 = True

        if task.options.skip_step2 and (not task.options.strict_step2):
            await self.append_log(task, "[worker-auto] 社群自动策略生效：已自动关闭严格第2步，并启用跳过第2步")

        cmd = [
            sys.executable,
            "-u",
            str(SCRIPT_PATH),
            "--csv",
            task.file_path,
            "--hold-seconds",
            str(task.options.hold_seconds),
        ]
        if task.options.connect_cdp:
            cmd.extend(["--connect-cdp", "--cdp-endpoint", task.options.cdp_endpoint])
        if task.options.strict_step2:
            cmd.append("--strict-step2")
        if task.options.skip_step2:
            cmd.append("--skip-step2")
        if task.options.concurrent:
            cmd.extend(["--concurrent", str(task.options.concurrent)])
        if task.options.start:
            cmd.extend(["--start", str(task.options.start)])
        if task.options.end:
            cmd.extend(["--end", str(task.options.end)])
        if task.options.step3_channels:
            cmd.extend(["--step3-channels", task.options.step3_channels])
        if task.options.create_url:
            cmd.extend(["--create-url", task.options.create_url])
        if task.options.executor_include_franchise:
            cmd.append("--executor-include-franchise")

        await self.append_log(task, f"$ {' '.join(cmd)}")
        started = datetime.now()
        child_env = os.environ.copy()
        # 避免在 nohup/后台启动场景中继承到无效标准流，导致 Python 子进程启动即崩溃
        child_env.setdefault("PYTHONUTF8", "1")
        child_env.setdefault("PYTHONIOENCODING", "utf-8")
        child_env.setdefault("PYTHONUNBUFFERED", "1")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ROOT),
            env=child_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="ignore")
            await self.append_log(task, line)
        rc = await proc.wait()

        task.ended_at = now_iso()
        task.duration_sec = (datetime.now() - started).total_seconds()
        if rc == 0 and task.fail_count == 0:
            task.status = "success"
        else:
            task.status = "failed"
            task.error = f"exit_code={rc}"
        await self.append_log(task, f"[worker-{worker_id}] task finished with status={task.status}")


app = FastAPI(title="Precision Marketing Automation UI")
runner = TaskRunner(workers=2)


@app.on_event("startup")
async def startup_event() -> None:
    await runner.start()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return UI_HTML


@app.get("/api/tasks")
async def list_tasks() -> JSONResponse:
    return JSONResponse({"tasks": await runner.list_tasks()})


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> JSONResponse:
    task = await runner.get_task(task_id)
    return JSONResponse(task.to_dict())


@app.get("/api/tasks/{task_id}/file")
async def download_task_file(task_id: str):
    task = await runner.get_task(task_id)
    p = Path(task.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Task file not found")
    return FileResponse(path=str(p), filename=p.name, media_type="text/csv")


@app.get("/api/tasks/{task_id}/plans")
async def get_task_plans(task_id: str) -> JSONResponse:
    task = await runner.get_task(task_id)
    p = Path(task.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Task file not found")
    plans = parse_task_plans(p)
    return JSONResponse({"task_id": task_id, "plans": plans})


@app.get("/api/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, offset: int = 0, limit: int = 300) -> JSONResponse:
    task = await runner.get_task(task_id)
    logs = task.logs[offset: offset + limit]
    return JSONResponse({
        "task_id": task_id,
        "offset": offset,
        "next_offset": offset + len(logs),
        "logs": logs,
        "status": task.status,
    })


@app.post("/api/tasks/{task_id}/materials")
async def save_task_materials(
    task_id: str,
    specs_json: str = Form(...),
    files: List[UploadFile] = File(default=[]),
) -> JSONResponse:
    task = await runner.get_task(task_id)
    csv_path = Path(task.file_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Task file not found")

    try:
        specs = json.loads(specs_json)
        if not isinstance(specs, list):
            raise ValueError("specs_json must be a list")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid specs_json: {e}")

    file_map: Dict[str, UploadFile] = {f.filename or "": f for f in files}
    out_dir = UPLOAD_DIR / f"{task_id}_plan_materials"
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in specs:
        idx = int(spec.get("index", -1))
        if idx < 0:
            continue
        plan_dir = out_dir / f"plan_{idx+1:03d}"
        plan_dir.mkdir(parents=True, exist_ok=True)

        cover_token = str(spec.get("cover_token", "") or "")
        if cover_token:
            uf = file_map.get(cover_token)
            if uf:
                b = await uf.read()
                if b:
                    cover_path = save_uploaded_mini_program_cover(f"{task_id}_p{idx+1}", (uf.filename or cover_token, b))
                    spec["msg_mini_program_cover_path"] = cover_path

        img_tokens = spec.get("moment_tokens", []) or []
        if img_tokens:
            img_blobs: List[Tuple[str, bytes]] = []
            for tok in img_tokens:
                tok = str(tok or "")
                uf = file_map.get(tok)
                if not uf:
                    continue
                b = await uf.read()
                if b:
                    img_blobs.append((uf.filename or tok, b))
            if img_blobs:
                img_paths = save_uploaded_moments_images(f"{task_id}_p{idx+1}", img_blobs)
                spec["moments_image_paths"] = "|".join(img_paths)

    touched = apply_task_materials_to_csv(csv_path, specs)
    return JSONResponse({"task_id": task_id, "updated_plans": touched})


@app.get("/api/template/csv")
async def download_template_csv():
    p = UPLOAD_DIR / "精准营销任务模板_防乱码.csv"
    write_template_csv(p)
    return FileResponse(path=str(p), filename="精准营销任务模板（CSV防乱码）.csv", media_type="text/csv")


@app.get("/api/template/xlsx")
async def download_template_xlsx():
    p = UPLOAD_DIR / "精准营销任务模板.xlsx"
    try:
        write_template_xlsx(p)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(
        path=str(p),
        filename="精准营销任务模板（统一模板）.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/template/community-xlsx")
async def download_community_template_xlsx():
    p = UPLOAD_DIR / "精准营销社群任务模板.xlsx"
    try:
        write_community_template_xlsx(p)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(
        path=str(p),
        filename="精准营销社群任务模板（含目标门店）.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/tasks/upload")
async def upload_tasks(
    files: List[UploadFile] = File(...),
    moments_images: List[UploadFile] = File(default=[]),
    mini_program_cover: Optional[UploadFile] = File(default=None),
    store_file: Optional[UploadFile] = File(default=None),
    step2_main_store_file: Optional[UploadFile] = File(default=None),
    step2_product_file: Optional[UploadFile] = File(default=None),
    connect_cdp: bool = Form(True),
    cdp_endpoint: str = Form("http://127.0.0.1:18800"),
    strict_step2: bool = Form(True),
    skip_step2: bool = Form(False),
    concurrent: int = Form(1),
    start: str = Form(""),
    end: str = Form(""),
    hold_seconds: int = Form(2),
    step3_channels: str = Form(""),
    create_url: str = Form(""),
    executor_include_franchise: bool = Form(False),
    moments_add_images: bool = Form(False),
    upload_stores: bool = Form(False),
    msg_add_mini_program: bool = Form(False),
    msg_mini_program_name: str = Form("大参林健康"),
    msg_mini_program_title: str = Form(""),
    msg_mini_program_page_path: str = Form(""),
    operator: str = Form(""),
) -> JSONResponse:
    created = []
    options = TaskOptions(
        connect_cdp=connect_cdp,
        cdp_endpoint=cdp_endpoint.strip(),
        strict_step2=strict_step2,
        skip_step2=skip_step2,
        concurrent=max(1, concurrent),
        start=parse_int(start, 0) or None,
        end=parse_int(end, 0) or None,
        hold_seconds=max(0, hold_seconds),
        step3_channels=step3_channels.strip(),
        create_url=create_url.strip(),
        executor_include_franchise=executor_include_franchise,
    )

    # 朋友圈图片（由本UI上传），按上传顺序透传到任务CSV
    image_blobs: List[tuple[str, bytes]] = []
    if moments_add_images:
        for mf in moments_images:
            b = await mf.read()
            if b:
                image_blobs.append((mf.filename or f"image_{len(image_blobs)+1}.jpg", b))
        if not image_blobs:
            raise HTTPException(status_code=400, detail="已勾选朋友圈图片上传，但未选择图片文件")

    mini_cover_blob: Optional[tuple[str, bytes]] = None
    if msg_add_mini_program:
        if mini_program_cover is None:
            raise HTTPException(status_code=400, detail="已勾选添加小程序，但未上传小程序封面")
        b = await mini_program_cover.read()
        if not b:
            raise HTTPException(status_code=400, detail="小程序封面文件为空")
        mini_cover_blob = (mini_program_cover.filename or "mini_cover.jpg", b)

    store_file_blob: Optional[tuple[str, bytes]] = None
    if upload_stores:
        if store_file is None:
            # 允许走“单Excel多sheet”自动提取门店文件，无需前端单独上传
            store_file_blob = None
        else:
            b = await store_file.read()
            if not b:
                raise HTTPException(status_code=400, detail="门店文件为空")
            store_file_blob = (store_file.filename or "stores.xlsx", b)

    step2_main_store_blob: Optional[tuple[str, bytes]] = None
    if step2_main_store_file is not None:
        b = await step2_main_store_file.read()
        if b:
            step2_main_store_blob = (step2_main_store_file.filename or "step2_main_store.xlsx", b)
    step2_product_blob: Optional[tuple[str, bytes]] = None
    if step2_product_file is not None:
        b = await step2_product_file.read()
        if b:
            step2_product_blob = (step2_product_file.filename or "step2_product.xlsx", b)

    for f in files:
        lower = f.filename.lower()
        if not (lower.endswith(".csv") or lower.endswith(".xlsx")):
            raise HTTPException(status_code=400, detail=f"Only CSV/XLSX supported: {f.filename}")
        tid = str(uuid.uuid4())
        stem = Path(f.filename).stem
        dst = UPLOAD_DIR / f"{tid}_{stem}.csv"
        file_step2_store_blob: Optional[Tuple[str, bytes]] = None
        file_step2_product_blob: Optional[Tuple[str, bytes]] = None
        file_sheet_assets: Dict[str, dict] = {}
        if lower.endswith(".xlsx"):
            # 优先按“单Excel多sheet”读取；若无对应sheet则仅任务sheet生效
            raw_xlsx = await f.read()
            ms_store_blob, ms_product_blob, ms_sheet_assets = convert_uploaded_xlsx_multi_sheet_from_bytes(raw_xlsx, dst)
            file_step2_store_blob = ms_store_blob
            file_step2_product_blob = ms_product_blob
            file_sheet_assets = ms_sheet_assets or {}
        else:
            with dst.open("wb") as out:
                shutil.copyfileobj(f.file, out)
        normalize_uploaded_csv_headers(dst)
        normalize_channels_in_csv(dst)
        normalize_community_create_url_in_csv(dst, options.step3_channels)
        apply_unified_field_mapping_and_refs(dst, tid, options.step3_channels, file_sheet_assets)
        if moments_add_images and image_blobs:
            image_paths = save_uploaded_moments_images(tid, image_blobs)
            inject_moments_images_to_csv(dst, image_paths, options.step3_channels)
        if msg_add_mini_program and mini_cover_blob:
            mini_cover_path = save_uploaded_mini_program_cover(tid, mini_cover_blob)
            inject_message_mini_program_to_csv(
                dst,
                options.step3_channels,
                True,
                msg_mini_program_name.strip() or "大参林健康",
                msg_mini_program_title.strip(),
                mini_cover_path,
                msg_mini_program_page_path.strip(),
            )
        # 上传门店：优先显式上传文件；否则复用“第2步门店sheet/文件”
        resolved_store_blob = store_file_blob or step2_main_store_blob or file_step2_store_blob
        if upload_stores and resolved_store_blob:
            store_path = save_uploaded_store_file(tid, resolved_store_blob)
            inject_store_file_to_csv(
                dst,
                options.step3_channels,
                True,
                store_path,
            )
        resolved_step2_store_blob = step2_main_store_blob or file_step2_store_blob
        if resolved_step2_store_blob:
            step2_store_path = save_uploaded_main_store_file(tid, resolved_step2_store_blob)
            inject_step2_main_store_file_to_csv(dst, step2_store_path)
        resolved_step2_product_blob = step2_product_blob or file_step2_product_blob
        if resolved_step2_product_blob:
            step2_product_path = save_uploaded_main_store_file(tid, resolved_step2_product_blob)
            inject_step2_product_file_to_csv(dst, step2_product_path)
        # 关键：一个上传文件内若有多条计划，拆成多条任务记录（每条计划一条任务）
        split_files = split_csv_to_single_plan_files(dst, stem)
        op = operator.strip() or os.getenv("USER") or getpass.getuser() or "unknown"
        for sf in split_files:
            plan_name_display, channel_display = summarize_csv_meta(sf)
            # 自动策略：仅社群渠道时，默认关闭严格第2步并启用跳过第2步（免人工配置）。
            # 优先使用任务文件中的渠道；若文件为空则回退到页面勾选渠道。
            community_only = _is_community_only_channels(channel_display or options.step3_channels)
            file_options = TaskOptions(
                connect_cdp=options.connect_cdp,
                cdp_endpoint=options.cdp_endpoint,
                strict_step2=(False if community_only else options.strict_step2),
                skip_step2=(True if community_only else options.skip_step2),
                concurrent=options.concurrent,
                start=options.start,
                end=options.end,
                hold_seconds=options.hold_seconds,
                step3_channels=options.step3_channels,
                create_url=options.create_url,
                executor_include_franchise=options.executor_include_franchise,
            )
            task = Task(
                id=str(uuid.uuid4()),
                filename=f.filename if len(split_files) == 1 else f"{f.filename}#{sf.stem.split('_')[-1]}",
                file_path=str(sf),
                options=file_options,
                operator=op,
                plan_name_display=plan_name_display,
                channel_display=channel_display,
            )
            await runner.add_task(task, auto_start=False)
            created.append(task.to_dict())
    return JSONResponse({"created": created})


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> JSONResponse:
    t = await runner.retry_task(task_id)
    return JSONResponse({"created": t.to_dict()})


@app.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: str) -> JSONResponse:
    t = await runner.pause_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.status == "running":
        raise HTTPException(status_code=409, detail="运行中任务不支持暂停，请等待完成后再操作")
    return JSONResponse({"task": t.to_dict()})


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str) -> JSONResponse:
    t = await runner.resume_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return JSONResponse({"task": t.to_dict()})


@app.post("/api/tasks/{task_id}/delete")
async def delete_task(task_id: str) -> JSONResponse:
    ok = await runner.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="删除失败：任务不存在或正在运行")
    return JSONResponse({"task_id": task_id, "deleted": True})


@app.post("/api/tasks/pause-batch")
async def batch_pause_tasks(ids: List[str] = Body(...)) -> JSONResponse:
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    result = await runner.batch_pause_tasks([str(i) for i in ids])
    return JSONResponse(result)


@app.post("/api/tasks/delete-batch")
async def batch_delete_tasks(ids: List[str] = Body(...)) -> JSONResponse:
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    result = await runner.batch_delete_tasks([str(i) for i in ids])
    return JSONResponse(result)


@app.post("/api/tasks/start")
async def start_pending_tasks() -> JSONResponse:
    ids = await runner.start_pending()
    return JSONResponse({"started_ids": ids, "count": len(ids)})


@app.post("/api/tasks/{task_id}/start")
async def start_one_task(task_id: str) -> JSONResponse:
    ok = await runner.start_task(task_id)
    return JSONResponse({"task_id": task_id, "started": bool(ok)})


@app.post("/api/tasks/retry-failed")
async def retry_failed() -> JSONResponse:
    ids = await runner.retry_failed()
    return JSONResponse({"created_ids": ids})


UI_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>精准营销自动化任务中心</title>
  <style>
    :root{
      --bg:#f3f2fb;
      --card:#ffffff;
      --line:#ecebf5;
      --text:#1d1d1f;
      --sub:#515154;
      --hint:#6e6e73;
      --brand:#2f2a7e;
      --brand-dark:#221f5c;
      --brand-soft:#f1efff;
      --nav:#ffffff;
      --nav-active:#f4f2ff;
      --radius:16px;
      --control-h:40px;
      --font:14px;
      --space-1:8px;
      --space-2:12px;
      --space-3:16px;
      --space-4:20px;
    }
    *{box-sizing:border-box}
    body{font-family:"SF Pro Text","SF Pro Display","PingFang SC","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:radial-gradient(1200px 700px at 20% -10%,#ede9ff 0%,transparent 60%),radial-gradient(1200px 700px at 100% 0%,#efe8ff 0%,transparent 58%),var(--bg);color:var(--text);font-size:var(--font);-webkit-font-smoothing:antialiased}
    .app-shell{max-width:1480px;margin:0 auto;min-height:100vh;padding:18px var(--space-3) 24px var(--space-3)}
    .main{padding:0}
    .page-title{margin:0 0 var(--space-2) 0;font-size:22px;line-height:1.2;font-weight:700;letter-spacing:-.01em;color:var(--text)}
    .card-title{margin:0 0 var(--space-2) 0;font-size:18px;line-height:1.25;font-weight:700;letter-spacing:-.01em;color:var(--text)}
    .card{background:rgba(255,255,255,.96);border:none;border-radius:18px;padding:var(--space-3);margin-bottom:var(--space-2);box-shadow:0 10px 30px rgba(42,34,94,.08)}
    .row{display:flex;gap:var(--space-2);flex-wrap:wrap;align-items:center}
    .section-title{font-size:15px;font-weight:700;color:#1d1d1f;margin:0 0 var(--space-2) 0;display:flex;align-items:center;gap:8px;line-height:1.3}
    .step-no{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;background:var(--brand);color:#fff;font-size:12px;font-weight:700}
    .step-box{border:none;border-radius:14px;padding:var(--space-2);background:#fff;margin-bottom:10px;transition:all .2s ease;box-shadow:inset 0 0 0 1px rgba(120,110,190,.10)}
    .step-box:hover{box-shadow:inset 0 0 0 1px rgba(120,110,190,.16),0 8px 20px rgba(47,42,126,.06)}
    /* 按步骤区分渐变背景（参考卡片轻渐变风格） */
    .card .step-box:nth-of-type(1){
      background:linear-gradient(135deg,#f6f2ff 0%,#fff 55%,#f2f7ff 100%);
      border-color:transparent;
    }
    .card .step-box:nth-of-type(2){
      background:linear-gradient(135deg,#fff7f3 0%,#fff 52%,#f3f9ff 100%);
      border-color:transparent;
    }
    .card .step-box:nth-of-type(3){
      background:linear-gradient(135deg,#f2fff8 0%,#fff 55%,#f4f5ff 100%);
      border-color:transparent;
    }
    .step-box.compact{
      padding:10px;
      background:rgba(255,255,255,.52) !important;
      border:none !important;
      box-shadow:0 8px 22px rgba(62,54,120,.08) !important;
      backdrop-filter:blur(10px) saturate(118%);
      -webkit-backdrop-filter:blur(10px) saturate(118%);
    }
    .step-box.compact .form-grid{
      gap:8px 10px;
    }
    .step-box.compact .field{
      min-height:38px;
      gap:6px;
    }
    .step-box.compact .step-caption{
      margin-top:4px;
    }
    .step-caption{font-size:12px;color:var(--hint);margin-top:6px;line-height:1.6}
    .form-grid{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:10px 12px}
    .form-grid .full{grid-column:1 / -1}
    .field{display:flex;align-items:center;gap:8px;min-height:44px}
    .field.between{justify-content:space-between}
    .field.vertical{flex-direction:column;align-items:flex-start}
    .label{min-width:112px;color:var(--sub);font-size:13px;font-weight:500}
    .inline-check{display:inline-flex;align-items:center;gap:6px;color:var(--sub);font-size:13px}
    .field input[type="text"], .field input[type="number"], .field input:not([type]), .field select{
      height:var(--control-h);box-sizing:border-box;
    }
    .field input[type="file"]{
      width:100%;
      max-width:560px;
      height:44px;
      padding:6px 10px;
      background:rgba(255,255,255,.78);
      border:1px solid rgba(120,110,190,.20);
      border-radius:12px;
      color:#66647a;
      line-height:30px;
    }
    .field input[type="file"]::file-selector-button{
      height:30px;
      padding:0 14px;
      margin-right:12px;
      border:1px solid #d0c9f2;
      border-radius:9px;
      background:linear-gradient(180deg,#f6f3ff,#ece7ff);
      color:#312b84;
      font-size:13px;
      font-weight:600;
      cursor:pointer;
    }
    .field input[type="file"]:hover{
      border-color:#c9c2ef;
      box-shadow:0 0 0 3px rgba(87,74,194,.08);
    }
    .field input[type="file"]::file-selector-button:hover{
      background:linear-gradient(180deg,#efeaff,#e4ddff);
    }
    /* 仅任务文件：去掉线框和背景，保持更简洁 */
    #files.file-uniform{
      background:transparent !important;
      border:none !important;
      box-shadow:none !important;
      padding:0 !important;
      height:auto !important;
      line-height:normal !important;
      color:var(--sub);
    }
    #files.file-uniform:hover{
      border:none !important;
      box-shadow:none !important;
    }
    #files.file-uniform::file-selector-button{
      margin-right:10px;
      border:none;
      border-radius:12px;
      background:linear-gradient(135deg,rgba(146,126,255,.26),rgba(134,189,255,.22));
      box-shadow:inset 0 0 0 1px rgba(114,126,196,.22);
    }
    .field.vertical .row{width:100%}
    .field.vertical .row label{display:flex;align-items:center;gap:6px;color:var(--sub);font-size:13px}
    .actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding-top:6px}
    .subcard{border:none;background:linear-gradient(180deg,#fefeff,#faf9ff);border-radius:12px;padding:12px;margin-top:8px;box-shadow:inset 0 0 0 1px rgba(120,110,190,.08)}
    .adv-toggle{display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 14px;border-radius:999px;background:var(--brand-soft);color:#312b84;border:1px solid #dbd4ff;cursor:pointer;font-weight:600}
    .adv-toggle.text-link{
      height:auto;
      padding:0;
      border:none;
      background:transparent;
      color:#4b46a3;
      border-radius:0;
      box-shadow:none;
      font-weight:500;
      text-decoration:underline;
      text-underline-offset:3px;
    }
    .adv-toggle.text-link:hover{background:transparent;color:#312b84}
    .adv-panel{display:none;border:none;background:#faf8ff;border-radius:12px;padding:12px;margin-top:8px;box-shadow:inset 0 0 0 1px rgba(120,110,190,.14)}
    .adv-panel.open{display:block}
    .tiny{font-size:12px;color:var(--hint);line-height:1.55}
    .tiny.wrap{
      display:block;
      white-space:normal;
      word-break:normal;
      overflow-wrap:break-word;
      line-break:auto;
      max-width:100%;
    }
    .field.full .tiny{
      margin-left:8px;
      white-space:normal;
      overflow:visible;
      text-overflow:clip;
      max-width:none;
      line-height:1.5;
    }
    .upload-line{
      display:grid !important;
      grid-template-columns:112px minmax(560px,1fr) minmax(180px,auto);
      align-items:center;
      gap:12px;
      width:100%;
    }
    .upload-line .label{
      margin:0;
      min-width:112px;
      flex:none;
    }
    .upload-line .tiny{
      margin:0;
      max-width:none;
      white-space:normal;
      word-break:break-word;
    }
    .file-uniform{
      width:560px !important;
      max-width:560px !important;
      min-width:560px !important;
    }
    .channel-grid{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:8px 14px}
    .compose-side .channel-grid{
      grid-template-columns:repeat(2,minmax(170px,1fr));
      gap:8px 10px;
    }
    .channel-block{border:none;border-radius:0;background:transparent;padding:0;box-shadow:none}
    .channel-item{
      display:flex;
      align-items:center;
      gap:10px;
      padding:6px 2px;
      border-radius:0;
      background:transparent;
      border:none;
      transition:all .2s ease;
    }
    .channel-item:hover{
      background:transparent;
      transform:none;
    }
    .channel-item input{margin-top:0;transform:scale(1.08)}
    .channel-icon{
      width:30px;
      height:30px;
      border-radius:10px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      font-size:12px;
      font-weight:800;
      letter-spacing:.2px;
      color:#fff;
      box-shadow:0 6px 12px rgba(28,35,52,.18);
      flex:0 0 30px;
    }
    .channel-icon.sms{background:linear-gradient(135deg,#8aa0c8 0%,#6f86b2 52%,#5d739f 100%)}
    .channel-icon.msg{background:linear-gradient(135deg,#334155 0%,#273449 48%,#1f2937 100%)}
    .channel-icon.group{background:linear-gradient(135deg,#1f9d8f 0%,#178f84 50%,#137a74 100%)}
    .channel-icon.moments{background:linear-gradient(135deg,#7b5cff 0%,#6b46f0 50%,#5b34dd 100%)}
    .channel-main{font-size:13px;color:#111827;font-weight:700;line-height:1.35}
    .channel-strong{font-weight:800;color:#312b84}
    .material-panel{border:1px solid #e8e6f3;background:#fcfcfe;border-radius:12px;padding:12px}
    .material-title{font-size:14px;font-weight:600;color:#0f172a;margin-bottom:8px}
    .channel-inline-config{margin-top:10px}
    .hidden{display:none !important}
    input,button,select{padding:8px 12px;border:1px solid #d7d4e8;border-radius:10px;font-size:13px;outline:none}
    input:focus,select:focus{border-color:#bdb5ed;box-shadow:0 0 0 3px rgba(87,74,194,.12)}
    button{background:linear-gradient(180deg,#3a328f,#2f2a7e);color:#fff;border:none;cursor:pointer;height:40px;padding:0 16px;font-weight:600;letter-spacing:.01em;box-shadow:0 6px 14px rgba(47,42,126,.24)}
    button:hover{background:linear-gradient(180deg,#302a82,#252066)}
    button.secondary{background:#fff;color:#2f2a7e;border:1px solid #cdc7ef;box-shadow:none}
    button.secondary:hover{background:#f7f5ff}
    .tip{font-size:12px;color:var(--hint);line-height:1.55}
    .hint{font-size:12px;color:var(--hint);display:block}
    table{width:100%;border-collapse:separate;border-spacing:0}
    th,td{border-bottom:1px solid rgba(120,110,190,.12);padding:10px 8px;text-align:left;font-size:13px;vertical-align:top}
    th{background:#f7f6fc;font-weight:600;color:#3e3a56;position:sticky;top:0;z-index:1}
    tbody tr:hover td{background:rgba(245,243,255,.45)}
    .status-pending{color:#6b7280}
    .status-running{color:#2563eb}
    .status-success{color:#059669}
    .status-failed{color:#dc2626}
    .status-paused{color:#b45309}
    #logs{background:#0b1020;color:#dbeafe;height:58vh;overflow:auto;padding:10px;border-radius:8px;white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:12px}
    .file-hero{
      background:transparent;
      border:none;
      border-radius:0;
      padding:0;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
    }
    .file-hero .row{
      flex:1;
      min-width:0;
      align-items:center;
    }
    .file-hero .row .label{
      flex:0 0 112px;
    }
    .file-hero .row input[type="file"]{
      flex:1;
      max-width:none;
      min-width:260px;
    }
    .upload-actions{display:flex;gap:14px;align-items:center;margin-top:6px;padding-left:112px}
    .primary-actions button{height:44px;padding:0 20px;font-size:14px;font-weight:700}
    .log-modal{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;z-index:9999}
    .log-modal.open{display:flex}
    .log-panel{width:min(1200px,92vw);max-height:88vh;background:#fff;border-radius:14px;border:1px solid #d1d5db;padding:14px}
    .log-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
    .material-modal{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;z-index:9998}
    .material-modal.open{display:flex}
    .material-panel{width:min(1260px,94vw);max-height:90vh;background:#fff;border-radius:14px;border:none;padding:14px;overflow:auto;box-shadow:0 18px 42px rgba(15,23,42,.16)}
    .material-row{border:none;border-radius:12px;padding:10px;margin-bottom:10px;box-shadow:inset 0 0 0 1px rgba(120,110,190,.10)}
    .material-row h4{margin:0 0 8px 0;font-size:14px}
    .material-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .img-preview{display:flex;gap:8px;flex-wrap:wrap}
    .img-preview img{width:64px;height:64px;object-fit:cover;border-radius:8px;border:1px solid #ddd}
    .path-chip{display:inline-block;font-size:12px;padding:2px 8px;border:1px solid #ddd;border-radius:999px;background:#fafafa;margin:0 6px 6px 0}
    .link-pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#f5f1ff;color:#312b84;border:1px solid #d9d0ff;font-size:12px;text-decoration:none}
    @media (max-width: 1100px){
      .form-grid{grid-template-columns:1fr}
      .label{min-width:90px}
      .channel-grid{grid-template-columns:1fr}
      .upload-line{grid-template-columns:1fr}
      .file-uniform{width:100% !important;min-width:0 !important;max-width:none !important}
    }
    /* === Editorial high-end visual refresh (DESIGN.md aligned, no behavior changes) === */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Work+Sans:wght@400;500;600;700&display=swap');
    :root{
      --im-bg:#f9f9f9;
      --im-bg-soft:#f4f3f3;
      --im-bg-deep:#eceaea;
      --im-ink:#1c2334;
      --im-sub:#454b5a;
      --im-hint:#6a6f7d;
      --im-brand:#1c2334;
      --im-brand-2:#2b3348;
      --im-accent:#e4c02f;
      --im-accent-deep:#715d00;
      --im-card:#ffffff;
      --im-ghost:rgba(28,35,52,.13);
      --im-shadow:0 28px 56px rgba(28,35,52,.07);
    }
    body{
      background:
        radial-gradient(1200px 640px at 8% -10%, rgba(228,192,47,.12), transparent 58%),
        radial-gradient(1400px 760px at 100% -16%, rgba(28,35,52,.10), transparent 62%),
        linear-gradient(180deg,#fafafa 0%,#f5f5f7 100%);
      color:var(--im-ink);
      font-family:"Work Sans","PingFang SC","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }
    .app-shell{
      max-width:1440px;
      padding:22px 18px 28px;
    }
    .card{
      background:linear-gradient(180deg,rgba(255,255,255,.96),rgba(247,247,248,.96));
      border:none;
      border-radius:22px;
      box-shadow:var(--im-shadow);
      padding:18px;
      margin-bottom:14px;
    }
    .card-title{
      font-family:"Plus Jakarta Sans","PingFang SC","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:1.78rem;
      font-weight:700;
      color:var(--im-ink);
      margin-bottom:14px;
      letter-spacing:.2px;
    }
    .section-title{
      font-family:"Plus Jakarta Sans","PingFang SC","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:1.04rem;
      font-weight:700;
      color:var(--im-ink);
      margin-bottom:10px;
    }
    .step-no{
      width:24px;
      height:24px;
      background:linear-gradient(135deg,var(--im-brand),var(--im-brand-2));
      box-shadow:0 6px 14px rgba(28,35,52,.25);
    }
    .step-box{
      border:none;
      box-shadow:none;
      border-radius:16px;
      padding:12px;
      margin-bottom:12px;
    }
    .card .step-box:nth-of-type(1){
      background:linear-gradient(135deg,#ffffff 0%,#f4f3f3 100%);
    }
    .card .step-box:nth-of-type(2){
      background:linear-gradient(135deg,#fbfbfb 0%,#f2f2f2 100%);
    }
    .card .step-box:nth-of-type(3){
      background:linear-gradient(135deg,#fefefe 0%,#efefef 100%);
    }
    .step-caption,.tip,.tiny,.hint{
      color:var(--im-hint);
      line-height:1.55;
    }
    .label{
      color:var(--im-sub);
      font-weight:600;
    }
    .upload-line{
      grid-template-columns:104px minmax(580px,1fr) minmax(180px,auto);
      gap:10px;
    }
    input,button,select{
      border-radius:10px;
      border:1px solid rgba(28,35,52,.10);
      font-size:13px;
    }
    input[type="text"],input[type="number"],select{
      background:transparent;
      border:none;
      border-bottom:1px solid rgba(28,35,52,.24);
      border-radius:0;
      padding-left:0;
      padding-right:0;
    }
    input:focus,select:focus{
      border-color:var(--im-brand);
      box-shadow:none;
    }
    .field input[type="file"]{
      height:42px;
      padding:5px 10px;
      border:1px solid rgba(28,35,52,.16);
      border-radius:12px;
      background:linear-gradient(180deg,#ffffff,#f4f3f3);
      color:#3f4657;
    }
    .field input[type="file"]::file-selector-button{
      border-radius:10px;
      border:1px solid rgba(28,35,52,.18);
      background:linear-gradient(180deg,#ffffff,#eeeeef);
      color:#222938;
      font-weight:600;
    }
    .field input[type="file"]::file-selector-button:hover{
      background:linear-gradient(180deg,#f8f8f8,#e9e9ea);
    }
    .adv-panel{
      background:linear-gradient(180deg,#fbfbfb,#f3f3f4);
      border:none;
      box-shadow:none;
    }
    .adv-toggle.text-link{
      color:#2f3650;
      text-decoration:none;
      border-bottom:1px dashed rgba(28,35,52,.38);
      font-weight:600;
    }
    .adv-toggle.text-link:hover{
      color:#111827;
      border-bottom-color:rgba(28,35,52,.62);
    }
    button{
      background:linear-gradient(135deg,#7c89d9 0%,#9aa5ea 52%,#b7c0f2 100%);
      border:1px solid rgba(92,108,185,.38);
      box-shadow:0 10px 22px rgba(124,137,217,.24);
      font-weight:700;
      letter-spacing:.15px;
      color:#ffffff;
    }
    button:hover{
      background:linear-gradient(135deg,#8896e1 0%,#a8b2ee 54%,#c3cbf6 100%);
      border-color:rgba(92,108,185,.44);
    }
    button.secondary{
      background:linear-gradient(135deg,#f8faff 0%,#eef2ff 50%,#f5f7ff 100%);
      color:#4a5685;
      border:1px solid rgba(123,137,217,.30);
      box-shadow:none;
      font-weight:600;
    }
    button.secondary:hover{
      background:linear-gradient(135deg,#f3f6ff 0%,#e9eeff 52%,#f1f4ff 100%);
      border-color:rgba(123,137,217,.42);
      color:#3f4b79;
    }
    .primary-actions button{
      min-width:140px;
      height:46px;
    }
    .link-pill{
      border:1px solid rgba(28,35,52,.18);
      background:linear-gradient(180deg,#fbfbfb,#f2f2f2);
      color:#2b3348;
      font-weight:600;
      border-radius:999px;
      padding:4px 10px;
    }
    table{
      border:none;
      border-radius:12px;
      overflow:hidden;
      background:linear-gradient(180deg,#ffffff,#f8f8f8);
    }
    th{
      background:linear-gradient(180deg,#f2f2f3,#ececec);
      color:#2d3342;
      font-weight:700;
      border-bottom:1px solid rgba(28,35,52,.08);
    }
    td{
      border-bottom:1px solid rgba(28,35,52,.06);
      color:#1f2937;
    }
    tbody tr:hover td{
      background:rgba(28,35,52,.035);
    }
    .material-panel,.log-panel{
      border:none;
      border-radius:16px;
      box-shadow:0 22px 52px rgba(28,35,52,.22);
    }
    .material-row{
      border:none;
      box-shadow:none;
      background:linear-gradient(180deg,#ffffff,#f3f3f3);
    }
    .hero-bar{
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:12px;
      margin-bottom:10px;
    }
    .hero-title{
      font-family:"Plus Jakarta Sans","PingFang SC","Helvetica Neue",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:1.42rem;
      font-weight:700;
      color:var(--im-ink);
      letter-spacing:.1px;
    }
    .hero-sub{
      font-size:12px;
      color:var(--im-hint);
      margin-top:2px;
    }
    .theme-wrap{display:flex;align-items:center;gap:8px}
    .theme-switch{
      display:inline-flex;
      align-items:center;
      gap:6px;
      padding:4px;
      border:1px solid rgba(28,35,52,.12);
      border-radius:999px;
      background:linear-gradient(180deg,#fff,#f4f6fb);
    }
    .theme-btn{
      width:30px;height:30px;border-radius:999px;border:none;cursor:pointer;
      display:inline-flex;align-items:center;justify-content:center;
      color:#4b5563;background:transparent;box-shadow:none;padding:0;
      transition:all .18s ease;
    }
    .theme-btn svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
    .theme-btn:hover{color:#111827;background:rgba(28,35,52,.08)}
    .theme-btn.active{
      background:linear-gradient(135deg,#7c89d9 0%,#9aa5ea 52%,#b7c0f2 100%);
      color:#fff;
      box-shadow:0 8px 16px rgba(124,137,217,.28);
    }
    .compose-layout{
      display:grid;
      grid-template-columns:1fr;
      gap:14px;
      align-items:stretch;
    }
    .compose-main>.step-box,.compose-side>.step-box{height:100%}
    .compose-side{display:none !important}
    .compose-main,.compose-side{
      display:flex;
      flex-direction:column;
      gap:10px;
    }
    .action-strip{
      display:flex;
      align-items:center;
      justify-content:flex-start;
      gap:12px;
      margin:2px 0 10px 0;
      padding:2px 0;
    }
    .action-strip button{
      min-width:180px;
      height:48px;
      font-size:16px;
      border-radius:14px;
    }
    .action-strip button.secondary{
      min-width:200px;
    }
    .batch-op{
      display:flex;
      align-items:center;
      gap:10px;
      margin-left:8px;
      padding-left:10px;
      border-left:1px solid rgba(28,35,52,.12);
    }
    .batch-op .tiny{margin:0;color:#6b7280}
    .task-table-wrap{
      border-radius:14px;
      overflow:hidden;
      background:#fff;
    }
    .check-col{width:38px;text-align:center}
    .check-col input{transform:scale(1.05)}
    .task-card-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      margin-bottom:10px;
    }
    .task-meta{
      font-size:12px;
      color:var(--im-hint);
    }
    .task-section-spacer{
      margin-top:2px;
      border-top:1px solid rgba(28,35,52,.08);
      padding-top:10px;
    }
    @media (max-width: 1180px){
      .compose-layout{grid-template-columns:1fr}
      .hero-bar{flex-direction:column;align-items:flex-start}
      .theme-wrap{width:100%}
      .theme-switch{width:100%;justify-content:flex-start}
    }
    html[data-theme="dark"]{color-scheme:dark}
    html[data-theme="dark"] body{
      background:
        radial-gradient(1180px 620px at 10% -12%, rgba(127,160,255,.18), transparent 60%),
        radial-gradient(1380px 760px at 100% -18%, rgba(182,151,255,.15), transparent 62%),
        linear-gradient(180deg,#283043 0%,#222a3b 54%,#1d2433 100%);
      color:#ecf1fa;
    }
    html[data-theme="dark"] .card{
      background:linear-gradient(180deg,rgba(47,57,78,.94),rgba(38,47,66,.95));
      box-shadow:0 22px 46px rgba(16,22,38,.28), inset 0 1px 0 rgba(255,255,255,.06);
    }
    html[data-theme="dark"] .hero-title,
    html[data-theme="dark"] .section-title,
    html[data-theme="dark"] .card-title{color:#f5f8ff}
    html[data-theme="dark"] .label,
    html[data-theme="dark"] .channel-main{color:#dbe4f2}
    html[data-theme="dark"] .tiny,
    html[data-theme="dark"] .hint,
    html[data-theme="dark"] .step-caption,
    html[data-theme="dark"] .hero-sub,
    html[data-theme="dark"] .task-meta{color:#aab6c9}
    html[data-theme="dark"] .step-box{
      background:linear-gradient(180deg,#313b52,#283247) !important;
      box-shadow:inset 0 0 0 1px rgba(183,196,228,.14), 0 8px 20px rgba(15,21,35,.16);
    }
    html[data-theme="dark"] .step-box.compact{
      background:rgba(57,69,95,.52) !important;
      border:none !important;
      box-shadow:0 10px 24px rgba(8,13,24,.22) !important;
      backdrop-filter:blur(10px) saturate(120%);
      -webkit-backdrop-filter:blur(10px) saturate(120%);
    }
    html[data-theme="dark"] .field input[type="file"]{
      background:linear-gradient(180deg,#334059,#2a3448);
      border-color:rgba(203,216,245,.22);
      color:#e8eefc;
    }
    html[data-theme="dark"] .field input[type="file"]::file-selector-button{
      background:linear-gradient(180deg,#4a5a79,#394a67);
      border-color:rgba(203,216,245,.28);
      color:#f6f9ff;
    }
    html[data-theme="dark"] #files.file-uniform{
      background:transparent !important;
      border:none !important;
      box-shadow:none !important;
      color:#dbe4f3;
    }
    html[data-theme="dark"] #files.file-uniform:hover{
      border:none !important;
      box-shadow:none !important;
    }
    html[data-theme="dark"] #files.file-uniform::file-selector-button{
      background:linear-gradient(135deg,rgba(161,178,255,.28),rgba(124,206,255,.22));
      border:none;
      box-shadow:inset 0 0 0 1px rgba(214,226,246,.24);
      color:#f5f8ff;
    }
    html[data-theme="dark"] .adv-panel{background:linear-gradient(180deg,#303b54,#273349)}
    html[data-theme="dark"] .link-pill{
      background:linear-gradient(180deg,#394865,#2f3d58);
      border-color:rgba(203,216,245,.25);
      color:#e0e8ff;
    }
    html[data-theme="dark"] .task-table-wrap{background:#2a3449}
    html[data-theme="dark"] table{background:linear-gradient(180deg,#34425d,#2a3449)}
    html[data-theme="dark"] th{
      background:linear-gradient(180deg,#455677,#374762);
      color:#edf2fb;
      border-bottom-color:rgba(214,226,246,.24);
    }
    html[data-theme="dark"] td{
      color:#f1f5ff;
      border-bottom-color:rgba(214,226,246,.16);
    }
    html[data-theme="dark"] tbody tr:hover td{background:rgba(189,206,242,.12)}
    html[data-theme="dark"] .theme-switch{
      background:linear-gradient(180deg,#3a4967,#2f3d58);
      border-color:rgba(214,226,246,.26);
    }
    html[data-theme="dark"] .theme-btn{color:#b7c3d8}
    html[data-theme="dark"] .theme-btn:hover{color:#f4f7ff;background:rgba(214,226,246,.14)}
    html[data-theme="dark"] .theme-btn.active{
      background:linear-gradient(135deg,#8ea2ff 0%,#9f89ff 52%,#8de1ff 100%);
      color:#ffffff;
    }
    #logs{
      background:#132138;
      color:#e3ecff;
      border-radius:10px;
      border:1px solid rgba(180,202,243,.30);
    }
  </style>
</head>
<body>
<div class="app-shell">
  <main class="main">
    <div>
      <div class="card">
        <div class="hero-bar">
          <div>
            <div class="hero-title">精准营销自动化配置（业务版）</div>
            <div class="hero-sub">选择文件 -> 添加素材 -> 开始执行</div>
          </div>
          <div class="theme-wrap">
            <div class="theme-switch" role="group" aria-label="页面显示模式">
              <button id="themeModeLight" class="theme-btn" type="button" title="浅色" data-mode="light" aria-label="浅色">
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5M18.9 5.1l-1.6 1.6M6.7 17.3l-1.6 1.6M18.9 18.9l-1.6-1.6M6.7 6.7 5.1 5.1"/></svg>
              </button>
              <button id="themeModeDark" class="theme-btn" type="button" title="深色" data-mode="dark" aria-label="深色">
                <svg viewBox="0 0 24 24"><path d="M20 14.3A8 8 0 1 1 9.7 4 6.5 6.5 0 1 0 20 14.3Z"/></svg>
              </button>
            </div>
          </div>
        </div>
        <div class="compose-layout">
          <div class="compose-main">
            <div class="step-box compact">
          <div class="form-grid">
            <div class="field full upload-line file-hero">
              <span class="label">任务文件</span>
              <input id="files" class="file-uniform" type="file" multiple accept=".csv,.xlsx"/>
            </div>
            <div class="field full upload-actions">
              <button id="advToggleBtn" type="button" class="adv-toggle text-link" onclick="toggleAdvancedConfig()">高级配置（展开）</button>
            </div>
            <div class="field full">
              <span class="label">模板下载</span>
              <div class="row">
                <a class="link-pill" href="/api/template/xlsx">下载Excel统一模板</a>
                <a class="link-pill" href="/api/template/csv">下载CSV模板(防乱码)</a>
              </div>
            </div>
          </div>
          <div id="advancedConfig" class="adv-panel">
            <div class="form-grid">
              <div class="field vertical">
                <label><span class="label">浏览器调试地址</span><input id="cdp_endpoint" value="http://127.0.0.1:18800" style="width:220px"/></label>
                <span class="tiny">作用：接管本地已登录浏览器（默认 127.0.0.1:18800）。</span>
              </div>
              <div class="field vertical">
                <label><span class="label">并发任务数</span><input id="concurrent" type="number" min="1" value="1" style="width:88px"/></label>
                <span class="tiny">作用：同时执行的任务数。建议先用 1 验证稳定性。</span>
              </div>
              <div class="field vertical">
                <label><span class="label">保留浏览器(秒)</span><input id="hold_seconds" type="number" min="0" value="2" style="width:88px"/></label>
                <span class="tiny">作用：任务结束后页面停留时间，便于人工复核。</span>
              </div>
              <div class="field vertical full">
                <label class="inline-check channel-strong"><input id="executor_include_franchise" type="checkbox" checked/> 执行员工包含加盟区域（自动同步勾选“xx加盟”节点）</label>
                <span class="tiny wrap">示例：执行员工=广佛省区，自动追加广佛省区加盟；执行员工=大郑州营运区，自动追加大郑州营运区加盟。</span>
              </div>
            </div>
          </div>
            </div>
          </div>
          <div class="compose-side">
            <div class="step-box">
              <div class="section-title"><span class="step-no">2</span>第2步：选中发送渠道（可多选）</div>
              <div class="channel-grid">
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="短信"/>
                <span class="channel-icon sms">短信</span>
                <span><div class="channel-main">短信</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户消息"/>
                <span class="channel-icon msg">1对1</span>
                <span><div class="channel-main">会员通-发客户消息</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发送社群"/>
                <span class="channel-icon group">社群</span>
                <span><div class="channel-main">会员通-发送社群</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户朋友圈"/>
                <span class="channel-icon moments">朋友</span>
                <span><div class="channel-main">会员通-发客户朋友圈</div></span>
              </label>
            </div>
              </div>
              <div class="step-caption">素材配置请在任务列表中按计划点击“添加素材”进行设置。</div>
            </div>
          </div>
        </div>
      </div>

      <div class="action-strip">
        <button onclick="startExecute()">开始执行</button>
        <button class="secondary" onclick="retryFailed()">一键重试失败任务</button>
        <div class="batch-op">
          <button class="secondary" onclick="batchPauseSelected()">批量暂停</button>
          <button class="secondary" onclick="batchDeleteSelected()">批量删除</button>
          <span class="tiny" id="batchInfo">已选 0 项</span>
        </div>
      </div>

      <div class="card task-section-spacer">
        <div class="task-card-head">
          <h3 class="card-title" style="margin-bottom:0">任务列表</h3>
          <div class="task-meta">按计划添加素材后，再执行任务</div>
        </div>
        <div class="task-table-wrap">
          <table>
            <thead><tr>
              <th class="check-col"><input id="selectAllTasks" type="checkbox" onchange="toggleSelectAllTasks(this.checked)"/></th>
              <th>文件</th><th>计划名称</th><th>发送渠道</th><th>状态</th><th>进度</th><th>成功/失败</th><th>开始</th><th>完成</th><th>耗时(s)</th><th>操作</th>
            </tr></thead>
            <tbody id="taskRows"></tbody>
          </table>
        </div>
      </div>
    </div>
  </main>
</div>
<div id="logModal" class="log-modal" onclick="closeLogModal(event)">
  <div class="log-panel" onclick="event.stopPropagation()">
    <div class="log-head">
      <div id="logTitle" style="color:#6b7280">未选中任务</div>
      <button class="secondary" onclick="closeLogModal()">关闭</button>
    </div>
    <div id="logs"></div>
  </div>
</div>
<div id="materialModal" class="material-modal" onclick="closeMaterialModal(event)">
  <div class="material-panel" onclick="event.stopPropagation()">
    <div class="log-head">
      <div id="materialTitle" style="color:#374151;font-weight:600">按计划添加素材</div>
      <div class="row">
        <button class="secondary" onclick="closeMaterialModal()">关闭</button>
        <button onclick="saveTaskMaterials()">保存素材</button>
      </div>
    </div>
    <div class="tiny" style="margin-bottom:8px">说明：素材按计划行独立配置，可随时覆盖，保存后会回写到该任务CSV，重试任务会按最新素材执行。</div>
    <div id="materialRows"></div>
  </div>
</div>
<script>
let selectedTaskId = "";
let logOffset = 0;
let materialTaskId = "";
let materialPlans = [];
let materialTokenSeq = 0;
let uploading = false;
let selectedTaskIds = new Set();
const materialFileMap = new Map();
const LS_KEYS = {
  tasks: 'pm_ui_cached_tasks_v1',
  selectedTaskId: 'pm_ui_selected_task_id_v1',
  logsText: 'pm_ui_cached_logs_text_v1',
  logsTitle: 'pm_ui_cached_logs_title_v1',
  prefs: 'pm_ui_prefs_v1',
};

let currentThemeMode = 'light';
function applyTheme(theme){
  const root = document.documentElement;
  if(theme === 'dark') root.setAttribute('data-theme', 'dark');
  else root.removeAttribute('data-theme');
}
function updateThemeButtons(mode){
  document.querySelectorAll('.theme-btn').forEach(btn => {
    const active = btn.getAttribute('data-mode') === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}
function setThemeMode(mode, persist=true){
  const m = (mode === 'dark') ? 'dark' : 'light';
  currentThemeMode = m;
  if(persist){
    // 仅记录临时操作态；页面最终仍以时间规则自动切换
    saveLocal('pm_ui_theme_manual_last', m);
  }
  updateThemeButtons(m);
  applyTheme(m);
}
function modeByTime(){
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes();
  const mins = h * 60 + m;
  // 07:00-17:29 浅色；17:30-次日06:59 深色
  return (mins >= 420 && mins < 1050) ? 'light' : 'dark';
}
function syncThemeByTime(){
  const mode = modeByTime();
  if(mode !== currentThemeMode){
    setThemeMode(mode, false);
  }
}

function saveLocal(key, value){
  try{ localStorage.setItem(key, JSON.stringify(value)); }catch(_){}
}
function loadLocal(key, fallback=null){
  try{
    const raw = localStorage.getItem(key);
    if(!raw) return fallback;
    return JSON.parse(raw);
  }catch(_){ return fallback; }
}

function toggleAdvancedConfig(){
  const panel = document.getElementById('advancedConfig');
  const btn = document.getElementById('advToggleBtn');
  if(!panel) return;
  panel.classList.toggle('open');
  if(btn){
    btn.textContent = panel.classList.contains('open') ? '高级配置（收起）' : '高级配置（展开）';
  }
  saveUiPrefs();
}

function selectedChannels(){
  return Array.from(document.querySelectorAll('.step3_channel:checked')).map(el => el.value);
}

function mirrorCommunityMaterialInputs(){
  const mapChecks = [
    ['msg_add_mini_program', 'msg_add_mini_program_community'],
    ['moments_add_images', 'moments_add_images_community'],
  ];
  for(const [mainId, communityId] of mapChecks){
    const main = document.getElementById(mainId);
    const community = document.getElementById(communityId);
    if(!main || !community) continue;
    if(community.checked !== main.checked) community.checked = main.checked;
  }
}

function syncChannelMaterials(){
  const channels = selectedChannels();
  const isCommunity = channels.includes('会员通-发送社群');
  const showMoments = channels.includes('会员通-发客户朋友圈') || isCommunity;
  const showMsg = channels.includes('会员通-发客户消息') || isCommunity;
  const momentsBox = document.getElementById('materialMoments');
  const msgBox = document.getElementById('materialMiniProgram');
  const momentsCommunityBox = document.getElementById('materialMomentsCommunity');
  const msgCommunityBox = document.getElementById('materialMiniProgramCommunity');
  const emptyTip = document.getElementById('materialEmptyTip');
  if(momentsBox) momentsBox.classList.toggle('hidden', !showMoments || isCommunity);
  if(msgBox) msgBox.classList.toggle('hidden', !showMsg || isCommunity);
  if(momentsCommunityBox) momentsCommunityBox.classList.toggle('hidden', !isCommunity);
  if(msgCommunityBox) msgCommunityBox.classList.toggle('hidden', !isCommunity);

  mirrorCommunityMaterialInputs();
  if(!showMoments){
    const chk = document.getElementById('moments_add_images');
    const file = document.getElementById('moments_images');
    const chkCommunity = document.getElementById('moments_add_images_community');
    const fileCommunity = document.getElementById('moments_images_community');
    if(chk) chk.checked = false;
    if(file) file.value = '';
    if(chkCommunity) chkCommunity.checked = false;
    if(fileCommunity) fileCommunity.value = '';
  }
  if(!showMsg){
    const chk = document.getElementById('msg_add_mini_program');
    const cover = document.getElementById('mini_program_cover');
    const chkCommunity = document.getElementById('msg_add_mini_program_community');
    const coverCommunity = document.getElementById('mini_program_cover_community');
    if(chk) chk.checked = false;
    if(cover) cover.value = '';
    if(chkCommunity) chkCommunity.checked = false;
    if(coverCommunity) coverCommunity.value = '';
  }
  if(emptyTip) emptyTip.style.display = (showMoments || showMsg) ? 'none' : 'block';
  saveUiPrefs();
}

function esc(s){
  return (s||"").replace(/[&<>"']/g, m => ({
    "&":"&amp;",
    "<":"&lt;",
    ">":"&gt;",
    '"':"&quot;",
    "'":"&#39;"
  }[m]));
}

async function upload(){
  if(uploading) return;
  const fileInput = document.getElementById('files');
  const files = fileInput.files;
  if(!files.length){
    // 更顺手：未选文件时直接拉起文件选择框，而不是报错中断
    fileInput.click();
    return;
  }
  uploading = true;
  fileInput.disabled = true;
  const fd = new FormData();
  for(const f of files){ fd.append('files', f); }
  // 系统默认复用已登录浏览器（固定开启）
  fd.append('connect_cdp', 'true');
  fd.append('cdp_endpoint', document.getElementById('cdp_endpoint').value);
  // 严格第2步由文件/渠道预设逻辑处理（前端不再暴露开关）
  fd.append('strict_step2', 'true');
  fd.append('skip_step2', 'false');
  fd.append('concurrent', document.getElementById('concurrent').value || '1');
  fd.append('start', '');
  fd.append('end', '');
  fd.append('hold_seconds', document.getElementById('hold_seconds').value || '2');
  const channels = selectedChannels();
  // 允许不勾选页面渠道：优先使用任务文件内“第3步渠道(可多选)”字段
  fd.append('step3_channels', channels.join(','));
  fd.append('executor_include_franchise', document.getElementById('executor_include_franchise').checked ? 'true' : 'false');
  // 素材已迁移至任务列表“添加素材”，这里默认不携带全局素材
  fd.append('moments_add_images', 'false');
  const momentImgs = [];
  for(const img of momentImgs){ fd.append('moments_images', img); }
  // 上传门店是否生效由任务文件字段控制，这里不做全局强制
  fd.append('upload_stores', 'false');
  fd.append('msg_add_mini_program', 'false');
  saveUiPrefs();
  try{
    const r = await fetch('/api/tasks/upload', {method:'POST', body:fd});
    if(!r.ok){
      alert(await r.text());
    } else {
      await refreshTasks();
    }
  } finally {
    fileInput.value = '';
    fileInput.disabled = false;
    uploading = false;
  }
}

async function startExecute(){
  const r = await fetch('/api/tasks/start', {method:'POST'});
  if(!r.ok){ alert(await r.text()); return; }
  const data = await r.json();
  if(!data.count){
    alert('当前没有待执行任务。');
    return;
  }
  alert(`已开始执行 ${data.count} 个任务。`);
  await refreshTasks();
}

async function retryTask(id){
  await fetch('/api/tasks/' + id + '/retry', {method:'POST'});
  await refreshTasks();
}

async function pauseTask(id){
  const r = await fetch('/api/tasks/' + id + '/pause', {method:'POST'});
  if(!r.ok){ alert(await r.text()); return; }
  await refreshTasks();
}

async function resumeTask(id){
  const r = await fetch('/api/tasks/' + id + '/resume', {method:'POST'});
  if(!r.ok){ alert(await r.text()); return; }
  await refreshTasks();
}

async function deleteTask(id){
  if(!confirm('确认删除该任务？删除后不会执行。')) return;
  const r = await fetch('/api/tasks/' + id + '/delete', {method:'POST'});
  if(!r.ok){ alert(await r.text()); return; }
  selectedTaskIds.delete(id);
  await refreshTasks();
}

async function retryFailed(){
  await fetch('/api/tasks/retry-failed', {method:'POST'});
  await refreshTasks();
}

async function batchPauseSelected(){
  const ids = Array.from(selectedTaskIds);
  if(!ids.length){ alert('请先勾选任务'); return; }
  const r = await fetch('/api/tasks/pause-batch', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(ids),
  });
  if(!r.ok){ alert(await r.text()); return; }
  const data = await r.json();
  alert(`批量暂停完成：成功 ${data.changed || 0}，忽略 ${data.ignored || 0}`);
  await refreshTasks();
}

async function batchDeleteSelected(){
  const ids = Array.from(selectedTaskIds);
  if(!ids.length){ alert('请先勾选任务'); return; }
  if(!confirm(`确认删除已选 ${ids.length} 个任务？删除后不会执行。`)) return;
  const r = await fetch('/api/tasks/delete-batch', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(ids),
  });
  if(!r.ok){ alert(await r.text()); return; }
  const data = await r.json();
  alert(`批量删除完成：成功 ${data.changed || 0}，忽略 ${data.ignored || 0}`);
  selectedTaskIds.clear();
  await refreshTasks();
}

function fmtStatus(s){return '<span class="status-'+s+'">'+s+'</span>';}

function renderFileLink(task){
  return `<a class="link-pill" href="/api/tasks/${task.id}/file">下载CSV</a>`;
}

function updateBatchInfo(){
  const n = selectedTaskIds.size;
  const el = document.getElementById('batchInfo');
  if(el) el.textContent = `已选 ${n} 项`;
  const all = document.getElementById('selectAllTasks');
  if(all){
    const boxes = Array.from(document.querySelectorAll('.task-select'));
    all.checked = boxes.length > 0 && boxes.every(b => b.checked);
  }
}

function toggleTaskSelection(id, checked){
  if(checked) selectedTaskIds.add(id);
  else selectedTaskIds.delete(id);
  updateBatchInfo();
}

function toggleSelectAllTasks(checked){
  document.querySelectorAll('.task-select').forEach(el => {
    el.checked = checked;
    const id = el.getAttribute('data-id');
    if(!id) return;
    if(checked) selectedTaskIds.add(id);
    else selectedTaskIds.delete(id);
  });
  updateBatchInfo();
}

function _statusText(t){
  if(t.paused && t.status === 'pending') return 'paused';
  return t.status;
}

function renderTasks(rows){
  const visibleIds = new Set(rows.map(r => r.id));
  selectedTaskIds = new Set(Array.from(selectedTaskIds).filter(id => visibleIds.has(id)));
  const tbody = document.getElementById('taskRows');
  tbody.innerHTML = rows.map(t => `
    <tr>
      <td class="check-col"><input class="task-select" data-id="${t.id}" type="checkbox" ${selectedTaskIds.has(t.id) ? 'checked' : ''} onchange="toggleTaskSelection('${t.id}', this.checked)"/></td>
      <td><div class="file-hero">${esc(t.filename)}</div><div style="margin-top:4px">${renderFileLink(t)}</div></td>
      <td>${esc(t.plan_name || '-')}</td>
      <td>${esc(t.send_channels || '-')}</td>
      <td>${fmtStatus(_statusText(t))}</td>
      <td>${t.completed_plans}/${t.total_plans || '-'}</td>
      <td>${t.success_count}/${t.fail_count}</td>
      <td>${esc(t.started_at || '-')}</td>
      <td>${esc(t.ended_at || '-')}</td>
      <td>${t.duration_sec ? t.duration_sec.toFixed(1) : '-'}</td>
      <td>
        <button onclick="openLogModal('${t.id}')">日志</button>
        <button class="secondary" onclick="openMaterialModal('${t.id}')">添加素材</button>
        ${t.status === 'running' ? '' : (t.paused && t.status === 'pending' ? `<button class="secondary" onclick="resumeTask('${t.id}')">恢复</button>` : `<button class="secondary" onclick="pauseTask('${t.id}')">暂停</button>`)}
        ${t.status === 'running' ? '' : `<button class="secondary" onclick="deleteTask('${t.id}')">删除</button>`}
        ${t.status === 'failed' ? `<button class="secondary" onclick="retryTask('${t.id}')">重试</button>` : ''}
      </td>
    </tr>
  `).join('');
  updateBatchInfo();
}

async function refreshTasks(){
  let rows = [];
  try{
    const r = await fetch('/api/tasks');
    const data = await r.json();
    rows = data.tasks || [];
    saveLocal(LS_KEYS.tasks, rows);
  }catch(_){
    rows = loadLocal(LS_KEYS.tasks, []);
  }
  if(!selectedTaskId){
    const running = rows.find(t => t.status === 'running');
    if(running){
      selectedTaskId = running.id;
      saveLocal(LS_KEYS.selectedTaskId, selectedTaskId);
      logOffset = 0;
      document.getElementById('logs').textContent = "";
      document.getElementById('logTitle').textContent = `任务 ${running.filename} (${running.status})`;
      saveLocal(LS_KEYS.logsText, "");
      saveLocal(LS_KEYS.logsTitle, document.getElementById('logTitle').textContent);
    }
  }else{
    const exists = rows.some(t => t.id === selectedTaskId);
    if(!exists){
      selectedTaskId = "";
      logOffset = 0;
      saveLocal(LS_KEYS.selectedTaskId, "");
      document.getElementById('logTitle').textContent = '任务不存在（可能服务重启），请重新选择';
    }
  }
  renderTasks(rows);
}

function openLogModal(id){
  const m = document.getElementById('logModal');
  if(m) m.classList.add('open');
  return selectTask(id);
}

function closeLogModal(evt){
  if(evt && evt.target && evt.target.id !== 'logModal') return;
  const m = document.getElementById('logModal');
  if(m) m.classList.remove('open');
}

function _channelList(raw){
  return String(raw || '').split(/[|,，、/]/).map(s => s.trim()).filter(Boolean);
}

function _supportMini(channels){
  const s = new Set(_channelList(channels));
  return s.has('会员通-发客户消息') || s.has('会员通-发送社群');
}

function _supportMoments(channels){
  const s = new Set(_channelList(channels));
  return s.has('会员通-发客户朋友圈') || s.has('会员通-发送社群');
}

function closeMaterialModal(evt){
  if(evt && evt.target && evt.target.id !== 'materialModal') return;
  const m = document.getElementById('materialModal');
  if(m) m.classList.remove('open');
}

function _renderMaterialPreviews(row, idx){
  const box = row.querySelector(`.img-preview[data-kind="moments"][data-idx="${idx}"]`);
  if(!box) return;
  box.innerHTML = '';
  (materialPlans[idx]?.moment_tokens || []).forEach(tok => {
    const f = materialFileMap.get(tok);
    if(!f) return;
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.alt = f.name;
    box.appendChild(img);
  });
}

function renderMaterialRows(){
  const root = document.getElementById('materialRows');
  if(!root) return;
  if(!materialPlans.length){
    root.innerHTML = '<div class="tiny">当前任务没有可配置计划行。</div>';
    return;
  }
  root.innerHTML = materialPlans.map(p => {
    const mini = _supportMini(p.channels);
    const moments = _supportMoments(p.channels);
    const idx = p.index;
    const chips = (p.moments_image_paths || '').split('|').filter(Boolean).map(x => `<span class="path-chip">${esc(x.split('/').pop())}</span>`).join('');
    return `
      <div class="material-row" data-idx="${idx}">
        <h4>计划${idx + 1}：${esc(p.name)} <span class="tiny">（渠道：${esc(p.channels || '-')}）</span></h4>
        <div class="material-grid">
          <div>
            <label class="inline-check ${mini ? '' : 'hidden'}"><input type="checkbox" data-kind="mini" data-idx="${idx}" ${p.msg_add_mini_program ? 'checked' : ''}/> 添加小程序卡片</label>
            <div class="${mini ? '' : 'hidden'}" style="margin-top:6px">
              <input type="file" data-kind="mini-cover" data-idx="${idx}" accept=".jpg,.jpeg,.png"/>
              ${p.msg_mini_program_cover_path ? `<div class="tiny" style="margin-top:4px">当前封面：${esc(p.msg_mini_program_cover_path.split('/').pop())}</div>` : ''}
            </div>
          </div>
          <div>
            <label class="inline-check ${moments ? '' : 'hidden'}"><input type="checkbox" data-kind="moments" data-idx="${idx}" ${p.moments_add_images ? 'checked' : ''}/> 启用图片上传</label>
            <div class="${moments ? '' : 'hidden'}" style="margin-top:6px">
              <input type="file" data-kind="moments-files" data-idx="${idx}" multiple accept=".jpg,.jpeg,.png"/>
              <div class="img-preview" data-kind="moments" data-idx="${idx}"></div>
              ${chips ? `<div style="margin-top:4px">${chips}</div>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');

  root.querySelectorAll('input[data-kind="mini"]').forEach(el => {
    el.addEventListener('change', (e) => {
      const idx = Number(e.target.dataset.idx);
      materialPlans[idx].msg_add_mini_program = !!e.target.checked;
    });
  });
  root.querySelectorAll('input[data-kind="moments"]').forEach(el => {
    el.addEventListener('change', (e) => {
      const idx = Number(e.target.dataset.idx);
      materialPlans[idx].moments_add_images = !!e.target.checked;
    });
  });
  root.querySelectorAll('input[data-kind="mini-cover"]').forEach(el => {
    el.addEventListener('change', (e) => {
      const idx = Number(e.target.dataset.idx);
      const f = e.target.files && e.target.files[0];
      if(!f) return;
      const token = `cover_${Date.now()}_${++materialTokenSeq}_${idx}`;
      materialFileMap.set(token, f);
      materialPlans[idx].cover_token = token;
    });
  });
  root.querySelectorAll('input[data-kind="moments-files"]').forEach(el => {
    el.addEventListener('change', (e) => {
      const idx = Number(e.target.dataset.idx);
      const list = Array.from(e.target.files || []);
      const tokens = [];
      list.forEach((f, i) => {
        const token = `mom_${Date.now()}_${++materialTokenSeq}_${idx}_${i}`;
        materialFileMap.set(token, f);
        tokens.push(token);
      });
      materialPlans[idx].moment_tokens = tokens;
      _renderMaterialPreviews(el.closest('.material-row'), idx);
    });
  });
}

async function openMaterialModal(id){
  materialTaskId = id;
  materialFileMap.clear();
  const resp = await fetch('/api/tasks/' + id + '/plans');
  if(!resp.ok){ alert('获取计划列表失败'); return; }
  const data = await resp.json();
  materialPlans = (data.plans || []).map(p => ({
    index: Number(p.index),
    name: p.name || '',
    channels: p.channels || '',
    msg_add_mini_program: !!p.msg_add_mini_program,
    moments_add_images: !!p.moments_add_images,
    msg_mini_program_cover_path: p.msg_mini_program_cover_path || '',
    moments_image_paths: p.moments_image_paths || '',
    cover_token: '',
    moment_tokens: []
  }));
  document.getElementById('materialTitle').textContent = `按计划添加素材（任务 ${id.slice(0,8)}）`;
  renderMaterialRows();
  const m = document.getElementById('materialModal');
  if(m) m.classList.add('open');
}

async function saveTaskMaterials(){
  if(!materialTaskId){ return; }
  const specs = materialPlans.map(p => ({
    index: p.index,
    msg_add_mini_program: !!p.msg_add_mini_program,
    moments_add_images: !!p.moments_add_images,
    cover_token: p.cover_token || '',
    moment_tokens: p.moment_tokens || [],
  }));
  const fd = new FormData();
  fd.append('specs_json', JSON.stringify(specs));
  materialFileMap.forEach((file, token) => {
    fd.append('files', file, token);
  });
  const resp = await fetch(`/api/tasks/${materialTaskId}/materials`, {method:'POST', body:fd});
  if(!resp.ok){
    alert(await resp.text());
    return;
  }
  alert('素材已保存，可直接重试该任务执行。');
  closeMaterialModal();
}

async function selectTask(id){
  selectedTaskId = id;
  saveLocal(LS_KEYS.selectedTaskId, selectedTaskId);
  logOffset = 0;
  document.getElementById('logs').textContent = "";
  const resp = await fetch('/api/tasks/' + id);
  if(resp.status === 404){
    selectedTaskId = "";
    saveLocal(LS_KEYS.selectedTaskId, "");
    document.getElementById('logTitle').textContent = '任务不存在（可能服务重启），请重新选择';
    return;
  }
  const t = await resp.json();
  document.getElementById('logTitle').textContent = `任务 ${t.filename} (${t.status})`;
  saveLocal(LS_KEYS.logsTitle, document.getElementById('logTitle').textContent);
  saveLocal(LS_KEYS.logsText, "");
  await pollLogs(true);
}

async function pollLogs(reset=false){
  if(!selectedTaskId) return;
  const r = await fetch(`/api/tasks/${selectedTaskId}/logs?offset=${logOffset}&limit=500`);
  if(r.status === 404){
    selectedTaskId = "";
    logOffset = 0;
    saveLocal(LS_KEYS.selectedTaskId, "");
    document.getElementById('logTitle').textContent = '任务不存在（可能服务重启），已清除旧任务选择';
    return;
  }
  const data = await r.json();
  const logs = data.logs || [];
  if(logs.length){
    const box = document.getElementById('logs');
    box.textContent += logs.join("\\n") + "\\n";
    box.scrollTop = box.scrollHeight;
    logOffset = data.next_offset || (logOffset + logs.length);
    saveLocal(LS_KEYS.logsText, box.textContent);
    saveLocal(LS_KEYS.logsTitle, document.getElementById('logTitle').textContent);
  }
}

function saveUiPrefs(){
  const momentsChecked = !!document.getElementById('moments_add_images')?.checked || !!document.getElementById('moments_add_images_community')?.checked;
  const miniProgramChecked = !!document.getElementById('msg_add_mini_program')?.checked || !!document.getElementById('msg_add_mini_program_community')?.checked;
  const prefs = {
    cdp_endpoint: document.getElementById('cdp_endpoint')?.value || '',
    concurrent: document.getElementById('concurrent')?.value || '1',
    hold_seconds: document.getElementById('hold_seconds')?.value || '2',
    channels: selectedChannels(),
    executor_include_franchise: !!document.getElementById('executor_include_franchise')?.checked,
    moments_add_images: momentsChecked,
    msg_add_mini_program: miniProgramChecked,
    advanced_open: document.getElementById('advancedConfig')?.classList.contains('open') || false,
  };
  saveLocal(LS_KEYS.prefs, prefs);
}

function restoreUiFromCache(){
  const prefs = loadLocal(LS_KEYS.prefs, null);
  if(prefs){
    if(document.getElementById('cdp_endpoint')) document.getElementById('cdp_endpoint').value = prefs.cdp_endpoint || 'http://127.0.0.1:18800';
    if(document.getElementById('concurrent')) document.getElementById('concurrent').value = prefs.concurrent || '1';
    if(document.getElementById('hold_seconds')) document.getElementById('hold_seconds').value = prefs.hold_seconds || '2';
    const channels = new Set(prefs.channels || []);
    document.querySelectorAll('.step3_channel').forEach(el => { el.checked = channels.has(el.value); });
    if(document.getElementById('executor_include_franchise')) document.getElementById('executor_include_franchise').checked = !!prefs.executor_include_franchise;
    if(document.getElementById('moments_add_images')) document.getElementById('moments_add_images').checked = !!prefs.moments_add_images;
    if(document.getElementById('msg_add_mini_program')) document.getElementById('msg_add_mini_program').checked = !!prefs.msg_add_mini_program;
    if(prefs.advanced_open){
      const panel = document.getElementById('advancedConfig');
      const btn = document.getElementById('advToggleBtn');
      if(panel) panel.classList.add('open');
      if(btn) btn.textContent = '高级配置（收起）';
    }
  }
  setThemeMode('light', false);
  const cachedRows = loadLocal(LS_KEYS.tasks, []);
  if(cachedRows.length){
    renderTasks(cachedRows);
  }
  const cachedSelected = loadLocal(LS_KEYS.selectedTaskId, '');
  if(cachedSelected){
    selectedTaskId = cachedSelected;
  }
  const cachedTitle = loadLocal(LS_KEYS.logsTitle, '未选中任务');
  const cachedLogs = loadLocal(LS_KEYS.logsText, '');
  document.getElementById('logTitle').textContent = cachedTitle;
  document.getElementById('logs').textContent = cachedLogs;
}

setInterval(async ()=>{ await refreshTasks(); await pollLogs(); }, 2000);
document.querySelectorAll('.step3_channel').forEach(el => el.addEventListener('change', syncChannelMaterials));
const filesEl = document.getElementById('files');
if(filesEl){
  filesEl.addEventListener('change', () => {
    if(filesEl.files && filesEl.files.length){
      upload();
    }
  });
}
['cdp_endpoint','concurrent','hold_seconds','executor_include_franchise','moments_add_images','msg_add_mini_program']
  .forEach(id => {
    const el = document.getElementById(id);
    if(el){ el.addEventListener('change', saveUiPrefs); el.addEventListener('input', saveUiPrefs); }
  });
document.querySelectorAll('.theme-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.getAttribute('data-mode') || 'light';
    setThemeMode(mode, true);
  });
});
[['moments_add_images_community','moments_add_images'], ['msg_add_mini_program_community','msg_add_mini_program']].forEach(([fromId, toId]) => {
  const from = document.getElementById(fromId);
  const to = document.getElementById(toId);
  if(from && to){
    from.addEventListener('change', () => { to.checked = !!from.checked; saveUiPrefs(); });
    to.addEventListener('change', () => { from.checked = !!to.checked; saveUiPrefs(); });
  }
});
['moments_images_community','mini_program_cover_community'].forEach(id => {
  const el = document.getElementById(id);
  if(el){ el.addEventListener('change', saveUiPrefs); }
});
restoreUiFromCache();
syncChannelMaterials();
refreshTasks();
</script>
</body>
</html>
"""
