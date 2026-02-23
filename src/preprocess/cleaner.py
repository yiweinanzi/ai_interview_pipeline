"""文本清洗和标准化"""

import json
from datetime import datetime
import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from src.models import AtomicQuestion
from src.settings import settings

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class TextNormalizer:
    """文本标准化器"""

    def __init__(self, config_path: Path | None = None):
        self.term_mappings = {}
        self.config = {}

        if config_path and config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
                self.term_mappings = self.config.get("normalization", {}).get("term_mappings", {})

    def normalize(self, text: str) -> str:
        """标准化文本

        Args:
            text: 输入文本

        Returns:
            标准化后的文本
        """
        if not text:
            return ""

        # 1. 全角转半角
        text = self._full_to_half(text)

        # 2. 统一标点符号
        text = self._normalize_punctuation(text)

        # 3. 去除多余空格
        text = re.sub(r"\s+", " ", text)

        # 4. 术语映射
        text = self._apply_term_mappings(text)

        # 5. 去除首尾空白
        text = text.strip()

        return text

    def _full_to_half(self, text: str) -> str:
        """全角字符转半角"""
        result = []
        for char in text:
            code = ord(char)
            # 全角空格
            if code == 0x3000:
                result.append(" ")
            # 全角字符 (！到～)
            elif 0xFF01 <= code <= 0xFF5E:
                result.append(chr(code - 0xFEE0))
            else:
                result.append(char)
        return "".join(result)

    def _normalize_punctuation(self, text: str) -> str:
        """统一标点符号"""
        # 中文标点统一
        replacements = {
            "，": ", ",
            "。": ". ",
            "：": ": ",
            "；": "; ",
            "？": "? ",
            "！": "! ",
            "（": " (",
            "）": ") ",
            "【": " [",
            "】": "] ",
            "「": " \"",
            "」": "\" ",
            "『": " \"",
            "』": "\" ",
            """: "\"",
            """: "\"",
            "'": "'",
            "'": "'",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        # 清理多余空格
        text = re.sub(r"\s+", " ", text)

        return text

    def _apply_term_mappings(self, text: str) -> str:
        """应用术语映射"""
        text_lower = text.lower()

        for old, new in self.term_mappings.items():
            # 不区分大小写替换
            pattern = re.compile(re.escape(old), re.IGNORECASE)
            text = pattern.sub(new, text)

        return text


class QuestionNormalizer:
    """问题标准化器"""

    def __init__(self):
        config_path = Path(__file__).parent.parent.parent / "configs" / "pipeline.yaml"
        self.text_normalizer = TextNormalizer(config_path)

    def normalize_question(self, question: AtomicQuestion) -> AtomicQuestion:
        """标准化问题"""
        # 标准化问题文本
        question.question_text_norm = self.text_normalizer.normalize(question.question_text_raw)

        return question


def run_normalize(
    input_file: Path,
    output_file: Path,
) -> dict[str, Any]:
    """运行问题标准化

    Args:
        input_file: 输入文件
        output_file: 输出文件

    Returns:
        统计信息
    """
    normalizer = QuestionNormalizer()

    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    total_questions = 0

    with open(input_file, encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue

            question_data = json.loads(line)
            question = AtomicQuestion(**question_data)

            # 标准化
            question = normalizer.normalize_question(question)

            f_out.write(json.dumps(question.model_dump(), cls=JSONEncoder, ensure_ascii=False))
            f_out.write("\n")
            total_questions += 1

    logger.info(f"问题标准化完成: {total_questions}个问题")

    return {
        "total_questions": total_questions,
    }
