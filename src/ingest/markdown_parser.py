"""Markdown文件解析器"""

import logging
import re
from pathlib import Path
from typing import Any

from src.models import InterviewRecord, SourceType

logger = logging.getLogger(__name__)


def parse_standard_markdown(file_path: Path, company_hint: str | None = None) -> InterviewRecord | None:
    """解析标准格式的Markdown面经文件

    适用于 nowcoder_xxx_suanfa/ 目录下的文件

    Args:
        file_path: 文件路径
        company_hint: 公司名称提示（从目录名提取）

    Returns:
        InterviewRecord 或 None（如果解析失败）
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return None

    if not content.strip():
        logger.warning(f"文件为空: {file_path}")
        return None

    # 解析标题（通常是第一个#标题）
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_path.stem

    # 解析发布时间
    date_raw = None
    date_patterns = [
        r"\*\*发布时间\*\*[：:]\s*(.+?)(?:\n|$)",
        r"发布时间[：:]\s*(.+?)(?:\n|$)",
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, content)
        if match:
            date_raw = match.group(1).strip()
            break

    # 提取正文（去掉元信息后的内容）
    # 跳过标题行、发布时间、标签等元信息
    lines = content.split("\n")
    text_start = 0

    for i, line in enumerate(lines):
        # 跳过标题
        if line.startswith("#"):
            text_start = i + 1
            continue
        # 跳过发布时间行
        if "**发布时间**" in line or "发布时间" in line:
            text_start = i + 1
            continue
        # 跳过标签行
        if "**标签**" in line or line.strip().startswith("**回复数**"):
            text_start = i + 1
            continue
        # 找到第一个非空非元信息行
        if line.strip() and not line.startswith("**") and not line.startswith(">"):
            break

    text_raw = "\n".join(lines[text_start:]).strip()

    # 文本清洗
    text_clean = clean_text(text_raw)

    return InterviewRecord(
        source_type=SourceType.MARKDOWN,
        source_path=str(file_path),
        source_title=title,
        company_raw=company_hint,
        interview_date_raw=date_raw,
        text_raw=content,  # 保留完整原文
        text_clean=text_clean,
        ingest_meta={
            "parser": "standard_markdown",
            "original_title": title,
        },
    )


def parse_knowledge_base_markdown(file_path: Path) -> list[InterviewRecord]:
    """解析知识点题库格式的Markdown文件

    适用于 04-interview/ 目录下的文件
    这些文件是按主题整理的题库，包含详细解析

    Args:
        file_path: 文件路径

    Returns:
        InterviewRecord列表（每个问题一条记录）
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return []

    records = []

    # 识别问题边界（Q1:, Q2:, #### Q1: 等格式）
    question_pattern = re.compile(
        r"(?:^|\n)(?:#{1,4}\s*)?(?:Q\d+[:.：]|问题\d+[:.：]|####\s*Q\d+)",
        re.MULTILINE,
    )

    # 找到所有问题的起始位置
    matches = list(question_pattern.finditer(content))

    if not matches:
        # 如果没有找到标准问题格式，将整个文件作为一条记录
        return [
            InterviewRecord(
                source_type=SourceType.MARKDOWN,
                source_path=str(file_path),
                source_title=file_path.stem,
                company_raw="通用题库",
                text_raw=content,
                text_clean=clean_text(content),
                ingest_meta={
                    "parser": "knowledge_base_markdown",
                    "file_type": "question_bank",
                },
            )
        ]

    # 按问题分割内容
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        question_block = content[start:end].strip()

        # 提取问题标题
        title_match = re.search(r"(?:Q\d+[:.：]|问题\d+[:.：])\s*(.+?)(?:\n|$)", question_block)
        title = title_match.group(1).strip() if title_match else f"问题{i + 1}"

        # 提取难度
        difficulty = None
        difficulty_match = re.search(r"\*\*难度\*\*[：:]\s*(.+?)(?:\n|$)", question_block)
        if difficulty_match:
            difficulty = difficulty_match.group(1).strip()

        # 提取标签
        tags = []
        tags_match = re.search(r"\*\*标签\*\*[：:]\s*(.+?)(?:\n|$)", question_block)
        if tags_match:
            tags = [t.strip() for t in tags_match.group(1).split("#") if t.strip()]

        records.append(
            InterviewRecord(
                source_type=SourceType.MARKDOWN,
                source_path=str(file_path),
                source_title=title,
                company_raw="通用题库",
                text_raw=question_block,
                text_clean=clean_text(question_block),
                ingest_meta={
                    "parser": "knowledge_base_markdown",
                    "question_index": i + 1,
                    "difficulty": difficulty,
                    "tags": tags,
                },
            )
        )

    return records


