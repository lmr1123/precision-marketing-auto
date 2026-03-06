import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "precision-auto-playwright-batch.py"
UPLOAD_DIR = ROOT / "ui_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_int(val: str, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


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


@dataclass
class Task:
    id: str
    filename: str
    file_path: str
    options: TaskOptions
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "file_path": self.file_path,
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
            "options": {
                "connect_cdp": self.options.connect_cdp,
                "cdp_endpoint": self.options.cdp_endpoint,
                "strict_step2": self.options.strict_step2,
                "skip_step2": self.options.skip_step2,
                "concurrent": self.options.concurrent,
                "start": self.options.start,
                "end": self.options.end,
                "hold_seconds": self.options.hold_seconds,
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
        self._update_eta(task)

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


@app.post("/api/tasks/upload")
async def upload_tasks(
    files: List[UploadFile] = File(...),
    connect_cdp: bool = Form(True),
    cdp_endpoint: str = Form("http://127.0.0.1:18800"),
    strict_step2: bool = Form(True),
    skip_step2: bool = Form(False),
    concurrent: int = Form(1),
    start: str = Form(""),
    end: str = Form(""),
    hold_seconds: int = Form(2),
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
    )
    for f in files:
        if not f.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail=f"Only CSV supported: {f.filename}")
        tid = str(uuid.uuid4())
        dst = UPLOAD_DIR / f"{tid}_{Path(f.filename).name}"
        with dst.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        task = Task(id=tid, filename=f.filename, file_path=str(dst), options=options)
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
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f5f7fb;color:#1f2937}
    .wrap{max-width:1280px;margin:20px auto;padding:0 16px}
    .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin-bottom:12px}
    .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
    input,button,select{padding:8px 10px;border:1px solid #d1d5db;border-radius:8px}
    button{background:#0f766e;color:#fff;border:none;cursor:pointer}
    button.secondary{background:#374151}
    table{width:100%;border-collapse:collapse}
    th,td{border-bottom:1px solid #e5e7eb;padding:8px;text-align:left;font-size:13px}
    th{background:#f9fafb}
    .status-pending{color:#6b7280}
    .status-running{color:#2563eb}
    .status-success{color:#059669}
    .status-failed{color:#dc2626}
    #logs{background:#0b1020;color:#dbeafe;height:360px;overflow:auto;padding:10px;border-radius:8px;white-space:pre-wrap;font-family:ui-monospace,Menlo,monospace;font-size:12px}
  </style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h3 style="margin:0 0 10px 0">批量导入 CSV 并执行</h3>
    <div class="row">
      <input id="files" type="file" multiple accept=".csv"/>
      <label><input id="connect_cdp" type="checkbox" checked/> CDP接管</label>
      <label>CDP: <input id="cdp_endpoint" value="http://127.0.0.1:18800" style="width:220px"/></label>
      <label><input id="strict_step2" type="checkbox" checked/> strict-step2</label>
      <label><input id="skip_step2" type="checkbox"/> skip-step2</label>
      <label>并发 <input id="concurrent" type="number" min="1" value="1" style="width:70px"/></label>
      <label>start <input id="start" type="number" min="1" style="width:80px"/></label>
      <label>end <input id="end" type="number" min="1" style="width:80px"/></label>
      <label>hold <input id="hold_seconds" type="number" min="0" value="2" style="width:70px"/></label>
      <button onclick="upload()">上传并入队</button>
      <button class="secondary" onclick="retryFailed()">一键重试失败任务</button>
    </div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px 0">任务列表</h3>
    <table>
      <thead><tr>
        <th>文件</th><th>状态</th><th>进度</th><th>成功/失败</th><th>开始</th><th>完成</th><th>预计完成</th><th>耗时(s)</th><th>操作</th>
      </tr></thead>
      <tbody id="taskRows"></tbody>
    </table>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px 0">执行日志</h3>
    <div id="logTitle" style="margin-bottom:8px;color:#6b7280">未选中任务</div>
    <div id="logs"></div>
  </div>
</div>
<script>
let selectedTaskId = "";
let logOffset = 0;

function esc(s){return (s||"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[m]));}

async function upload(){
  const files = document.getElementById('files').files;
  if(!files.length){ alert('请先选择CSV文件'); return; }
  const fd = new FormData();
  for(const f of files){ fd.append('files', f); }
  fd.append('connect_cdp', document.getElementById('connect_cdp').checked ? 'true' : 'false');
  fd.append('cdp_endpoint', document.getElementById('cdp_endpoint').value);
  fd.append('strict_step2', document.getElementById('strict_step2').checked ? 'true' : 'false');
  fd.append('skip_step2', document.getElementById('skip_step2').checked ? 'true' : 'false');
  fd.append('concurrent', document.getElementById('concurrent').value || '1');
  fd.append('start', document.getElementById('start').value || '');
  fd.append('end', document.getElementById('end').value || '');
  fd.append('hold_seconds', document.getElementById('hold_seconds').value || '2');
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

async function refreshTasks(){
  const r = await fetch('/api/tasks');
  const data = await r.json();
  const rows = data.tasks || [];
  const tbody = document.getElementById('taskRows');
  tbody.innerHTML = rows.map(t => `
    <tr>
      <td>${esc(t.filename)}</td>
      <td>${fmtStatus(t.status)}</td>
      <td>${t.completed_plans}/${t.total_plans || '-'}</td>
      <td>${t.success_count}/${t.fail_count}</td>
      <td>${esc(t.started_at || '-')}</td>
      <td>${esc(t.ended_at || '-')}</td>
      <td>${esc(t.eta || '-')}</td>
      <td>${t.duration_sec ? t.duration_sec.toFixed(1) : '-'}</td>
      <td>
        <button onclick="selectTask('${t.id}')">日志</button>
        ${t.status === 'failed' ? `<button class="secondary" onclick="retryTask('${t.id}')">重试</button>` : ''}
      </td>
    </tr>
  `).join('');
}

async function selectTask(id){
  selectedTaskId = id;
  logOffset = 0;
  document.getElementById('logs').textContent = "";
  const t = await (await fetch('/api/tasks/' + id)).json();
  document.getElementById('logTitle').textContent = `任务 ${t.filename} (${t.status})`;
  await pollLogs(true);
}

async function pollLogs(reset=false){
  if(!selectedTaskId) return;
  const r = await fetch(`/api/tasks/${selectedTaskId}/logs?offset=${logOffset}&limit=500`);
  const data = await r.json();
  const logs = data.logs || [];
  if(logs.length){
    const box = document.getElementById('logs');
    box.textContent += logs.join("\\n") + "\\n";
    box.scrollTop = box.scrollHeight;
    logOffset = data.next_offset || (logOffset + logs.length);
  }
}

setInterval(async ()=>{ await refreshTasks(); await pollLogs(); }, 2000);
refreshTasks();
</script>
</body>
</html>
"""

