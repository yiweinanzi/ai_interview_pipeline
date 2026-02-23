"""覆盖率审计模块"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from src.models import CoverageAudit, RunAudit

logger = logging.getLogger(__name__)


def run_audit() -> dict[str, Any]:
    """运行覆盖率审计

    Returns:
        审计结果
    """
    data_dir = Path(__file__).parent.parent.parent / "data"

    # 审计报告
    audit = RunAudit()

    # 1. 统计原始记录数
    records_file = data_dir / "staging" / "interviews_raw.jsonl"
    record_ids: set[UUID] = set()

    if records_file.exists():
        with open(records_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                record_ids.add(UUID(data["record_id"]))
        audit.total_records = len(record_ids)

    # 2. 统计分块数
    chunks_file = data_dir / "staging" / "chunks.jsonl"
    if chunks_file.exists():
        with open(chunks_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    audit.total_chunks += 1

    # 3. 统计原子问题数
    questions_file = data_dir / "processed" / "atomic_questions.jsonl"
    covered_records: set[UUID] = set()

    if questions_file.exists():
        with open(questions_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                audit.total_atomic_questions += 1

                # 统计各轮次
                extract_pass = data.get("extract_pass")
                if extract_pass == "first":
                    audit.first_pass_questions += 1
                elif extract_pass == "coverage":
                    audit.coverage_pass_questions += 1

                # 记录覆盖的record
                record_id = UUID(data.get("record_id", ""))
                covered_records.add(record_id)

    # 4. 统计canonical问题数
    canonical_file = data_dir / "processed" / "canonical_questions.jsonl"
    if canonical_file.exists():
        with open(canonical_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    audit.total_atomic_questions += 0  # 已经统计过了
                    audit.canonical_questions += 1

    # 5. 计算覆盖率
    if audit.total_records > 0:
        audit.source_coverage_rate = len(covered_records) / audit.total_records

    # 6. 找出未覆盖的记录
    uncovered = record_ids - covered_records
    audit.uncovered_records = [str(rid) for rid in uncovered]

    # 7. 统计失败记录
    for rid in uncovered:
        coverage = CoverageAudit(
            record_id=rid,
            has_atomic_questions=False,
            atomic_count=0,
            coverage_status="failed",
            notes="未抽取到任何问题",
        )
        audit.extraction_failures += 1

    audit.finished_at = datetime.now()

    # 8. 写入审计报告
    output_dir = data_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_file = output_dir / "coverage_audit.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit.model_dump(), f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"审计报告已生成: {audit_file}")

    # 9. 生成可读报告
    report_file = output_dir / "run_report.md"
    generate_report(audit, report_file)

    return {
        "coverage_rate": audit.source_coverage_rate,
        "total_records": audit.total_records,
        "total_chunks": audit.total_chunks,
        "total_questions": audit.total_atomic_questions,
        "canonical_questions": audit.canonical_questions,
        "uncovered_count": len(audit.uncovered_records),
        "audit_file": str(audit_file),
    }


def generate_report(audit: RunAudit, output_path: Path) -> None:
    """生成可读的运行报告

    Args:
        audit: 审计数据
        output_path: 输出路径
    """
    lines = [
        "# 面经处理流水线运行报告",
        "",
        f"**运行ID**: {audit.run_id}",
        f"**开始时间**: {audit.started_at}",
        f"**结束时间**: {audit.finished_at}",
        "",
        "---",
        "",
        "## 数据统计",
        "",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 原始面经记录 | {audit.total_records} |",
        f"| 文本分块数 | {audit.total_chunks} |",
        f"| 原子问题总数 | {audit.total_atomic_questions} |",
        f"| 首次抽取问题数 | {audit.first_pass_questions} |",
        f"| 补漏抽取问题数 | {audit.coverage_pass_questions} |",
        f"| 去重后问题数 | {audit.canonical_questions} |",
        "",
        "---",
        "",
        "## 覆盖率",
        "",
        f"**源记录覆盖率**: {audit.source_coverage_rate:.2%}",
        "",
    ]

    if audit.uncovered_records:
        lines.append("### 未覆盖记录")
        lines.append("")
        lines.append(f"共 {len(audit.uncovered_records)} 条记录未抽取到问题：")
        lines.append("")
        for rid in audit.uncovered_records[:10]:
            lines.append(f"- `{rid}`")
        if len(audit.uncovered_records) > 10:
            lines.append(f"- ... 还有 {len(audit.uncovered_records) - 10} 条")
        lines.append("")

    if audit.error_codes:
        lines.append("---")
        lines.append("")
        lines.append("## 错误统计")
        lines.append("")
        for code, count in audit.error_codes.items():
            lines.append(f"- {code}: {count}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 验收状态")
    lines.append("")

    if audit.source_coverage_rate >= 1.0:
        lines.append("- [x] 覆盖率 = 100%")
    else:
        lines.append(f"- [ ] 覆盖率 = {audit.source_coverage_rate:.2%} (目标100%)")

    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"运行报告已生成: {output_path}")
