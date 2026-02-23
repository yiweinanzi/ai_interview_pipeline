"""原子问题抽取器"""

import json
from datetime import datetime
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from src.llm import DeepSeekClient, get_client
from src.models import (
    AtomicQuestion,
    ExtractedQuestion,
    ExtractionResult,
    ExtractPass,
    QuestionType,
    TextChunk,
)
from src.settings import settings

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# Prompt模板（稳定前缀，用于缓存）
SYSTEM_PROMPT_EXTRACT = """你是一个"面试问题抽取器"。请从下面的文本中，**完整提取所有面试问题**（包括追问），不要漏掉任何问题，不要总结，不要合并同义问题。

## 输出格式

输出必须是**json格式**，格式如下：

```json
{
  "questions": [
    {
      "question_text": "问题的完整文本",
      "question_type": "main",
      "round_hint": "一面/二面/HR面（如果可���别）",
      "topic_hint": ["相关主题关键词"],
      "evidence_span": "原文中包含该问题的直接片段",
      "is_multi_part": false
    }
  ]
}
```

## 抽取规则

1. **只抽取问题**：不要抽取候选人回答（除非回答里包含追问线索）
2. **复合问题拆分**：一个问句中包含多个问题的要拆开
3. **保守保留**：如果不确定是否是问题，**保留它**
4. **证据必须来自原文**：evidence_span必须是原文中的直接片段
5. **保留原始表述**：不要改写或总结问题

## 识别问题的信号

- 问号结尾的句子
- "介绍一下..."、"讲一下..."、"说说..."开头
- "为什么..."、"怎么..."、"如何..."
- 编号的问题（1. 2. 3.）
- 追问（"那xxx呢？"、"继续深挖..."）
"""


SYSTEM_PROMPT_COVERAGE = """你是一个"漏题检查器"。下面有**原始文本**和**已经抽取的问题列表**，请仔细检查是否有**遗漏的问题**。

## 输出格式

输出必须是**json格式**：

```json
{
  "missed_questions": [
    {
      "question_text": "遗漏问题的完整文本",
      "question_type": "main",
      "evidence_span": "原文中的直接片段",
      "reason": "为什么认为这是遗漏的问题"
    }
  ]
}
```

## 检查规则

1. **只输出遗漏的问题**：不要重复已经抽取的问题
2. **宁可多报也不要漏报**：对于不确定的内容，保守地标记为遗漏
3. **如果没有遗漏**：输出 `{"missed_questions": []}`
"""


class QuestionExtractor:
    """问题抽取器"""

    def __init__(
        self,
        client: DeepSeekClient | None = None,
        enable_coverage: bool = True,
    ):
        self.client = client or get_client()
        self.enable_coverage = enable_coverage
        self.prompt_version = "v1.0"

    def extract_questions(self, chunk: TextChunk) -> list[AtomicQuestion]:
        """从chunk中抽取问题

        Args:
            chunk: 文本分块

        Returns:
            原子问题列表
        """
        questions = []

        # 第一轮抽取
        first_pass_result = self._extract_first_pass(chunk.chunk_text)
        for q in first_pass_result:
            question = self._create_atomic_question(
                q,
                chunk,
                ExtractPass.FIRST,
            )
            questions.append(question)

        # 补漏检查
        if self.enable_coverage and first_pass_result:
            coverage_result = self._coverage_check(
                chunk.chunk_text,
                first_pass_result,
            )
            for missed in coverage_result:
                question = self._create_atomic_question(
                    missed,
                    chunk,
                    ExtractPass.COVERAGE,
                )
                questions.append(question)

        return questions

    def _extract_first_pass(self, text: str) -> list[ExtractedQuestion]:
        """第一轮抽取"""
        user_prompt = f"## 原文\n\n{text}"

        try:
            result = self.client.call_json(
                SYSTEM_PROMPT_EXTRACT,
                user_prompt,
                response_model=ExtractionResult,
                temperature=0.0,
                max_tokens=6144,
            )
            return [ExtractedQuestion(**q) for q in result.get("questions", [])]
        except Exception as e:
            logger.error(f"抽取问题失败: {e}")
            return []

    def _coverage_check(
        self,
        text: str,
        extracted: list[ExtractedQuestion],
    ) -> list[ExtractedQuestion]:
        """补漏检查"""
        # 构建已抽取问题列表
        extracted_text = "\n".join([
            f"- {q.question_text}"
            for q in extracted
        ])

        user_prompt = f"""## 原始文本

{text}

## 已抽取的问题列表

{extracted_text}
"""
        try:
            from src.models.schemas import CoverageCheckResult, MissedQuestion

            result = self.client.call_json(
                SYSTEM_PROMPT_COVERAGE,
                user_prompt,
                response_model=CoverageCheckResult,
                temperature=0.0,
                max_tokens=6144,
            )

            missed = []
            for q in result.get("missed_questions", []):
                missed.append(ExtractedQuestion(
                    question_text=q.get("question_text", ""),
                    question_type=q.get("question_type", "main"),
                    evidence_span=q.get("evidence_span", ""),
                ))
            return missed
        except Exception as e:
            logger.error(f"补漏检查失败: {e}")
            return []

    def _create_atomic_question(
        self,
        extracted: ExtractedQuestion,
        chunk: TextChunk,
        extract_pass: ExtractPass,
    ) -> AtomicQuestion:
        """创建原子问题"""
        # 确定问题类型
        q_type = QuestionType.FOLLOWUP if extracted.question_type == "followup" else QuestionType.MAIN

        return AtomicQuestion(
            record_id=chunk.record_id,
            chunk_id=chunk.chunk_id,
            question_text_raw=extracted.question_text,
            question_type=q_type,
            round_hint=extracted.round_hint,
            topic_hint=extracted.topic_hint,
            evidence_text=extracted.evidence_span,
            extract_pass=extract_pass,
            llm_model=self.client.model,
            prompt_version=self.prompt_version,
        )


def run_extract(
    input_file: Path,
    output_file: Path,
    coverage: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """运行问题抽取

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        coverage: 是否进行补漏检查
        limit: 限制处理的分块数量

    Returns:
        统计信息
    """
    extractor = QuestionExtractor(enable_coverage=coverage)

    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    total_chunks = 0
    first_pass_count = 0
    coverage_pass_count = 0
    total_questions = 0

    with open(input_file, encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue

            if limit and total_chunks >= limit:
                break

            chunk_data = json.loads(line)
            chunk = TextChunk(**chunk_data)
            total_chunks += 1

            # 抽取问题
            questions = extractor.extract_questions(chunk)

            for question in questions:
                if question.extract_pass == ExtractPass.FIRST:
                    first_pass_count += 1
                else:
                    coverage_pass_count += 1

                f_out.write(json.dumps(question.model_dump(), cls=JSONEncoder, ensure_ascii=False))
                f_out.write("\n")
                total_questions += 1

            if total_chunks % 10 == 0:
                logger.info(f"已处理 {total_chunks} 个分块，抽取 {total_questions} 个问题")

    logger.info(f"问题抽取完成: {total_chunks}个分块 -> {total_questions}个问题")

    return {
        "total_chunks": total_chunks,
        "first_pass_count": first_pass_count,
        "coverage_pass_count": coverage_pass_count,
        "total_questions": total_questions,
    }
