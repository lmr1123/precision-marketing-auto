import asyncio
import csv
import getpass
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

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
    "use_recommend": "推荐算法",
    "start_time": "计划开始时间",
    "end_time": "计划结束时间",
    "trigger_type": "触发方式",
    "send_time": "发送时间",
    "global_limit": "全局触达限制",
    "set_target": "是否设置目标",
    "group_name": "分群名称",
    "update_type": "更新方式",
    "main_operating_area": "主消费营运区",
    "coupon_ids": "券规则ID",
    "sms_content": "短信内容",
    "step3_end_time": "第3步结束时间",
    "executor_employees": "执行员工",
    "send_content": "发送内容",
    "channels": "第3步渠道(可多选)",
    "moments_add_images": "朋友圈是否上传图片",
    "moments_image_paths": "朋友圈图片路径(用|分隔)",
    "msg_add_mini_program": "会员通消息是否添加小程序",
    "msg_mini_program_name": "小程序名称",
    "msg_mini_program_title": "小程序标题",
    "msg_mini_program_cover_path": "小程序封面路径",
    "msg_mini_program_page_path": "小程序链接",
}
HEADER_CN_TO_EN: Dict[str, str] = {v: k for k, v in HEADER_EN_TO_CN.items()}
TEMPLATE_HIDE_FIELDS = {
    "group_name",
    "channels",
    "moments_add_images",
    "moments_image_paths",
    "msg_add_mini_program",
    "msg_mini_program_name",
    "msg_mini_program_title",
    "msg_mini_program_cover_path",
    "msg_mini_program_page_path",
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
        "use_recommend",
        "start_time",
        "end_time",
        "trigger_type",
        "send_time",
        "global_limit",
        "set_target",
        "group_name",
        "update_type",
        "main_operating_area",
        "coupon_ids",
        "sms_content",
        "step3_end_time",
        "executor_employees",
        "send_content",
        "channels",
        "moments_add_images",
        "moments_image_paths",
        "msg_add_mini_program",
        "msg_mini_program_name",
        "msg_mini_program_title",
        "msg_mini_program_cover_path",
        "msg_mini_program_page_path",
    ]


def load_template_headers_and_sample() -> tuple[List[str], List[str]]:
    if DEFAULT_DATA_CSV.exists():
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with DEFAULT_DATA_CSV.open("r", encoding=enc, newline="") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    if rows:
                        headers = [str(x or "").strip() for x in rows[0]]
                        sample = [str(x or "").strip() for x in (rows[1] if len(rows) > 1 else [""] * len(headers))]
                        if headers:
                            defaults = _default_headers()
                            missing = [h for h in defaults if h not in headers]
                            if missing:
                                headers = headers + missing
                                sample = sample + [""] * len(missing)
                            return headers, sample
            except Exception:
                continue
    headers = _default_headers()
    return headers, [""] * len(headers)


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
    ws.title = "plans"
    ws.append(cn_headers)
    ws.append(sample)
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
        if "会员通-发客户朋友圈" not in channel_scope:
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
    """将会员通-发客户消息的小程序配置回写到任务CSV。"""
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
        if "会员通-发客户消息" not in channel_scope:
            continue
        row["msg_add_mini_program"] = "是"
        row["msg_mini_program_name"] = program_name or "大参林健康"
        row["msg_mini_program_title"] = title or ""
        row["msg_mini_program_cover_path"] = cover_path or ""
        row["msg_mini_program_page_path"] = page_path or ""

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
            },
        }


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

    async def add_task(self, task: Task) -> None:
        async with self.lock:
            self.tasks[task.id] = task
        await self.queue.put(task.id)

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
        await self.queue.put(new_id)
        return new_task

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
        task.started_at = now_iso()
        task.error = ""
        task.logs = []
        await self.append_log(task, f"[worker-{worker_id}] task started: {task.filename}")

        cmd = [
            sys.executable,
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

        await self.append_log(task, f"$ {' '.join(cmd)}")
        started = datetime.now()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ROOT),
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


