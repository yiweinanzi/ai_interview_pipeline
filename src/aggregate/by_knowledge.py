"""按知识点汇总模块"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd
import yaml

from src.models import CanonicalQuestion

logger = logging.getLogger(__name__)


def aggregate_by_knowledge(
    questions: list[CanonicalQuestion],
    taxonomy_path: Path | None = None,
) -> dict[str, list[dict]]:
    """按知识点聚合问题

    Args:
        questions: 问题列表
        taxonomy_path: taxonomy配置路径

    Returns:
        按知识点分组的问题字典
    """
    # 加载taxonomy
    if taxonomy_path is None:
        taxonomy_path = Path(__file__).parent.parent.parent / "configs" / "knowledge_taxonomy.yaml"

    taxonomy = {}
    if taxonomy_path.exists():
        with open(taxonomy_path, encoding="utf-8") as f:
            taxonomy = yaml.safe_load(f).get("taxonomy", {})

    knowledge_questions: dict[str, list[dict]] = defaultdict(list)

    for q in questions:
        primary = q.primary_tag or "uncertain"

        # 获取分类的友好名称
        category_name = primary
        if primary in taxonomy:
            category_name = taxonomy[primary].get("name", primary)

        knowledge_questions[category_name].append({
            "canonical_id": str(q.canonical_question_id),
            "question": q.canonical_question_text,
            "companies": q.companies,
            "company_count": q.company_count,
            "variants": q.variants[:5],
            "secondary_tags": q.secondary_tags,
            "member_count": q.member_count,
            "tag_key": primary,
        })

    return dict(knowledge_questions)


def generate_knowledge_markdown(
    knowledge_questions: dict[str, list[dict]],
    output_path: Path,
    high_freq_threshold: int = 5,  # 高频问题阈值：出现5次以上
) -> None:
    """生成按知识点汇总的Markdown文件

    Args:
        knowledge_questions: 按知识点分组的问题
        output_path: 输出文件路径
        high_freq_threshold: 高频问题阈值
    """
    # 统计高频问题
    all_questions = []
    for questions in knowledge_questions.values():
        all_questions.extend(questions)

    high_freq_questions = [
        q for q in all_questions
        if q["member_count"] >= high_freq_threshold
    ]
    high_freq_count = len(high_freq_questions)

    lines = [
        "# AI算法工程师面经汇总 - 按知识点分类",
        "",
        f"共收录 {len(all_questions)} 个问题",
        f"涵盖 {len(knowledge_questions)} 个知识点领域",
        f"**高频问题（出现{high_freq_threshold}次以上）: {high_freq_count} 个**",
        "",
        "---",
        "",
        "## 高频问题速览",
        "",
    ]

    # 高频问题按出现次数排序
    sorted_high_freq = sorted(high_freq_questions, key=lambda x: x["member_count"], reverse=True)
    for q in sorted_high_freq[:50]:  # 最多显示50个高频问题
        freq_level = get_freq_level(q["member_count"])
        companies_str = ", ".join(q["companies"][:3]) if q.get("companies") else ""
        lines.append(f"- {freq_level} **{q['question']}** ({q['member_count']}次 | {companies_str})")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 目录")
    lines.append("")

    # 按问题数量排序
    sorted_knowledge = sorted(
        knowledge_questions.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    # 生成目录
    for name, questions in sorted_knowledge:
        hf_count = len([q for q in questions if q["member_count"] >= high_freq_threshold])
        hf_mark = f" ({hf_count}高频)" if hf_count > 0 else ""
        lines.append(f"- [{name}](#{name.lower()}) ({len(questions)}题{hf_mark})")

    lines.append("")
    lines.append("---")
    lines.append("")

    # 生成各知识点内容
    for name, questions in sorted_knowledge:
        lines.append(f"## {name}")
        lines.append(f"")
        hf_in_cat = [q for q in questions if q["member_count"] >= high_freq_threshold]
        lines.append(f"**题目数量**: {len(questions)} (高频 {len(hf_in_cat)} 个)")
        lines.append(f"")

        # 按出现次数排序
        sorted_questions = sorted(questions, key=lambda x: x["member_count"], reverse=True)

        for i, q in enumerate(sorted_questions, 1):
            # 高频标记
            freq_level = get_freq_level(q["member_count"])
            is_high_freq = q["member_count"] >= high_freq_threshold

            title = f"### {i}. {freq_level} {q['question']}" if is_high_freq else f"### {i}. {q['question']}"
            lines.append(title)
            lines.append(f"")

            # 公司信息
            if q.get("companies"):
                company_str = ", ".join(q["companies"][:5])
                if len(q["companies"]) > 5:
                    company_str += f" 等{len(q['companies'])}家公司"
                lines.append(f"**出现公司**: {company_str}")
                lines.append("")

            # 出现次数（高频加粗）
            if is_high_freq:
                lines.append(f"**出现次数**: **{q['member_count']}** (高频)")
            else:
                lines.append(f"**出现次数**: {q['member_count']}")
            lines.append("")

            # 变体
            if q.get("variants"):
                other_variants = [v for v in q["variants"] if v != q["question"]]
                if other_variants:
                    lines.append("**常见变体**:")
                    for v in other_variants[:3]:
                        lines.append(f"- {v}")
                    lines.append("")

        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"知识点汇总Markdown已生成: {output_path}")
    logger.info(f"高频问题数: {high_freq_count}")


def get_freq_level(count: int) -> str:
    """获取高频等级标记"""
    if count >= 20:
        return "🔥🔥🔥"  # 超高频
    elif count >= 10:
        return "🔥🔥"   # 高频
    elif count >= 5:
        return "🔥"     # 中频
    return ""


def generate_knowledge_excel(
    knowledge_questions: dict[str, list[dict]],
    output_path: Path,
    high_freq_threshold: int = 5,
) -> None:
    """生成按知识点汇总的Excel文件

    Args:
        knowledge_questions: 按知识点分组的问题
        output_path: 输出文件路径
        high_freq_threshold: 高频问题阈值
    """
    rows = []

    for knowledge, questions in knowledge_questions.items():
        for q in questions:
            # 判断是否高频
            is_high_freq = q["member_count"] >= high_freq_threshold
            freq_level = ""
            if q["member_count"] >= 20:
                freq_level = "超高频"
            elif q["member_count"] >= 10:
                freq_level = "高频"
            elif q["member_count"] >= 5:
                freq_level = "中频"

            rows.append({
                "知识点": knowledge,
                "问题": q["question"],
                "高频标记": freq_level,
                "出现次数": q["member_count"],
                "出现公司数": q["company_count"],
                "出现公司": ", ".join(q.get("companies", [])[:5]),
                "变体": "; ".join(q.get("variants", [])[:3]),
                "次级知识点": ", ".join(q.get("secondary_tags", [])),
            })

    df = pd.DataFrame(rows)
    # 按高频标记和出现次数排序
    freq_order = {"超高频": 0, "高频": 1, "中频": 2, "": 3}
    df["_sort"] = df["高频标记"].map(freq_order)
    df = df.sort_values(["_sort", "出现次数"], ascending=[True, False])
    df = df.drop(columns=["_sort"])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # 汇总表
        df.to_excel(writer, sheet_name="汇总", index=False)

        # 高频问题单独sheet
        high_freq_df = df[df["出现次数"] >= high_freq_threshold]
        if not high_freq_df.empty:
            high_freq_df.to_excel(writer, sheet_name="高频问题", index=False)

        # 为每个知识点创建单独的sheet
        for knowledge in df["知识点"].unique()[:20]:
            k_df = df[df["知识点"] == knowledge]
            sheet_name = knowledge[:31]
            k_df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info(f"知识点汇总Excel已生成: {output_path}")
