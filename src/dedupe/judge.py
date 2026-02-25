"""LLM去重裁决模块"""

import json
import logging
from typing import Any
from uuid import UUID

from src.llm import DeepSeekClient, get_client
from src.models import (
    AtomicQuestion,
    CanonicalQuestion,
    CandidateSource,
    DedupeJudgeResult,
    DedupePair,
)
from src.settings import settings

logger = logging.getLogger(__name__)


# Prompt模板
SYSTEM_PROMPT_DEDUPE = """你是一个"面试问题去重裁判"。请判断下面**两个问题**是否**本质上是同一个问题**。

## 输出格式

输出必须是**json格式**：

```json
{
  "is_duplicate": true,
  "confidence": 0.92,
  "same_concept_reason": "为什么认为是同一个问题",
  "difference_reason": "如果不同，说明差异在哪里",
  "canonical_question": "统一后的标准问题表述",
  "knowledge_tags": ["知识点标签1", "知识点标签2"]
}
```

## 判定规则

### 算作重复的情况
- 表述不同但语义等价
- "Transformer的注意力机制是什么？" vs "讲一下Transformer的Attention"
- "BN和LN的区别" vs "BatchNorm和LayerNorm有什么不同"

### 不算重复的情况
1. **侧重点不同**："BatchNorm原理" vs "BatchNorm训练和推理的区别"
2. **场景约束不同**："推荐系统中的冷启动" vs "冷启动问题"
3. **追问vs主问题**："Transformer的结构" vs "Transformer为什么用Pre-Norm"
4. **答案结构明显不同**
"""


class UnionFind:
    """并查集实现，用于聚类重复问题"""

    def __init__(self):
        self.parent: dict[UUID, UUID] = {}
        self.rank: dict[UUID, int] = {}

    def find(self, x: UUID) -> UUID:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # 路径压缩
        return self.parent[x]

    def union(self, x: UUID, y: UUID):
        px = self.find(x)
        py = self.find(y)
        if px == py:
            return

        # 按秩合并
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1

    def get_clusters(self) -> dict[UUID, list[UUID]]:
        """获取所有聚类"""
        clusters: dict[UUID, list[UUID]] = {}
        for x in self.parent:
            root = self.find(x)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(x)
        return clusters


