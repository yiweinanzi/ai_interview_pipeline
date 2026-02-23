"""数据接入模块"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from src.ingest.csv_parser import parse_csv_file, parse_excel_file
from src.ingest.markdown_parser import (
    extract_company_from_dir,
    parse_feishu_markdown,
    parse_knowledge_base_markdown,
    parse_standard_markdown,
)
from src.ingest.special_parser import (
    detect_file_type,
    parse_ali_deep_dive,
    parse_general_markdown,
)
from src.models import InterviewRecord

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    """支持UUID和datetime的JSON编码器"""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def run_ingest(
    input_dir: Path,
    output_file: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    """运行数据接入流程

    Args:
        input_dir: 输入目录
        output_file: 输出文件路径
        limit: 限制处理的文件数量

    Returns:
        统计信息字典
    """
    # 加载公司别名配置
    config_path = Path(__file__).parent.parent.parent / "configs" / "company_alias.yaml"
    company_config = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            company_config = yaml.safe_load(f)

    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    records: list[InterviewRecord] = []
    stats = {
        "total_files": 0,
        "success_count": 0,
        "error_count": 0,
        "by_type": {},
        "by_company": {},
    }

    # 遍历输入目录
    input_path = Path(input_dir)

    for file_path in sorted(input_path.rglob("*")):
        if not file_path.is_file():
            continue

        if limit and stats["total_files"] >= limit:
            break

        # 跳过非目标文件
        suffix = file_path.suffix.lower()
        if suffix not in [".md", ".csv", ".xlsx", ".xls"]:
            continue

        stats["total_files"] += 1

        # 获取公司提示（从目录名）
        parent_dir = file_path.parent.name
        company_hint = extract_company_from_dir(parent_dir)

        try:
            file_records = process_file(file_path, company_hint, company_config)
            records.extend(file_records)
            stats["success_count"] += len(file_records)

            # 统计
            for record in file_records:
                file_type = record.source_type.value
                stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

                company = record.company_raw or "未知"
                stats["by_company"][company] = stats["by_company"].get(company, 0) + 1

        except Exception as e:
            logger.error(f"处理文件失败: {file_path}, 错误: {e}")
            stats["error_count"] += 1

    # 归一化公司名
    mappings = company_config.get("mappings", {})
    for record in records:
        if record.company_raw and record.company_raw in mappings:
            record.company_norm = mappings[record.company_raw]
        else:
            record.company_norm = record.company_raw

    # 写入输出文件
    with open(output_file, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record.model_dump(), cls=JSONEncoder, ensure_ascii=False))
            f.write("\n")

    logger.info(f"数据接入完成: {len(records)}条记录写入 {output_file}")

    return stats


def process_file(
    file_path: Path,
    company_hint: str | None,
    company_config: dict,
) -> list[InterviewRecord]:
    """处理单个文件

    Args:
        file_path: 文件路径
        company_hint: 公司名称提示
        company_config: 公司配置

    Returns:
        InterviewRecord列表
    """
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        return parse_csv_file(file_path)

    elif suffix in [".xlsx", ".xls"]:
        return parse_excel_file(file_path)

    elif suffix == ".md":
        # 检测Markdown文件类型
        file_type = detect_file_type(file_path)
        parent_dir = file_path.parent.name

        if file_type == "knowledge_base" or parent_dir == "04-interview":
            return parse_knowledge_base_markdown(file_path)

        elif file_type == "feishu":
            record = parse_feishu_markdown(file_path)
            return [record] if record else []

        elif file_type == "ali_deep_dive":
            return parse_ali_deep_dive(file_path)

        elif file_type == "standard":
            record = parse_standard_markdown(file_path, company_hint)
            return [record] if record else []

        else:
            # 通用解析
            record = parse_general_markdown(file_path)
            return [record] if record else []

    return []
