"""特殊格式解析器"""

import logging
import re
from pathlib import Path

from src.models import InterviewRecord, SourceType

logger = logging.getLogger(__name__)


def parse_ali_deep_dive(file_path: Path) -> list[InterviewRecord]:
    """解析阿里系深度解析格式的Markdown

    这种格式包含频次统计和详细分析，如 else/阿里系.md

    Args:
        file_path: 文件路径

    Returns:
        InterviewRecord列表
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return []

    records = []

    # 按二级标题分割（## xxx）
    sections = re.split(r"\n##\s+", content)

    for section in sections[1:]:  # 跳过第一个（可能是空或标题）
        # 提取小节标题
        lines = section.split("\n")
        section_title = lines[0].strip() if lines else ""

        # 在小节中查找问题（通常在**加粗**或- 列表中）
        # 提取所有看起来像问题的内容
        questions = []

        # 匹配格式如 "- **RoPE (Rotary Positional Embeddings): 42次**"
        question_pattern = re.compile(
            r"[-*]\s*\*\*([^*]+)\*\*[:：]?\s*(\d+次)?",
            re.MULTILINE,
        )

        for match in question_pattern.finditer(section):
            question_text = match.group(1).strip()
            freq = match.group(2) if match.group(2) else ""

            if question_text and len(question_text) > 3:
                # 获取上下文（到下一��问题之前的所有内容）
                start = match.end()
                next_match = question_pattern.search(section, match.end())
                end = next_match.start() if next_match else len(section)
                context = section[start:end].strip()

                # 构建完整的问题文本
                full_text = f"{question_text}"
                if freq:
                    full_text += f" ({freq})"
                if context:
                    full_text += f"\n\n{context[:500]}"  # 限制上下文长度

                record = InterviewRecord(
                    source_type=SourceType.MARKDOWN,
                    source_path=str(file_path),
                    source_title=question_text,
                    company_raw="阿里巴巴",
                    text_raw=full_text,
                    text_clean=full_text,
                    ingest_meta={
                        "parser": "ali_deep_dive",
                        "section": section_title,
                        "frequency": freq,
                    },
                )
                records.append(record)

    return records


def parse_general_markdown(file_path: Path) -> InterviewRecord | None:
    """通用Markdown解析器

    作为最后的后备方案

    Args:
        file_path: 文件路径

    Returns:
        InterviewRecord 或 None
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return None

    if not content.strip():
        return None

    # 提取标题
    title_match = re.search(r"^#+\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_path.stem

    # 尝试从标题或内容中提取公司名
    company_raw = extract_company_from_content(content) or "未知"

    return InterviewRecord(
        source_type=SourceType.MARKDOWN,
        source_path=str(file_path),
        source_title=title,
        company_raw=company_raw,
        text_raw=content,
        text_clean=content.strip(),
        ingest_meta={
            "parser": "general_markdown",
        },
    )


def extract_company_from_content(content: str) -> str | None:
    """从内容中提取公司名"""
    company_keywords = [
        ("字节跳动", ["字节跳动", "字节", "bytedance", "抖音", "tiktok"]),
        ("阿里巴巴", ["阿里巴巴", "阿里", "alibaba", "阿里云", "达摩院"]),
        ("腾讯", ["腾讯", "tencent", "微信", "QQ"]),
        ("美团", ["美团", "meituan"]),
        ("快手", ["快手", "kuaishou"]),
        ("百度", ["百度", "baidu"]),
        ("网易", ["网易", "netease", "网易云音乐", "网易游戏"]),
        ("小红书", ["小红书", "xiaohongshu", "xhs"]),
        ("华为", ["华为", "huawei"]),
        ("京东", ["京东", "jd", "jingdong"]),
        ("拼多多", ["拼多多", "pdd", "pinduoduo"]),
        ("哔哩哔哩", ["哔哩哔哩", "bilibili", "B站", "b站"]),
    ]

    content_lower = content.lower()
    for company, keywords in company_keywords:
        for keyword in keywords:
            if keyword.lower() in content_lower:
                return company

    return None


def detect_file_type(file_path: Path) -> str:
    """检测文件类型

    Returns:
        文件类型: standard, knowledge_base, feishu, ali_deep_dive, general
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return "general"

    # 检测知识点题库格式
    if re.search(r"Q\d+[:.：].*?难度", content, re.DOTALL):
        return "knowledge_base"

    # 检测飞书剪存格式
    if "游侠飞书剪存" in content or "原文链接" in content:
        return "feishu"

    # 检测阿里深度解析格式
    if "2025年至今" in content and "次**" in content:
        return "ali_deep_dive"

    # 检测标准面经格式
    if re.search(r"\*\*发布时间\*\*", content):
        return "standard"

    return "general"