class DedupeJudge:
    """去重裁决器"""

    def __init__(
        self,
        client: DeepSeekClient | None = None,
        confidence_low: float = 0.55,
        confidence_high: float = 0.80,
    ):
        self.client = client or get_client()
        self.confidence_low = confidence_low
        self.confidence_high = confidence_high

    def judge_pair(
        self,
        q1: AtomicQuestion,
        q2: AtomicQuestion,
        source: CandidateSource = CandidateSource.FUZZY,
    ) -> DedupePair:
        """裁决一对问题是否重复"""
        text1 = q1.question_text_norm or q1.question_text_raw
        text2 = q2.question_text_norm or q2.question_text_raw

        user_prompt = f"""## 问题A

{text1}

## 问题B

{text2}
"""
        try:
            result = self.client.call_json(
                SYSTEM_PROMPT_DEDUPE,
                user_prompt,
                response_model=DedupeJudgeResult,
                # 裁决结果结构固定且较短，限制输出长度可显著降低时延/解析失败概率
                max_tokens=512,
            )

            is_duplicate = result.get("is_duplicate", False)
            confidence = result.get("confidence", 0.5)

            # 判断是否需要复核
            review_flag = (
                is_duplicate
                and self.confidence_low <= confidence < self.confidence_high
            )

            return DedupePair(
                qid_a=q1.atomic_question_id,
                qid_b=q2.atomic_question_id,
                candidate_source=source,
                llm_is_duplicate=is_duplicate,
                llm_confidence=confidence,
                llm_reason=result.get("same_concept_reason") or result.get("difference_reason"),
                canonical_question_candidate=result.get("canonical_question"),
                knowledge_tags=result.get("knowledge_tags", []),
                review_flag=review_flag,
            )
        except Exception as e:
            logger.error(f"LLM裁决失败: {e}")
            return DedupePair(
                qid_a=q1.atomic_question_id,
                qid_b=q2.atomic_question_id,
                candidate_source=source,
                review_flag=True,  # 失败的进入复核
            )

    def build_canonical_questions(
        self,
        questions: list[AtomicQuestion],
        pairs: list[DedupePair],
    ) -> tuple[list[CanonicalQuestion], list[CanonicalQuestion]]:
        """构建规范化问题

        Args:
            questions: 所有问题
            pairs: 裁决结果

        Returns:
            (确定的问题列表, 需要复核的问题列表)
        """
        # 构建问题ID到问题的映射
        q_map = {q.atomic_question_id: q for q in questions}

        # 使用并查集聚类
        uf = UnionFind()

        # 只合并确定为重复的（高置信度）
        for pair in pairs:
            if pair.llm_is_duplicate and pair.llm_confidence >= self.confidence_high:
                uf.union(pair.qid_a, pair.qid_b)

        # 获取聚类结果
        clusters = uf.get_clusters()

        # 处理未聚类的单元素
        for q in questions:
            if q.atomic_question_id not in uf.parent:
                clusters[q.atomic_question_id] = [q.atomic_question_id]

        # 预计算：复核成员索引 + canonical候选索引，避免每个cluster重复扫描全部pairs
        review_member_ids: set[UUID] = set()
        canonical_hint_by_member: dict[UUID, str] = {}
        for pair in pairs:
            if pair.review_flag:
                review_member_ids.add(pair.qid_a)
                review_member_ids.add(pair.qid_b)

            if (
                pair.canonical_question_candidate
                and pair.llm_is_duplicate
                and pair.llm_confidence is not None
                and pair.llm_confidence >= self.confidence_high
            ):
                canonical_hint_by_member.setdefault(
                    pair.qid_a,
                    pair.canonical_question_candidate,
                )
                canonical_hint_by_member.setdefault(
                    pair.qid_b,
                    pair.canonical_question_candidate,
                )

        # 构建canonical questions
        canonical_questions = []
        review_questions = []

        for root, members in clusters.items():
            member_questions = [q_map[mid] for mid in members if mid in q_map]
            if not member_questions:
                continue

            # 找到最佳canonical表述
            canonical_text = ""
            for mid in members:
                hint = canonical_hint_by_member.get(mid)
                if hint:
                    canonical_text = hint
                    break
            if not canonical_text:
                canonical_text = self._select_canonical_text(
                    member_questions,
                    [],
                    member_ids=set(members),
                )

            # 收集公司信息
            companies = list(set(
                q_map[mid].round_hint or "未知"
                for mid in members if mid in q_map
            ))

            # 收集变体
            variants = list(set(
                q.question_text_raw
                for q in member_questions
            ))

            cq = CanonicalQuestion(
                canonical_question_text=canonical_text,
                member_count=len(members),
                member_ids=members,
                company_count=len(companies),
                companies=companies,
                variants=variants[:10],  # 最多保留10个变体
                source_refs=[
                    str(q_map[mid].record_id)
                    for mid in members if mid in q_map
                ],
            )

            # 检查是否需要复核（低置信度合并）
            needs_review = any(mid in review_member_ids for mid in members)

            if needs_review:
                review_questions.append(cq)
            else:
                canonical_questions.append(cq)

        return canonical_questions, review_questions

    def _select_canonical_text(
        self,
        questions: list[AtomicQuestion],
        pairs: list[DedupePair],
        member_ids: set[UUID] | None = None,
    ) -> str:
        """选择最佳的canonical表述"""
        if member_ids is None:
            member_ids = {q.atomic_question_id for q in questions}

        # 优先使用LLM生成的canonical
        for pair in pairs:
            if (
                pair.canonical_question_candidate
                and pair.qid_a in member_ids
                and pair.qid_b in member_ids
            ):
                return pair.canonical_question_candidate

        # 否则选择最长的表述（通常更完整）
        if questions:
            return max(questions, key=lambda q: len(q.question_text_raw)).question_text_raw

        return ""
