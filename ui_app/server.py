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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
    "use_recommend": "推荐算法",
    "start_time": "计划开始时间",
    "end_time": "计划结束时间",
    "trigger_type": "触发方式",
    "send_time": "发送时间",
    "global_limit": "全局触达限制",
    "set_target": "是否设置目标",
    "create_url": "创建链接",
    "group_name": "分群名称",
    "update_type": "更新方式",
    "main_operating_area": "主消费营运区",
    "main_store_file_path": "主消费门店文件路径",
    "step2_store_file_path": "第2步门店信息文件路径",
    "step2_product_file_path": "第2步商品编码文件路径",
    "coupon_ids": "券规则ID",
    "sms_content": "短信内容",
    "step3_end_time": "第3步结束时间",
    "distribution_mode": "分配方式",
    "executor_employees": "执行员工",
    "send_content": "发送内容",
    "group_send_name": "下发群名",
    "channels": "第3步渠道(可多选)",
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
TEMPLATE_HIDE_FIELDS = {
    "group_name",
    "channels",
    "moments_add_images",
    "moments_image_paths",
    "upload_stores",
    "store_file_path",
    "main_store_file_path",
    "step2_store_file_path",
    "step2_product_file_path",
    "msg_add_mini_program",
    "msg_mini_program_cover_path",
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
        "use_recommend",
        "start_time",
        "end_time",
        "trigger_type",
        "send_time",
        "global_limit",
        "set_target",
        "create_url",
        "group_name",
        "update_type",
        "main_operating_area",
        "main_store_file_path",
        "step2_store_file_path",
        "step2_product_file_path",
        "coupon_ids",
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
    # 业务引导示例：第2步主消费营运区支持多区域填写
    if "main_operating_area" in out_headers:
        idx = out_headers.index("main_operating_area")
        out_sample[idx] = "辽宁省区、九江、南昌、广州二"
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
    ws_store = wb.create_sheet("目标门店")
    ws_store.append(["门店编码", "大区", "省区", "营运区", "片区", "门店"])
    ws_store.append(["1001010022", "华南大区", "广佛省区", "广州一", "张惠敏", "00022店广州泰沙"])
    ws_product = wb.create_sheet("目标商品")
    ws_product.append(["商品编码", "大类", "中类", "小类", "商品名"])
    ws_product.append(["1010002", "RX", "心脑血管用药", "高血压用药", "硝苯地平片"])
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
        "分配方式", "执行员工", "下发群名", "发送内容", "第3步渠道(可多选)", "创建链接",
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
    ws_store = wb.create_sheet("目标门店")
    ws_store.append(["门店编码"])
    ws_store.append(["2000081179"])
    ws_product = wb.create_sheet("目标商品")
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
        normalized = [HEADER_CN_TO_EN.get(h, h) for h in raw_headers]
        if normalized == raw_headers:
            return
        rows[0] = normalized
        with dst_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    except Exception:
        # 不阻断上传；后续由脚本校验字段
        return


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


def convert_uploaded_xlsx_multi_sheet(
    upload: UploadFile, dst_csv: Path
) -> Tuple[Optional[Tuple[str, bytes]], Optional[Tuple[str, bytes]]]:
    """
    一个Excel多sheet模式：
    - 任务文件sheet -> 转CSV
    - 目标门店sheet -> 返回xlsx blob
    - 目标商品sheet -> 返回xlsx blob
    """
    if load_workbook is None:
        raise HTTPException(status_code=500, detail="Server missing openpyxl. Please install requirements-ui.txt")
    upload.file.seek(0)
    wb = load_workbook(upload.file, read_only=True, data_only=True)
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
    if store_sheet:
        store_blob = _sheet_to_xlsx_blob(store_sheet, wb[store_sheet])
    if product_sheet:
        product_blob = _sheet_to_xlsx_blob(product_sheet, wb[product_sheet])
    wb.close()
    return store_blob, product_blob

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

    ui_channels = step3_channels or ""
    for row in rows:
        row_channels = str(row.get("channels", "") or "").strip()
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

    ui_channels = step3_channels or ""
    for row in rows:
        row_channels = str(row.get("channels", "") or "").strip()
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

    ui_channels = step3_channels or ""
    for row in rows:
        row_channels = str(row.get("channels", "") or "").strip()
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
    ui_channels = step3_channels or ""
    for row in rows:
        row_channels = str(row.get("channels", "") or "").strip()
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
                c = (row.get("channels", "") or "").strip()
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
                channels = str(row.get("channels", "") or "").strip()
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
            if task.status != "pending":
                return False
            if task.queued:
                return False
            task.queued = True
        await self.queue.put(task_id)
        return True

    async def retry_task(self, task_id: str) -> Task:
        async with self.lock:
            old = self.tasks.get(task_id)
            if not old:
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
            ids = [tid for tid, t in self.tasks.items() if t.status == "pending" and not t.queued]
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
            failed_ids = [tid for tid, t in self.tasks.items() if t.status == "failed"]
        new_ids = []
        for tid in failed_ids:
            t = await self.retry_task(tid)
            new_ids.append(t.id)
        return new_ids

    async def list_tasks(self) -> List[dict]:
        async with self.lock:
            tasks = list(self.tasks.values())
        tasks.sort(key=lambda x: x.created_at, reverse=True)
        return [t.to_dict() for t in tasks]

    async def get_task(self, task_id: str) -> Task:
        async with self.lock:
            t = self.tasks.get(task_id)
        if not t:
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
                task = await self.get_task(task_id)
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
        filename="精准营销任务模板（含目标门店与目标商品）.xlsx",
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
        if lower.endswith(".xlsx"):
            # 优先按“单Excel多sheet”读取；若无对应sheet则仅任务sheet生效
            ms_store_blob, ms_product_blob = convert_uploaded_xlsx_multi_sheet(f, dst)
            file_step2_store_blob = ms_store_blob
            file_step2_product_blob = ms_product_blob
        else:
            with dst.open("wb") as out:
                shutil.copyfileobj(f.file, out)
        normalize_uploaded_csv_headers(dst)
        normalize_community_create_url_in_csv(dst, options.step3_channels)
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
        plan_name_display, channel_display = summarize_csv_meta(dst)
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
        op = operator.strip() or os.getenv("USER") or getpass.getuser() or "unknown"
        task = Task(
            id=tid,
            filename=f.filename,
            file_path=str(dst),
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
    .channel-block{border:none;border-radius:0;background:transparent;padding:0;box-shadow:none}
    .channel-item{display:flex;align-items:center;gap:8px;padding:4px 0}
    .channel-item input{margin-top:2px}
    .channel-icon{font-size:16px}
    .channel-main{font-size:13px;color:#111827;font-weight:600;line-height:1.35}
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
  </style>
</head>
<body>
<div class="app-shell">
  <main class="main">
    <div>
      <div class="card">
        <h3 class="card-title">批量导入并执行（业务版）</h3>
        <div class="step-box compact">
          <div class="section-title"><span class="step-no">1</span>第1步：导入与基础配置</div>
          <div class="form-grid">
            <div class="field full upload-line file-hero">
              <span class="label">任务文件</span>
              <input id="files" class="file-uniform" type="file" multiple accept=".csv,.xlsx"/>
            </div>
            <div class="field full upload-actions">
              <button onclick="upload()">上传任务</button>
              <button id="advToggleBtn" type="button" class="adv-toggle text-link" onclick="toggleAdvancedConfig()">高级配置（展开）</button>
            </div>
            <div class="field full">
              <span class="label">模板下载</span>
              <div class="row">
                <a class="link-pill" href="/api/template/xlsx">下载Excel模板</a>
                <a class="link-pill" href="/api/template/csv">下载CSV模板(防乱码)</a>
                <a class="link-pill" href="/api/template/community-xlsx">下载社群专用模板</a>
              </div>
            </div>
          </div>
          <div id="advancedConfig" class="adv-panel">
            <div class="form-grid">
              <div class="field vertical">
                <label class="inline-check"><input id="connect_cdp" type="checkbox" checked/> 复用当前已登录浏览器</label>
                <span class="tiny">作用：复用你当前 Chrome 登录态，减少重复登录。</span>
              </div>
              <div class="field vertical">
                <label><span class="label">浏览器调试地址</span><input id="cdp_endpoint" value="http://127.0.0.1:18800" style="width:220px"/></label>
                <span class="tiny">作用：接管本地已登录浏览器（默认 127.0.0.1:18800）。</span>
              </div>
              <div class="field vertical">
                <label class="inline-check"><input id="strict_step2" type="checkbox" checked/> 严格校验第2步</label>
                <span class="tiny">作用：第2步关键字段失败时立即中断，避免脏数据提交。</span>
              </div>
              <div class="field vertical">
                <label><span class="label">并发任务数</span><input id="concurrent" type="number" min="1" value="1" style="width:88px"/></label>
                <span class="tiny">作用：同时执行的任务数。建议先用 1 验证稳定性。</span>
              </div>
              <div class="field vertical">
                <label><span class="label">保留浏览器(秒)</span><input id="hold_seconds" type="number" min="0" value="2" style="width:88px"/></label>
                <span class="tiny">作用：任务结束后页面停留时间，便于人工复核。</span>
              </div>
              <div class="field vertical">
                <label class="inline-check"><input id="executor_store_upload" type="checkbox" checked/> 执行员工-指定门店（默认开启）</label>
                <span class="tiny">作用：执行员工支持通过“目标门店”sheet自动上传门店并勾选节点。</span>
              </div>
              <div class="field vertical">
                <label class="inline-check channel-strong"><input id="executor_include_franchise" type="checkbox" checked/> 执行员工包含加盟区域（自动同步勾选“xx加盟”节点）</label>
                <span class="tiny">示例：执行员工=广佛省区，自动追加广佛省区加盟；执行员工=大郑州营运区，自动追加大郑州营运区加盟。</span>
              </div>
            </div>
          </div>
          <div class="step-caption">先上传 CSV/XLSX，再根据需要展开“高级配置”。</div>
        </div>

        <div class="step-box">
          <div class="section-title"><span class="step-no">2</span>第2步：选中发送渠道（可多选）</div>
          <div class="channel-grid">
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="短信"/>
                <span class="channel-icon">💬</span>
                <span><div class="channel-main">短信</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户消息"/>
                <span class="channel-icon">👥</span>
                <span><div class="channel-main">会员通-发客户消息</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发送社群"/>
                <span class="channel-icon">👥</span>
                <span><div class="channel-main">会员通-发送社群</div></span>
              </label>
            </div>
            <div class="channel-block">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户朋友圈"/>
                <span class="channel-icon">🖼️</span>
                <span><div class="channel-main">会员通-发客户朋友圈</div></span>
              </label>
            </div>
          </div>
          <div class="step-caption">素材配置请在任务列表中按计划点击“添加素材”进行设置。</div>
        </div>

        <div class="section-title">执行动作</div>
        <div class="actions primary-actions">
          <button onclick="startExecute()">开始执行</button>
          <button class="secondary" onclick="retryFailed()">一键重试失败任务</button>
        </div>
        <div class="tip" style="margin-top:8px">先“上传任务”让计划进入任务列表，再按计划“添加素材”，最后点击“开始执行”批量自动化创建。</div>
      </div>

      <div class="card">
        <h3 class="card-title">任务列表</h3>
        <table>
          <thead><tr>
            <th>文件</th><th>计划名称</th><th>发送渠道</th><th>状态</th><th>进度</th><th>成功/失败</th><th>开始</th><th>完成</th><th>耗时(s)</th><th>操作</th>
          </tr></thead>
          <tbody id="taskRows"></tbody>
        </table>
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
const materialFileMap = new Map();
const LS_KEYS = {
  tasks: 'pm_ui_cached_tasks_v1',
  selectedTaskId: 'pm_ui_selected_task_id_v1',
  logsText: 'pm_ui_cached_logs_text_v1',
  logsTitle: 'pm_ui_cached_logs_title_v1',
  prefs: 'pm_ui_prefs_v1',
};

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
  // “执行员工-指定门店”控制第3步上传门店开关（默认开启）
  const executorStore = document.getElementById('executor_store_upload');
  const uploadStores = document.getElementById('upload_stores');
  if(executorStore && uploadStores){
    uploadStores.checked = !!executorStore.checked;
  }
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
  const files = document.getElementById('files').files;
  if(!files.length){ alert('请先选择CSV或XLSX文件'); return; }
  const fd = new FormData();
  for(const f of files){ fd.append('files', f); }
  fd.append('connect_cdp', document.getElementById('connect_cdp').checked ? 'true' : 'false');
  fd.append('cdp_endpoint', document.getElementById('cdp_endpoint').value);
  fd.append('strict_step2', document.getElementById('strict_step2').checked ? 'true' : 'false');
  fd.append('skip_step2', 'false');
  fd.append('concurrent', document.getElementById('concurrent').value || '1');
  fd.append('start', '');
  fd.append('end', '');
  fd.append('hold_seconds', document.getElementById('hold_seconds').value || '2');
  const channels = selectedChannels();
  if(!channels.length){ alert('请至少选择一个发送渠道'); return; }
  fd.append('step3_channels', channels.join(','));
  fd.append('executor_include_franchise', document.getElementById('executor_include_franchise').checked ? 'true' : 'false');
  // 素材已迁移至任务列表“添加素材”，这里默认不携带全局素材
  fd.append('moments_add_images', 'false');
  const momentImgs = [];
  for(const img of momentImgs){ fd.append('moments_images', img); }
  const uploadStoreEnabled = !!document.getElementById('executor_store_upload')?.checked;
  fd.append('upload_stores', uploadStoreEnabled ? 'true' : 'false');
  fd.append('msg_add_mini_program', 'false');
  saveUiPrefs();
  const r = await fetch('/api/tasks/upload', {method:'POST', body:fd});
  if(!r.ok){ alert(await r.text()); return; }
  alert('任务已上传到列表（待执行）。请先按需添加素材，再点击“开始执行”。');
  await refreshTasks();
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

async function retryFailed(){
  await fetch('/api/tasks/retry-failed', {method:'POST'});
  await refreshTasks();
}

function fmtStatus(s){return '<span class="status-'+s+'">'+s+'</span>';}

function renderFileLink(task){
  return `<a class="link-pill" href="/api/tasks/${task.id}/file">下载CSV</a>`;
}

function renderTasks(rows){
  const tbody = document.getElementById('taskRows');
  tbody.innerHTML = rows.map(t => `
    <tr>
      <td><div class="file-hero">${esc(t.filename)}</div><div style="margin-top:4px">${renderFileLink(t)}</div></td>
      <td>${esc(t.plan_name || '-')}</td>
      <td>${esc(t.send_channels || '-')}</td>
      <td>${fmtStatus(t.status)}</td>
      <td>${t.completed_plans}/${t.total_plans || '-'}</td>
      <td>${t.success_count}/${t.fail_count}</td>
      <td>${esc(t.started_at || '-')}</td>
      <td>${esc(t.ended_at || '-')}</td>
      <td>${t.duration_sec ? t.duration_sec.toFixed(1) : '-'}</td>
      <td>
        <button onclick="openLogModal('${t.id}')">日志</button>
        <button class="secondary" onclick="openMaterialModal('${t.id}')">添加素材</button>
        ${t.status === 'failed' ? `<button class="secondary" onclick="retryTask('${t.id}')">重试</button>` : ''}
      </td>
    </tr>
  `).join('');
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
    connect_cdp: !!document.getElementById('connect_cdp')?.checked,
    cdp_endpoint: document.getElementById('cdp_endpoint')?.value || '',
    strict_step2: !!document.getElementById('strict_step2')?.checked,
    concurrent: document.getElementById('concurrent')?.value || '1',
    hold_seconds: document.getElementById('hold_seconds')?.value || '2',
    channels: selectedChannels(),
    executor_include_franchise: !!document.getElementById('executor_include_franchise')?.checked,
    executor_store_upload: !!document.getElementById('executor_store_upload')?.checked,
    moments_add_images: momentsChecked,
    msg_add_mini_program: miniProgramChecked,
    advanced_open: document.getElementById('advancedConfig')?.classList.contains('open') || false
  };
  saveLocal(LS_KEYS.prefs, prefs);
}

function restoreUiFromCache(){
  const prefs = loadLocal(LS_KEYS.prefs, null);
  if(prefs){
    if(document.getElementById('connect_cdp')) document.getElementById('connect_cdp').checked = !!prefs.connect_cdp;
    if(document.getElementById('cdp_endpoint')) document.getElementById('cdp_endpoint').value = prefs.cdp_endpoint || 'http://127.0.0.1:18800';
    if(document.getElementById('strict_step2')) document.getElementById('strict_step2').checked = !!prefs.strict_step2;
    if(document.getElementById('concurrent')) document.getElementById('concurrent').value = prefs.concurrent || '1';
    if(document.getElementById('hold_seconds')) document.getElementById('hold_seconds').value = prefs.hold_seconds || '2';
    const channels = new Set(prefs.channels || []);
    document.querySelectorAll('.step3_channel').forEach(el => { el.checked = channels.has(el.value); });
    if(document.getElementById('executor_include_franchise')) document.getElementById('executor_include_franchise').checked = !!prefs.executor_include_franchise;
    if(document.getElementById('executor_store_upload')) document.getElementById('executor_store_upload').checked = (prefs.executor_store_upload !== false);
    if(document.getElementById('moments_add_images')) document.getElementById('moments_add_images').checked = !!prefs.moments_add_images;
    if(document.getElementById('msg_add_mini_program')) document.getElementById('msg_add_mini_program').checked = !!prefs.msg_add_mini_program;
    if(prefs.advanced_open){
      const panel = document.getElementById('advancedConfig');
      const btn = document.getElementById('advToggleBtn');
      if(panel) panel.classList.add('open');
      if(btn) btn.textContent = '高级配置（收起）';
    }
  }
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
['connect_cdp','cdp_endpoint','strict_step2','concurrent','hold_seconds','executor_include_franchise','executor_store_upload','moments_add_images','msg_add_mini_program']
  .forEach(id => {
    const el = document.getElementById(id);
    if(el){ el.addEventListener('change', saveUiPrefs); el.addEventListener('input', saveUiPrefs); }
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
