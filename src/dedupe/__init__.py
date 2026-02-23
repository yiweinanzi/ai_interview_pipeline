"""去重模块"""

import json
from datetime import datetime
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from src.dedupe.candidates import CandidateRecaller
from src.dedupe.judge import DedupeJudge
from src.models import AtomicQuestion, CanonicalQuestion

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def run_dedupe(
    input_file: Path,
    output_file: Path,
    use_embedding: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """运行去重流程

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        use_embedding: 是否使用向量召回
        limit: 限制处理的问题数量

    Returns:
        统计信息
    """
    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 加载问题
    questions: list[AtomicQuestion] = []
    with open(input_file, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            if limit and i >= limit:
                break
            data = json.loads(line)
            questions.append(AtomicQuestion(**data))

    logger.info(f"加载 {len(questions)} 个问题")

    # 1. 候选召回
    recaller = CandidateRecaller(use_embedding=use_embedding)
    candidates = recaller.recall_candidates(questions)

    logger.info(f"召回 {len(candidates)} 个候选对")

    # 2. LLM裁决
    judge = DedupeJudge()
    pairs = []

    # 构建问题映射
    q_map = {q.atomic_question_id: q for q in questions}

    for i, (qid_a, qid_b, source) in enumerate(candidates):
        q1 = q_map.get(qid_a)
        q2 = q_map.get(qid_b)

        if not q1 or not q2:
            continue

        pair = judge.judge_pair(q1, q2, source)
        pairs.append(pair)

        if (i + 1) % 10 == 0:
            logger.info(f"已裁决 {i + 1}/{len(candidates)} 个候选对")

    # 3. 构建canonical questions
    canonical_questions, review_questions = judge.build_canonical_questions(questions, pairs)

    logger.info(f"生成 {len(canonical_questions)} 个确定问题，{len(review_questions)} 个需复核")

    # 4. 写入输出
    with open(output_file, "w", encoding="utf-8") as f:
        for cq in canonical_questions:
            f.write(json.dumps(cq.model_dump(), cls=JSONEncoder, ensure_ascii=False))
            f.write("\n")

    # 写入复核队列
    review_file = output_file.parent / "review_queue.jsonl"
    with open(review_file, "w", encoding="utf-8") as f:
        for cq in review_questions:
            f.write(json.dumps(cq.model_dump(), cls=JSONEncoder, ensure_ascii=False))
            f.write("\n")

    return {
        "total_questions": len(questions),
        "candidate_pairs": len(candidates),
        "canonical_count": len(canonical_questions),
        "review_count": len(review_questions),
    }
