"""去重模块"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from datetime import datetime
import logging
from pathlib import Path
import threading
from typing import Any
from uuid import UUID

from src.dedupe.candidates import CandidateRecaller
from src.dedupe.judge import DedupeJudge
from src.models import AtomicQuestion, CandidateSource, CanonicalQuestion, DedupePair
from src.settings import settings

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
    recaller = CandidateRecaller(
        use_embedding=use_embedding,
        embedding_threshold=settings.similarity_threshold,
        embedding_top_k=settings.dedupe_embedding_top_k,
    )
    candidates = recaller.recall_candidates(questions)

    logger.info(f"召回 {len(candidates)} 个候选对")

    # 2. 裁决（规则直判 + 并发LLM）
    judge = DedupeJudge(
        confidence_low=settings.dedupe_confidence_low,
        confidence_high=settings.dedupe_confidence_high,
    )
    pairs = []

    # 构建问题映射
    q_map = {q.atomic_question_id: q for q in questions}
    llm_candidates: list[tuple[AtomicQuestion, AtomicQuestion, CandidateSource]] = []
    fast_path_count = 0

    # 2.1 exact/normalized 高精度候选走规则直判，减少不必要的LLM调用
    fast_path_enabled = settings.dedupe_fast_path_exact_normalized
    for qid_a, qid_b, source in candidates:
        q1 = q_map.get(qid_a)
        q2 = q_map.get(qid_b)
        if not q1 or not q2:
            continue

        if (
            fast_path_enabled
            and source in (CandidateSource.EXACT, CandidateSource.NORMALIZED)
        ):
            canonical_text = judge._select_canonical_text([q1, q2], [], {q1.atomic_question_id, q2.atomic_question_id})
            confidence = 0.99 if source == CandidateSource.EXACT else 0.97
            pairs.append(
                DedupePair(
                    qid_a=q1.atomic_question_id,
                    qid_b=q2.atomic_question_id,
                    candidate_source=source,
                    llm_is_duplicate=True,
                    llm_confidence=confidence,
                    llm_reason="规则直判: exact/normalized高精度匹配",
                    canonical_question_candidate=canonical_text,
                    review_flag=False,
                )
            )
            fast_path_count += 1
            continue

        llm_candidates.append((q1, q2, source))

    logger.info(
        "进入LLM裁决: %s 对 (规则直判 %s 对)",
        len(llm_candidates),
        fast_path_count,
    )

    # 2.2 剩余候选并发LLM裁决
    llm_judged = 0
    judge_workers = max(1, settings.dedupe_judge_workers)
    if llm_candidates:
        if judge_workers == 1:
            for i, (q1, q2, source) in enumerate(llm_candidates, 1):
                pair = judge.judge_pair(q1, q2, source)
                pairs.append(pair)
                llm_judged += 1
                if i % 10 == 0 or i == len(llm_candidates):
                    logger.info(
                        "已裁决 %s/%s 个候选对 (fast=%s, llm=%s/%s)",
                        fast_path_count + i,
                        len(candidates),
                        fast_path_count,
                        i,
                        len(llm_candidates),
                    )
        else:
            local_ctx = threading.local()

            def get_thread_judge() -> DedupeJudge:
                j = getattr(local_ctx, "judge", None)
                if j is None:
                    j = DedupeJudge(
                        confidence_low=settings.dedupe_confidence_low,
                        confidence_high=settings.dedupe_confidence_high,
                    )
                    local_ctx.judge = j
                return j

            def judge_one(item: tuple[AtomicQuestion, AtomicQuestion, CandidateSource]) -> DedupePair:
                q1, q2, source = item
                return get_thread_judge().judge_pair(q1, q2, source)

            with ThreadPoolExecutor(max_workers=judge_workers) as executor:
                futures = [executor.submit(judge_one, item) for item in llm_candidates]
                for i, future in enumerate(as_completed(futures), 1):
                    pairs.append(future.result())
                    llm_judged += 1
                    if i % 10 == 0 or i == len(llm_candidates):
                        logger.info(
                            "已裁决 %s/%s 个候选对 (fast=%s, llm=%s/%s, workers=%s)",
                            fast_path_count + i,
                            len(candidates),
                            fast_path_count,
                            i,
                            len(llm_candidates),
                            judge_workers,
                        )

    logger.info(
        "裁决完成: 总候选=%s, fast_path=%s, llm=%s",
        len(candidates),
        fast_path_count,
        llm_judged,
    )

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
        "fast_path_pairs": fast_path_count,
        "llm_judged_pairs": llm_judged,
        "judge_workers": judge_workers,
    }
