"""汇总模块"""

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from src.aggregate.by_company import (
    aggregate_by_company,
    generate_company_excel,
    generate_company_markdown,
)
from src.aggregate.by_knowledge import (
    aggregate_by_knowledge,
    generate_knowledge_excel,
    generate_knowledge_markdown,
)
from src.models import CanonicalQuestion

logger = logging.getLogger(__name__)


def run_aggregate(
    company_output: Path | None = None,
    knowledge_output: Path | None = None,
) -> dict[str, Any]:
    """运行汇总生成

    Args:
        company_output: 按公司汇总输出路径
        knowledge_output: 按知识点汇总输出路径

    Returns:
        统计信息
    """
    # 默认路径
    data_dir = Path(__file__).parent.parent.parent / "data"
    input_file = data_dir / "processed" / "classified_questions.jsonl"

    if company_output is None:
        company_output = data_dir / "output" / "company_summary.md"
    if knowledge_output is None:
        knowledge_output = data_dir / "output" / "knowledge_summary.md"

    # 确保输出目录存在
    company_output.parent.mkdir(parents=True, exist_ok=True)

    # 加载分类后的问题
    questions: list[CanonicalQuestion] = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            questions.append(CanonicalQuestion(**data))

    logger.info(f"加载 {len(questions)} 个问题")

    # 加载原始记录（用于提取公司信息）
    records_file = data_dir / "staging" / "interviews_raw.jsonl"
    records: dict[UUID, dict] = {}

    if records_file.exists():
        with open(records_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                record_id = UUID(data["record_id"])
                records[record_id] = data

    logger.info(f"加载 {len(records)} 条原始记录")

    # 按公司汇总
    company_questions = aggregate_by_company(questions, records)
    generate_company_markdown(company_questions, company_output)
    generate_company_excel(
        company_questions,
        company_output.with_suffix(".xlsx"),
    )

    # 按知识点汇总
    knowledge_questions = aggregate_by_knowledge(questions)
    generate_knowledge_markdown(knowledge_questions, knowledge_output)
    generate_knowledge_excel(
        knowledge_questions,
        knowledge_output.with_suffix(".xlsx"),
    )

    return {
        "company_output": str(company_output),
        "knowledge_output": str(knowledge_output),
        "total_questions": len(questions),
        "total_companies": len(company_questions),
        "total_knowledge_areas": len(knowledge_questions),
    }