@app.get("/api/template/csv")
async def download_template_csv():
    p = UPLOAD_DIR / "precision_template_utf8_bom.csv"
    write_template_csv(p)
    return FileResponse(path=str(p), filename="精准营销导入模板_UTF8BOM.csv", media_type="text/csv")


@app.get("/api/template/xlsx")
async def download_template_xlsx():
    p = UPLOAD_DIR / "precision_template.xlsx"
    try:
        write_template_xlsx(p)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return FileResponse(
        path=str(p),
        filename="精准营销导入模板.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/tasks/upload")
async def upload_tasks(
    files: List[UploadFile] = File(...),
    moments_images: List[UploadFile] = File(default=[]),
    mini_program_cover: Optional[UploadFile] = File(default=None),
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
    moments_add_images: bool = Form(False),
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
        if not msg_mini_program_title.strip():
            raise HTTPException(status_code=400, detail="已勾选添加小程序，但未填写小程序标题")
        if not msg_mini_program_page_path.strip():
            raise HTTPException(status_code=400, detail="已勾选添加小程序，但未填写小程序功能页面")
        if mini_program_cover is None:
            raise HTTPException(status_code=400, detail="已勾选添加小程序，但未上传小程序封面")
        b = await mini_program_cover.read()
        if not b:
            raise HTTPException(status_code=400, detail="小程序封面文件为空")
        mini_cover_blob = (mini_program_cover.filename or "mini_cover.jpg", b)

    for f in files:
        lower = f.filename.lower()
        if not (lower.endswith(".csv") or lower.endswith(".xlsx")):
            raise HTTPException(status_code=400, detail=f"Only CSV/XLSX supported: {f.filename}")
        tid = str(uuid.uuid4())
        stem = Path(f.filename).stem
        dst = UPLOAD_DIR / f"{tid}_{stem}.csv"
        if lower.endswith(".xlsx"):
            convert_uploaded_xlsx_to_csv(f, dst)
        else:
            with dst.open("wb") as out:
                shutil.copyfileobj(f.file, out)
        normalize_uploaded_csv_headers(dst)
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
        op = operator.strip() or os.getenv("USER") or getpass.getuser() or "unknown"
        task = Task(id=tid, filename=f.filename, file_path=str(dst), options=options, operator=op)
        await runner.add_task(task)
        created.append(task.to_dict())
    return JSONResponse({"created": created})


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> JSONResponse:
    t = await runner.retry_task(task_id)
    return JSONResponse({"created": t.to_dict()})


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
      --bg:#f5f7fb;
      --card:#ffffff;
      --line:#e5e7eb;
      --text:#111827;
      --sub:#4b5563;
      --hint:#6b7280;
      --brand:#0f766e;
      --brand-dark:#0b5d57;
      --radius:10px;
      --control-h:36px;
      --font:14px;
    }
    body{font-family:"PingFang SC","Microsoft YaHei",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--text);font-size:var(--font)}
    .wrap{max-width:1480px;margin:18px auto;padding:0 16px}
    .layout{display:grid;grid-template-columns:1.5fr .5fr;gap:12px;align-items:start}
    .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}
    .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
    .section-title{font-size:14px;font-weight:700;color:#0f172a;margin:0 0 10px 0;display:flex;align-items:center;gap:8px}
    .step-no{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:999px;background:var(--brand);color:#fff;font-size:12px;font-weight:700}
    .step-box{border:1px solid #dbe5f3;box-shadow:0 1px 2px rgba(15,118,110,.06);border-radius:12px;padding:12px;background:#fff;margin-bottom:10px}
    .step-caption{font-size:12px;color:var(--hint);margin-top:6px;line-height:1.5}
    .form-grid{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:10px 12px}
    .form-grid .full{grid-column:1 / -1}
    .field{display:flex;align-items:center;gap:8px;min-height:40px}
    .field.between{justify-content:space-between}
    .field.vertical{flex-direction:column;align-items:flex-start}
    .label{min-width:96px;color:var(--sub);font-size:13px}
    .inline-check{display:inline-flex;align-items:center;gap:6px;color:var(--sub);font-size:13px}
    .field input[type="text"], .field input[type="number"], .field input:not([type]), .field select{
      height:var(--control-h);box-sizing:border-box;
    }
    .field input[type="file"]{padding:7px 8px;max-width:260px}
    .field.vertical .row{width:100%}
    .field.vertical .row label{display:flex;align-items:center;gap:6px;color:var(--sub);font-size:13px}
    .actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding-top:2px}
    .subcard{border:1px solid var(--line);background:#fbfcff;border-radius:10px;padding:10px 12px;margin-top:8px}
    .adv-toggle{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:8px;background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;cursor:pointer}
    .adv-panel{display:none;border:1px dashed #c7d2fe;background:#f8faff;border-radius:10px;padding:10px;margin-top:8px}
    .adv-panel.open{display:block}
    .tiny{font-size:12px;color:var(--hint)}
    .channel-grid{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:10px}
    .channel-item{display:flex;align-items:flex-start;gap:8px;border:1px solid #d1d5db;border-radius:10px;padding:10px;background:#fff}
    .channel-item input{margin-top:2px}
    .channel-main{font-size:13px;color:#111827;font-weight:600}
    .channel-desc{font-size:12px;color:#6b7280;margin-top:2px;line-height:1.45}
    .material-panel{border:1px solid #d9e2ec;background:#fcfdff;border-radius:10px;padding:10px}
    .material-title{font-size:13px;font-weight:600;color:#0f172a;margin-bottom:8px}
    .hidden{display:none !important}
    input,button,select{padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:13px}
    button{background:var(--brand);color:#fff;border:none;cursor:pointer;height:36px;padding:0 14px}
    button:hover{background:var(--brand-dark)}
    button.secondary{background:#374151}
    .tip{font-size:12px;color:var(--hint);line-height:1.55}
    .hint{font-size:12px;color:var(--hint);display:block}
    table{width:100%;border-collapse:collapse}
    th,td{border-bottom:1px solid var(--line);padding:8px;text-align:left;font-size:13px;vertical-align:top}
    th{background:#f9fafb;font-weight:600}
    .status-pending{color:#6b7280}
    .status-running{color:#2563eb}
    .status-success{color:#059669}
    .status-failed{color:#dc2626}
    #logs{background:#0b1020;color:#dbeafe;height:calc(100vh - 180px);overflow:auto;padding:10px;border-radius:8px;white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:12px}
    .right-sticky{position:sticky;top:12px}
    .link-pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#ecfeff;color:#0f766e;border:1px solid #a5f3fc;font-size:12px;text-decoration:none}
    @media (max-width: 1100px){
      .layout{grid-template-columns:1fr}
      #logs{height:360px}
      .right-sticky{position:static}
      .form-grid{grid-template-columns:1fr}
      .label{min-width:84px}
      .channel-grid{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
<div class="wrap">
  <div class="layout">
    <div>
      <div class="card">
        <h3 style="margin:0 0 10px 0">批量导入并执行（业务版）</h3>
        <div class="step-box">
          <div class="section-title"><span class="step-no">1</span>第1步：导入与基础配置</div>
          <div class="form-grid">
            <div class="field full between">
              <div class="row">
                <span class="label">任务文件</span>
                <input id="files" type="file" multiple accept=".csv,.xlsx"/>
              </div>
              <button id="advToggleBtn" type="button" class="adv-toggle" onclick="toggleAdvancedConfig()">高级配置（展开）</button>
            </div>
            <div class="field full">
              <span class="label">创建链接</span>
              <input id="create_url" type="text" style="width:min(860px,100%)" placeholder="可选：手动填写创建链接；不填则按渠道自动匹配"/>
            </div>
            <div class="field full">
              <span class="hint" id="create_url_hint">自动匹配：短信=599702746907561984；会员通-发客户消息=594094287227023360；会员通-发客户朋友圈=599702926159527936；短信+会员通-发客户消息=600035736992907264</span>
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
            </div>
          </div>
          <div class="step-caption">先上传 CSV/XLSX，再根据需要展开“高级配置”。</div>
        </div>

        <div class="step-box">
          <div class="section-title"><span class="step-no">2</span>第2步：选中发送渠道（可多选）</div>
          <div class="subcard">
            <div class="channel-grid">
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="短信"/>
                <span>
                  <div class="channel-main">短信</div>
                  <div class="channel-desc">填写短信内容。</div>
                </span>
              </label>
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户消息"/>
                <span>
                  <div class="channel-main">会员通-发客户消息</div>
                  <div class="channel-desc">填写结束时间、执行员工、发送内容，可选小程序。</div>
                </span>
              </label>
              <label class="channel-item">
                <input class="step3_channel" type="checkbox" value="会员通-发客户朋友圈"/>
                <span>
                  <div class="channel-main">会员通-发客户朋友圈</div>
                  <div class="channel-desc">填写结束时间、执行员工、发送内容，可选上传图片。</div>
                </span>
              </label>
            </div>
          </div>
          <div class="step-caption">可单选或多选。系统将只填选中渠道对应字段。</div>
        </div>

        <div class="step-box">
          <div class="section-title"><span class="step-no">3</span>第3步：上传素材（按渠道生效）</div>
          <div class="form-grid">
            <div id="materialMoments" class="field vertical hidden material-panel">
              <div class="material-title">朋友圈上传图片</div>
              <label class="inline-check"><input id="moments_add_images" type="checkbox"/> 启用图片上传（最多9张）</label>
              <input id="moments_images" type="file" multiple accept=".jpg,.jpeg,.png"/>
              <span class="tiny">仅当选择“会员通-发客户朋友圈”时展示。支持 jpg/png，单张小于 10MB，按上传顺序提交。</span>
            </div>
            <div id="materialMiniProgram" class="field vertical hidden material-panel">
              <div class="material-title">会员通消息-添加小程序</div>
              <label class="inline-check"><input id="msg_add_mini_program" type="checkbox"/> 启用小程序配置</label>
              <div class="row">
                <label><span class="label" style="min-width:42px">名称</span><input id="msg_mini_program_name" value="大参林健康" style="width:140px"/></label>
                <label><span class="label" style="min-width:42px">标题</span><input id="msg_mini_program_title" placeholder="请输入标题" style="width:190px"/></label>
              </div>
              <div class="row">
                <label><span class="label" style="min-width:42px">链接</span><input id="msg_mini_program_page_path" placeholder="请输入链接" style="width:190px"/></label>
                <label><span class="label" style="min-width:42px">封面</span><input id="mini_program_cover" type="file" accept=".jpg,.jpeg,.png"/></label>
              </div>
              <span class="tiny">仅当选择“会员通-发客户消息”时展示。启用后请完整填写标题、链接并上传封面。</span>
            </div>
          </div>
          <div id="materialEmptyTip" class="step-caption">当前渠道无需附加素材，直接执行即可。</div>
        </div>

        <div class="section-title">执行动作</div>
        <div class="actions">
          <button onclick="upload()">上传并开始执行</button>
          <button class="secondary" onclick="retryFailed()">一键重试失败任务</button>
          <a class="link-pill" href="/api/template/xlsx">下载Excel模板</a>
          <a class="link-pill" href="/api/template/csv">下载CSV模板(防乱码)</a>
        </div>
        <div class="tip" style="margin-top:8px">说明: 支持上传 CSV / XLSX。下载模板为中文表头，便于业务填写；上传时系统会自动识别中文表头并转换为脚本字段。营销主题支持多选，多个值请用“、/，/,/|”分隔（示例：其他、26年3月积分换券）。Windows Excel 如遇 CSV 乱码，请优先下载“Excel模板”或“CSV模板(UTF-8 BOM)”。如勾选“朋友圈上传图片”，请在本页面选择图片文件（最多9张，jpg/png且<10MB），系统会自动写入任务CSV并按顺序上传。如勾选“会员通消息-添加小程序”，请填写标题、链接并上传封面，系统会自动注入到对应渠道行。</div>
      </div>

      <div class="card">
        <h3 style="margin:0 0 8px 0">任务列表</h3>
        <table>
          <thead><tr>
            <th>文件</th><th>状态</th><th>进度</th><th>成功/失败</th><th>开始</th><th>完成</th><th>预计完成</th><th>耗时(s)</th><th>复核链接</th><th>操作</th>
          </tr></thead>
          <tbody id="taskRows"></tbody>
        </table>
      </div>
    </div>
    <div class="right-sticky">
      <div class="card">
        <h3 style="margin:0 0 8px 0">执行日志（实时）</h3>
        <div id="logTitle" style="margin-bottom:8px;color:#6b7280">未选中任务</div>
        <div id="logs"></div>
      </div>
    </div>
  </div>
</div>
<script>
let selectedTaskId = "";
let logOffset = 0;
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

function updateCreateUrlHint(){
  const channels = selectedChannels();
  const hintEl = document.getElementById('create_url_hint');
  if(!hintEl) return;
  const hasSms = channels.includes('短信');
  const hasMsg = channels.includes('会员通-发客户消息');
  const hasMoments = channels.includes('会员通-发客户朋友圈');
  if(hasSms && hasMsg){
    hintEl.textContent = '当前自动匹配链接：短信 + 会员通-发客户消息 -> useId=600035736992907264（如需可手动覆盖）';
    return;
  }
  if(hasSms && !hasMsg && !hasMoments){
    hintEl.textContent = '当前自动匹配链接：短信 -> useId=599702746907561984（如需可手动覆盖）';
    return;
  }
  if(hasMsg && !hasSms && !hasMoments){
    hintEl.textContent = '当前自动匹配链接：会员通-发客户消息 -> useId=594094287227023360（如需可手动覆盖）';
    return;
  }
  if(hasMoments && !hasSms && !hasMsg){
    hintEl.textContent = '当前自动匹配链接：会员通-发客户朋友圈 -> useId=599702926159527936（如需可手动覆盖）';
    return;
  }
  hintEl.textContent = '自动匹配：短信=599702746907561984；会员通-发客户消息=594094287227023360；会员通-发客户朋友圈=599702926159527936；短信+会员通-发客户消息=600035736992907264';
}

function syncChannelMaterials(){
  const channels = selectedChannels();
  const showMoments = channels.includes('会员通-发客户朋友圈');
  const showMsg = channels.includes('会员通-发客户消息');
  const momentsBox = document.getElementById('materialMoments');
  const msgBox = document.getElementById('materialMiniProgram');
  const emptyTip = document.getElementById('materialEmptyTip');
  if(momentsBox) momentsBox.classList.toggle('hidden', !showMoments);
  if(msgBox) msgBox.classList.toggle('hidden', !showMsg);
  if(!showMoments){
    const chk = document.getElementById('moments_add_images');
    const file = document.getElementById('moments_images');
    if(chk) chk.checked = false;
    if(file) file.value = '';
  }
  if(!showMsg){
    const chk = document.getElementById('msg_add_mini_program');
    const title = document.getElementById('msg_mini_program_title');
    const page = document.getElementById('msg_mini_program_page_path');
    const cover = document.getElementById('mini_program_cover');
    if(chk) chk.checked = false;
    if(title) title.value = '';
    if(page) page.value = '';
    if(cover) cover.value = '';
  }
  if(emptyTip) emptyTip.style.display = (showMoments || showMsg) ? 'none' : 'block';
  updateCreateUrlHint();
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
  fd.append('create_url', document.getElementById('create_url').value || '');
  const channels = selectedChannels();
  if(!channels.length){ alert('请至少选择一个发送渠道'); return; }
  fd.append('step3_channels', channels.join(','));
  fd.append('moments_add_images', document.getElementById('moments_add_images').checked ? 'true' : 'false');
  const momentImgs = document.getElementById('moments_images').files;
  for(const img of momentImgs){ fd.append('moments_images', img); }
  fd.append('msg_add_mini_program', document.getElementById('msg_add_mini_program').checked ? 'true' : 'false');
  fd.append('msg_mini_program_name', document.getElementById('msg_mini_program_name').value || '大参林健康');
  fd.append('msg_mini_program_title', document.getElementById('msg_mini_program_title').value || '');
  fd.append('msg_mini_program_page_path', document.getElementById('msg_mini_program_page_path').value || '');
  const miniCover = document.getElementById('mini_program_cover').files[0];
  if(miniCover){ fd.append('mini_program_cover', miniCover); }
  saveUiPrefs();
  const r = await fetch('/api/tasks/upload', {method:'POST', body:fd});
  if(!r.ok){ alert(await r.text()); return; }
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

function renderReviewLink(task){
  if(task.latest_link){
    const label = (task.latest_link.includes('#/marketingPlan/viewPlan?') || task.latest_link.includes('#/marketingPlan/editPlan?'))
      ? '打开复核页' : '打开生成页';
    return `<a class="link-pill" href="${task.latest_link}" target="_blank">${label}</a>`;
  }
  return '<span class="hint">待生成</span>';
}

function renderFileLink(task){
  return `<a class="link-pill" href="/api/tasks/${task.id}/file">下载CSV</a>`;
}

function renderTasks(rows){
  const tbody = document.getElementById('taskRows');
  tbody.innerHTML = rows.map(t => `
    <tr>
      <td>${esc(t.filename)}<div style="margin-top:4px">${renderFileLink(t)}</div></td>
      <td>${fmtStatus(t.status)}</td>
      <td>${t.completed_plans}/${t.total_plans || '-'}</td>
      <td>${t.success_count}/${t.fail_count}</td>
      <td>${esc(t.started_at || '-')}</td>
      <td>${esc(t.ended_at || '-')}</td>
      <td>${esc(t.eta || '-')}</td>
      <td>${t.duration_sec ? t.duration_sec.toFixed(1) : '-'}</td>
      <td>${renderReviewLink(t)}</td>
      <td>
        <button onclick="selectTask('${t.id}')">日志</button>
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
  const prefs = {
    connect_cdp: !!document.getElementById('connect_cdp')?.checked,
    cdp_endpoint: document.getElementById('cdp_endpoint')?.value || '',
    strict_step2: !!document.getElementById('strict_step2')?.checked,
    concurrent: document.getElementById('concurrent')?.value || '1',
    hold_seconds: document.getElementById('hold_seconds')?.value || '2',
    create_url: document.getElementById('create_url')?.value || '',
    channels: selectedChannels(),
    moments_add_images: !!document.getElementById('moments_add_images')?.checked,
    msg_add_mini_program: !!document.getElementById('msg_add_mini_program')?.checked,
    msg_mini_program_name: document.getElementById('msg_mini_program_name')?.value || '大参林健康',
    msg_mini_program_title: document.getElementById('msg_mini_program_title')?.value || '',
    msg_mini_program_page_path: document.getElementById('msg_mini_program_page_path')?.value || '',
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
    if(document.getElementById('create_url')) document.getElementById('create_url').value = prefs.create_url || '';
    const channels = new Set(prefs.channels || []);
    document.querySelectorAll('.step3_channel').forEach(el => { el.checked = channels.has(el.value); });
    if(document.getElementById('moments_add_images')) document.getElementById('moments_add_images').checked = !!prefs.moments_add_images;
    if(document.getElementById('msg_add_mini_program')) document.getElementById('msg_add_mini_program').checked = !!prefs.msg_add_mini_program;
    if(document.getElementById('msg_mini_program_name')) document.getElementById('msg_mini_program_name').value = prefs.msg_mini_program_name || '大参林健康';
    if(document.getElementById('msg_mini_program_title')) document.getElementById('msg_mini_program_title').value = prefs.msg_mini_program_title || '';
    if(document.getElementById('msg_mini_program_page_path')) document.getElementById('msg_mini_program_page_path').value = prefs.msg_mini_program_page_path || '';
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
['connect_cdp','cdp_endpoint','strict_step2','concurrent','hold_seconds','create_url','moments_add_images','msg_add_mini_program','msg_mini_program_name','msg_mini_program_title','msg_mini_program_page_path']
  .forEach(id => {
    const el = document.getElementById(id);
    if(el){ el.addEventListener('change', saveUiPrefs); el.addEventListener('input', saveUiPrefs); }
  });
restoreUiFromCache();
syncChannelMaterials();
refreshTasks();
</script>
</body>
</html>
"""
