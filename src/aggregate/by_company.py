"""按公司汇总模块"""

import json
from datetime import datetime
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

from src.models import CanonicalQuestion

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def aggregate_by_company(
    questions: list[CanonicalQuestion],
    records: dict[UUID, dict],
) -> dict[str, list[dict]]:
    """按公司聚合问题

    Args:
        questions: 问题列表
        records: 原始记录映射 {record_id: record}

    Returns:
        按公司分组的问题字典
    """
    # 从source_refs提取公司信息
    company_questions: dict[str, list[dict]] = defaultdict(list)

    for q in questions:
        # 获取该问题出现的公司
        companies_for_q = set()

        for ref in q.source_refs:
            try:
                record_id = UUID(ref)
                record = records.get(record_id)
                if record:
                    company = record.get("company_norm") or record.get("company_raw") or "未知"
                    companies_for_q.add(company)
            except ValueError:
                pass

        # 更新问题的公司统计
        q.companies = list(companies_for_q)
        q.company_count = len(companies_for_q)

        # 将问题添加到各公司的列表
        for company in companies_for_q:
            company_questions[company].append({
                "canonical_id": str(q.canonical_question_id),
                "question": q.canonical_question_text,
                "variants": q.variants[:5],
                "primary_tag": q.primary_tag,
                "secondary_tags": q.secondary_tags,
                "member_count": q.member_count,
                "source_count": len(q.source_refs),
            })

    return dict(company_questions)


def get_freq_level(count: int) -> str:
    """获取高频等级标记"""
    if count >= 20:
        return "🔥🔥🔥"  # 超高频
    elif count >= 10:
        return "🔥🔥"   # 高频
    elif count >= 5:
        return "🔥"     # 中频
    return ""


def generate_company_markdown(
    company_questions: dict[str, list[dict]],
    output_path: Path,
    high_freq_threshold: int = 5,
) -> None:
    """生成按公司汇总的Markdown文件

    Args:
        company_questions: 按公司分组的问题
        output_path: 输出文件路径
        high_freq_threshold: 高频问题阈值
    """
    # 统计高频问题
    all_questions = []
    for questions in company_questions.values():
        all_questions.extend(questions)

    lines = [
        "# AI算法工程师面经汇总 - 按公司分类",
        "",
        f"共收录 {len(company_questions)} 家公司的面试问题",
        "",
        "---",
        "",
    ]

    # 按公司问题数量排序
    sorted_companies = sorted(
        company_questions.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    for company, questions in sorted_companies:
        # 统计该公司高频问题
        hf_count = len([q for q in questions if q["member_count"] >= high_freq_threshold])

        lines.append(f"## {company}")
        lines.append(f"")
        lines.append(f"**问题总数**: {len(questions)} (高频 {hf_count} 个)")
        lines.append(f"")

        # 按知识点分组
        by_tag: dict[str, list[dict]] = defaultdict(list)
        for q in questions:
            tag = q.get("primary_tag") or "其他"
            by_tag[tag].append(q)

        for tag, tag_questions in sorted(by_tag.items()):
            if tag == "uncertain":
                tag = "待分类"

            lines.append(f"### {tag}")
            lines.append(f"")

            # 按出现次数排序
            sorted_questions = sorted(tag_questions, key=lambda x: x["member_count"], reverse=True)

            for i, q in enumerate(sorted_questions, 1):
                is_high_freq = q["member_count"] >= high_freq_threshold
                freq_mark = get_freq_level(q["member_count"])

                title = f"#### {i}. {freq_mark} {q['question']}" if is_high_freq else f"#### {i}. {q['question']}"
                lines.append(title)
                lines.append(f"")

                if q.get("variants"):
                    lines.append("**常见变体**:")
                    for v in q["variants"][:3]:
                        if v != q["question"]:
                            lines.append(f"- {v}")
                    lines.append("")

                if is_high_freq:
                    lines.append(f"**出现次数**: **{q['member_count']}** (高频)")
                else:
                    lines.append(f"**出现次数**: {q['member_count']}")
                lines.append("")

        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"公司汇总Markdown已生成: {output_path}")


def generate_company_excel(
    company_questions: dict[str, list[dict]],
    output_path: Path,
    high_freq_threshold: int = 5,
) -> None:
    """生成按公司汇总的Excel文件

    Args:
        company_questions: 按公司分组的问题
        output_path: 输出文件路径
        high_freq_threshold: 高频问题阈值
    """
    rows = []

    for company, questions in company_questions.items():
        for q in questions:
            # 判断是否高频
            freq_level = ""
            if q["member_count"] >= 20:
                freq_level = "超高频"
            elif q["member_count"] >= 10:
                freq_level = "高频"
            elif q["member_count"] >= 5:
                freq_level = "中频"

            rows.append({
                "公司": company,
                "问题": q["question"],
                "高频标记": freq_level,
                "知识点": q.get("primary_tag", ""),
                "次级知识点": ", ".join(q.get("secondary_tags", [])),
                "出现次数": q["member_count"],
                "变体": "; ".join(q.get("variants", [])[:3]),
            })

    df = pd.DataFrame(rows)
    # 排序：先按公司，再按高频标记和出现次数
    freq_order = {"超高频": 0, "高频": 1, "中频": 2, "": 3}
    df["_sort"] = df["高频标记"].map(freq_order)
    df = df.sort_values(["公司", "_sort", "出现次数"], ascending=[True, True, False])
    df = df.drop(columns=["_sort"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="汇总", index=False)

        # 高频问题单独sheet
        high_freq_df = df[df["出现次数"] >= high_freq_threshold]
        if not high_freq_df.empty:
            high_freq_df.to_excel(writer, sheet_name="高频问题", index=False)

        # 为每个公司创建单独的sheet
        for company in df["公司"].unique()[:20]:  # 最多20个公司
            company_df = df[df["公司"] == company]
            # Sheet名称最长31字符
            sheet_name = company[:31]
            company_df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"公司汇总Excel已生成: {output_path}")