def parse_feishu_markdown(file_path: Path) -> InterviewRecord | None:
    """解析飞书剪存格式的Markdown文件

    适用于 else/ 目录下的面经1.md, 面经2.md 等文件

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

    # 飞书剪存格式通常包含原文链接和剪存时间
    # 提取公司信息（通常在标题或正文中）
    company_raw = None

    # 尝试从标题提取公司
    title_match = re.search(r"^#+\s*(.+?)(?:面经|面试)", content, re.MULTILINE)
    if title_match:
        title_text = title_match.group(1)
        # 提取公司名
        company_patterns = [
            r"(阿里|字节|腾讯|美团|快手|百度|网易|小红书|华为|京东|拼多多|B站|小米)",
            r"(蚂蚁|滴滴|携程|OPPO|VIVO|联想|荣耀|商汤|科大讯飞)",
        ]
        for pattern in company_patterns:
            match = re.search(pattern, title_text)
            if match:
                company_raw = match.group(1)
                break

    # 清洗飞书剪存的特殊格式
    text_clean = clean_text(content)
    # 移除飞书剪存的元信息
    text_clean = re.sub(r"🔗\s*原文链接.*?\n", "", text_clean)
    text_clean = re.sub(r"⏰\s*剪存时间.*?\n", "", text_clean)
    text_clean = re.sub(r"✂️\s*本文档由.*?\n", "", text_clean)
    text_clean = re.sub(r"💖\s*更多好物.*?\n", "", text_clean)

    return InterviewRecord(
        source_type=SourceType.MARKDOWN,
        source_path=str(file_path),
        source_title=file_path.stem,
        company_raw=company_raw or "未知",
        text_raw=content,
        text_clean=text_clean.strip(),
        ingest_meta={
            "parser": "feishu_markdown",
        },
    )


def clean_text(text: str) -> str:
    """清洗文本

    - 去除广告/引流内容
    - 去除HTML标签
    - 保留问题内容
    """
    if not text:
        return ""

    # 去除HTML标签
    text = re.sub(r"<[^>]+>", "", text)

    # 去除图片标签（牛客网格式）
    text = re.sub(r'<img[^>]*>', "", text)

    # 去除常见的广告/引流内容
    ad_patterns = [
        r"对于想求职.*?欢迎后台联系",
        r"点赞.*?收藏.*?关注",
        r"加群.*?私信",
        r"扫码.*?关注",
        r"更多面试题.*?关注",
        r"🐵公式解析失败.*",
    ]
    for pattern in ad_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 去除多余的空行（保留最多两个连续换行）
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 去除行首行尾空白
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def extract_company_from_dir(dir_name: str) -> str | None:
    """从目录名提取公司名称

    Args:
        dir_name: 目录名，如 "nowcoder_bytedance_suanfa"

    Returns:
        公司名称或None
    """
    import yaml

    # 加载公司别名配置
    config_path = Path(__file__).parent.parent.parent / "configs" / "company_alias.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            dir_to_company = config.get("dir_to_company", {})
    else:
        dir_to_company = {}

    # 尝试直接匹配
    if dir_name in dir_to_company:
        return dir_to_company[dir_name]

    # 尝试从模式提取
    patterns = [
        r"nowcoder_(.+)_suanfa",
        r"(.+)_suanfa",
        r"(.+)_algorithm",
    ]
    for pattern in patterns:
        match = re.match(pattern, dir_name)
        if match:
            key = match.group(1)
            if key in dir_to_company:
                return dir_to_company[key]
            # 返回原始提取的公司名（稍后归一化）
            return key

    return None
