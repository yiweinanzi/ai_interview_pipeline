"""知识点分类模块"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import datetime
import logging
from pathlib import Path
import threading
from typing import Any
from uuid import UUID

import yaml

from src.llm import DeepSeekClient, get_client
from src.models import CanonicalQuestion, ClassifiedQuestion, ClassificationResult
from src.settings import settings

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class KnowledgeClassifier:
    """知识点分类器"""

    def __init__(
        self,
        client: DeepSeekClient | None = None,
        taxonomy_path: Path | None = None,
    ):
        self.client = client or get_client()
        self.taxonomy = self._load_taxonomy(taxonomy_path)
        self._system_prompt = None

    def _load_taxonomy(self, path: Path | None) -> dict:
        """加载知识点分类体系"""
        if path is None:
            path = Path(__file__).parent.parent.parent / "configs" / "knowledge_taxonomy.yaml"

        if path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {}

    @property
    def system_prompt(self) -> str:
        """构建分类prompt"""
        if self._system_prompt is None:
            # 构建taxonomy描述
            taxonomy_desc = self._build_taxonomy_description()

            self._system_prompt = f"""你是一个"AI面试知识点分类器"。请根据给定的**知识点分类体系**，对问题进行**多标签分类**。

## 输出格式

输出必须是**json格式**：

```json
{{
  "primary_tag": "nlp_llm",
  "secondary_tags": ["transformer", "attention"],
  "confidence": 0.88,
  "reason": "分类理由"
}}
```

## 知识点分类体系

{taxonomy_desc}

## 分类规则

1. **选择最相关的一级分类作为primary_tag**
2. **可以选择多个相关的secondary_tags**
3. **如果无法确定**：设置 `primary_tag` 为 "uncertain"
4. **常见分类示例**：
   - "Transformer的注意力机制是什么？" → primary: nlp_llm
   - "BatchNorm和LayerNorm的区别" → primary: deep_learning
   - "手撕快速排序" → primary: coding
   - "推荐系统的召回策略" → primary: recsys
"""
        return self._system_prompt

    def _build_taxonomy_description(self) -> str:
        """构建taxonomy描述文本"""
        lines = []

        taxonomy = self.taxonomy.get("taxonomy", {})
        for key, value in taxonomy.items():
            name = value.get("name", key)
            lines.append(f"### {name} ({key})")

            subs = value.get("subcategories", {})
            for sub_key, sub_value in subs.items():
                sub_name = sub_value.get("name", sub_key)
                keywords = sub_value.get("keywords", [])
                lines.append(f"- {sub_name}: {', '.join(keywords[:5])}")

            lines.append("")

        return "\n".join(lines)

    def classify(self, question: CanonicalQuestion) -> ClassifiedQuestion:
        """对问题进行分类"""
        user_prompt = f"## 待分类问题\n\n{question.canonical_question_text}"

        try:
            result = self.client.call_json(
                self.system_prompt,
                user_prompt,
                response_model=ClassificationResult,
            )

            return ClassifiedQuestion(
                canonical_question_id=question.canonical_question_id,
                primary_tag=result.get("primary_tag", "uncertain"),
                secondary_tags=result.get("secondary_tags", []),
                confidence=result.get("confidence"),
                reason=result.get("reason"),
            )
        except Exception as e:
            logger.error(f"分类失败: {e}")
            return ClassifiedQuestion(
                canonical_question_id=question.canonical_question_id,
                primary_tag="uncertain",
                secondary_tags=[],
            )


def run_classify(
    input_file: Path,
    output_file: Path,
) -> dict[str, Any]:
    """运行知识点分类

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径

    Returns:
        统计信息
    """
    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    classifier = KnowledgeClassifier()

    # 加载问题
    questions: list[CanonicalQuestion] = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            questions.append(CanonicalQuestion(**data))

    logger.info(f"加载 {len(questions)} 个问题")

    # 分类（支持并发）
    total_questions = len(questions)
    classified: list[CanonicalQuestion] = []
    tag_stats: dict[str, int] = {}
    workers = max(1, settings.classify_workers)

    if workers == 1 or total_questions <= 1:
        for i, question in enumerate(questions):
            result = classifier.classify(question)
            question.primary_tag = result.primary_tag
            question.secondary_tags = result.secondary_tags
            classified.append(question)
            tag_stats[result.primary_tag] = tag_stats.get(result.primary_tag, 0) + 1
            if (i + 1) % 10 == 0 or (i + 1) == total_questions:
                logger.info(f"已分类 {i + 1}/{total_questions} 个问题")
    else:
        local_ctx = threading.local()
        classified_slots: list[CanonicalQuestion | None] = [None] * total_questions

        def get_thread_classifier() -> KnowledgeClassifier:
            inst = getattr(local_ctx, "classifier", None)
            if inst is None:
                inst = KnowledgeClassifier()
                local_ctx.classifier = inst
            return inst

        def classify_one(item: tuple[int, CanonicalQuestion]) -> tuple[int, ClassifiedQuestion]:
            idx, question = item
            result = get_thread_classifier().classify(question)
            return idx, result

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(classify_one, (i, q))
                for i, q in enumerate(questions)
            ]
            for done, future in enumerate(as_completed(futures), 1):
                idx, result = future.result()
                question = questions[idx]
                question.primary_tag = result.primary_tag
                question.secondary_tags = result.secondary_tags
                classified_slots[idx] = question
                tag_stats[result.primary_tag] = tag_stats.get(result.primary_tag, 0) + 1

                if done % 20 == 0 or done == total_questions:
                    logger.info(
                        "已分类 %s/%s 个问题 (workers=%s)",
                        done,
                        total_questions,
                        workers,
                    )

        classified = [q for q in classified_slots if q is not None]

    # 写入输出
    with open(output_file, "w", encoding="utf-8") as f:
        for cq in classified:
            f.write(json.dumps(cq.model_dump(), cls=JSONEncoder, ensure_ascii=False))
            f.write("\n")

    logger.info(f"分类完成: {tag_stats}")

    return {
        "total_questions": total_questions,
        "tag_stats": tag_stats,
    }
