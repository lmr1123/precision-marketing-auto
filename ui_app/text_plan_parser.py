import re
import textwrap
from dataclasses import dataclass
from typing import Dict, List


FIELD_TO_INTERNAL: Dict[str, str] = {
    "计划名称": "name",
    "发送渠道": "channels",
    "计划区域": "region",
    "营销主题": "theme",
    "场景类型": "scene_type",
    "计划类型": "plan_type",
    "推送内容": "push_content",
    "活动介绍": "activity_intro",
    "计划开始时间": "start_time",
    "计划结束时间": "end_time",
    "触发方式": "trigger_type",
    "发送时间": "send_time",
    "全局触达限制": "global_limit",
    "创建链接": "create_url",
    "主消费营运区": "main_operating_area",
    "主消费运营区": "main_operating_area",
    "主消费门店文件路径": "main_store_file_path",
    "第2步门店信息文件路径": "step2_store_file_path",
    "购买目标商品编码": "purchase_target_product_code",
    "目标商品编码": "purchase_target_product_code",
    "已领或已使用券规则ID": "coupon_ids_sheet_ref",
    "券规则ID": "coupon_ids",
    "员工任务结束时间": "step3_end_time",
    "第3步结束时间": "step3_end_time",
    "社群任务分配方式": "distribution_mode",
    "分配方式": "distribution_mode",
    "执行员工": "executor_employees",
    "下发群名": "group_send_name",
    "短信内容": "sms_content",
    "发送内容": "send_content",
    "是否上传门店": "upload_stores",
    "门店文件路径": "store_file_path",
    "1对1-小程序名称": "msg_mini_program_name",
    "1对1-小程序标题": "msg_mini_program_title",
    "1对1-小程序链接": "msg_mini_program_page_path",
    "会员通消息是否添加小程序": "msg_add_mini_program",
}

REQUIRED_FIELDS = {
    "name": "计划名称",
    "channels": "发送渠道",
    "theme": "营销主题",
    "start_time": "计划开始时间",
    "end_time": "计划结束时间",
    "send_time": "发送时间",
}

CONTENT_FIELDS = {
    "push_content": "推送内容",
    "sms_content": "短信内容",
    "send_content": "发送内容",
    "activity_intro": "活动介绍",
}

COMMUNITY_DISTRIBUTION_MODES = {
    "按条件筛选客户": "按条件筛选客户群",
    "按条件筛选客户群": "按条件筛选客户群",
    "导入门店": "导入门店",
    "选中门店": "导入门店",
}


@dataclass
class TextPlanParseError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _split_blocks(text: str) -> List[str]:
    normalized = textwrap.dedent(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in re.split(r"(?m)^\s*---+\s*$", normalized) if b.strip()]
    return blocks or ([normalized.strip()] if normalized.strip() else [])


def _parse_block(block: str, block_no: int) -> Dict[str, str]:
    row: Dict[str, str] = {}
    warnings: List[str] = []
    current_key = ""
    in_multiline = False
    multiline: List[str] = []

    def flush_multiline() -> None:
        nonlocal current_key, in_multiline, multiline
        if in_multiline and current_key and not current_key.startswith("__unsupported__"):
            row[current_key] = "\n".join(multiline).strip()
        current_key = ""
        in_multiline = False
        multiline = []

    def is_multiline_boundary(label: str, value: str, full_line: str) -> bool:
        if label in FIELD_TO_INTERNAL:
            return True
        if "://" in full_line or value.startswith("//"):
            return False
        return True

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_multiline:
            m_next = re.match(r"^([^:：]{2,40})\s*[:：]\s*(.*)$", stripped)
            if m_next and is_multiline_boundary(m_next.group(1).strip(), m_next.group(2).strip(), stripped):
                flush_multiline()
            else:
                if current_key and not current_key.startswith("__unsupported__"):
                    multiline.append(line[2:] if line.startswith("  ") else line)
                continue

        m = re.match(r"^([^:：]{2,40})\s*[:：]\s*(.*)$", stripped)
        if not m:
            raise TextPlanParseError(f"第{block_no}条：无法解析行“{stripped}”，请使用“字段: 值”格式")
        label = m.group(1).strip()
        value = m.group(2).strip()
        key = FIELD_TO_INTERNAL.get(label)
        if not key:
            warnings.append(f"未自动化字段“{label}”，创建后请业务复核/手工补充")
            if value == "|":
                current_key = f"__unsupported__{label}"
                in_multiline = True
                multiline = []
            continue
        if value == "|":
            current_key = key
            in_multiline = True
            multiline = []
            continue
        row[key] = value

    flush_multiline()
    for key, label in REQUIRED_FIELDS.items():
        if not str(row.get(key, "") or "").strip():
            raise TextPlanParseError(f"第{block_no}条：缺少必填字段“{label}”")
    if not any(str(row.get(key, "") or "").strip() for key in CONTENT_FIELDS):
        labels = " / ".join(CONTENT_FIELDS.values())
        raise TextPlanParseError(f"第{block_no}条：缺少内容字段“{labels}”至少一个")
    channels = str(row.get("channels", "") or "")
    channel_parts = [p.strip() for p in re.split(r"[|,，、/]+", channels) if p.strip()]
    if "智能电话" in channel_parts and len(channel_parts) > 1:
        raise TextPlanParseError(f"第{block_no}条：智能电话当前仅支持单渠道计划，请单独创建")
    distribution_mode = str(row.get("distribution_mode", "") or "").strip()
    if "会员通-发送社群" in channels and distribution_mode:
        mode_norm = re.sub(r"\s+", "", distribution_mode)
        normalized = COMMUNITY_DISTRIBUTION_MODES.get(mode_norm)
        if not normalized:
            raise TextPlanParseError(
                f"第{block_no}条：社群任务分配方式只支持“按条件筛选客户群”或“导入门店”，当前为“{distribution_mode}”"
            )
        row["distribution_mode"] = normalized
    if warnings:
        row["__warnings"] = "\n".join(dict.fromkeys(warnings))
    return row


def parse_text_plans(text: str) -> List[Dict[str, str]]:
    blocks = _split_blocks(text)
    if not blocks:
        raise TextPlanParseError("文本为空，请粘贴或上传计划文本")
    return [_parse_block(block, idx + 1) for idx, block in enumerate(blocks)]
