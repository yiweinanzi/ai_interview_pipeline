"""候选召回模块"""

import logging
from typing import Any
from uuid import UUID

import numpy as np
from rapidfuzz import fuzz

from src.llm import EmbeddingModel, get_embedding_model
from src.models import AtomicQuestion, CandidateSource

logger = logging.getLogger(__name__)


class CandidateRecaller:
    """候选召回器

    使用多层策略召回可能重复的问题对：
    1. 精确匹配
    2. 标准化后匹配
    3. 模糊相似度匹配
    4. 向量相似度匹配
    """

    def __init__(
        self,
        fuzzy_threshold: int = 85,
        embedding_threshold: float = 0.85,
        embedding_top_k: int = 50,
        use_embedding: bool = True,
    ):
        self.fuzzy_threshold = fuzzy_threshold
        self.embedding_threshold = embedding_threshold
        self.embedding_top_k = embedding_top_k
        self.use_embedding = use_embedding
        self._embedding_model = None

    @property
    def embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = get_embedding_model()
        return self._embedding_model

    def recall_candidates(
        self,
        questions: list[AtomicQuestion],
    ) -> list[tuple[UUID, UUID, CandidateSource]]:
        """召回候选问题对

        Args:
            questions: 问题列表

        Returns:
            候选对列表 [(qid_a, qid_b, source), ...]
        """
        candidates = []
        seen_pairs: set[tuple[UUID, UUID]] = set()

        # 1. 精确匹配
        exact_pairs = self._exact_match(questions)
        for pair in exact_pairs:
            if self._add_pair(pair, seen_pairs):
                candidates.append((pair[0], pair[1], CandidateSource.EXACT))

        logger.info(f"精确匹配: {len(exact_pairs)} 对")

        # 2. 标准化后匹配
        norm_pairs = self._normalized_match(questions)
        for pair in norm_pairs:
            if self._add_pair(pair, seen_pairs):
                candidates.append((pair[0], pair[1], CandidateSource.NORMALIZED))

        logger.info(f"标准化匹配: {len(norm_pairs)} 对 (累计 {len(candidates)})")

        # 3. 模糊相似度匹配
        fuzzy_pairs = self._fuzzy_match(questions, seen_pairs)
        for pair in fuzzy_pairs:
            if self._add_pair(pair, seen_pairs):
                candidates.append((pair[0], pair[1], CandidateSource.FUZZY))

        logger.info(f"模糊匹配: {len(fuzzy_pairs)} 对 (累计 {len(candidates)})")

        # 4. 向量相似度匹配
        if self.use_embedding:
            embedding_pairs = self._embedding_match(questions, seen_pairs)
            for pair in embedding_pairs:
                if self._add_pair(pair, seen_pairs):
                    candidates.append((pair[0], pair[1], CandidateSource.EMBEDDING))

            logger.info(f"向量匹配: {len(embedding_pairs)} 对 (累计 {len(candidates)})")

        return candidates

    def _add_pair(
        self,
        pair: tuple[UUID, UUID],
        seen: set[tuple[UUID, UUID]],
    ) -> bool:
        """添加候选对（避免重复）"""
        # 统一顺序
        key = (min(pair), max(pair))
        if key in seen:
            return False
        seen.add(key)
        return True

    def _exact_match(
        self,
        questions: list[AtomicQuestion],
    ) -> list[tuple[UUID, UUID]]:
        """精确匹配"""
        pairs = []
        text_to_ids: dict[str, list[UUID]] = {}

        for q in questions:
            text = q.question_text_raw.strip().lower()
            if text not in text_to_ids:
                text_to_ids[text] = []
            text_to_ids[text].append(q.atomic_question_id)

        for ids in text_to_ids.values():
            if len(ids) > 1:
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        pairs.append((ids[i], ids[j]))

        return pairs

    def _normalized_match(
        self,
        questions: list[AtomicQuestion],
    ) -> list[tuple[UUID, UUID]]:
        """标准化后匹配"""
        pairs = []
        norm_to_ids: dict[str, list[UUID]] = {}

        for q in questions:
            # 使用标准化后的文本，如果没有则使用原文
            text = (q.question_text_norm or q.question_text_raw)
            # 进一步标准化：去除标点、空格
            norm_text = self._normalize_for_comparison(text)

            if norm_text not in norm_to_ids:
                norm_to_ids[norm_text] = []
            norm_to_ids[norm_text].append(q.atomic_question_id)

        for ids in norm_to_ids.values():
            if len(ids) > 1:
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        pairs.append((ids[i], ids[j]))

        return pairs

    def _normalize_for_comparison(self, text: str) -> str:
        """为比较而标准化文本"""
        import re

        # 转小写
        text = text.lower()
        # 去除标点
        text = re.sub(r"[^\w\s]", "", text)
        # 去除空格
        text = re.sub(r"\s+", "", text)
        return text

    def _fuzzy_match(
        self,
        questions: list[AtomicQuestion],
        seen: set[tuple[UUID, UUID]],
    ) -> list[tuple[UUID, UUID]]:
        """模糊相似度匹配"""
        pairs = []

        # 对较短的问题列表进行全量比对
        if len(questions) <= 1000:
            for i in range(len(questions)):
                for j in range(i + 1, len(questions)):
                    q1 = questions[i]
                    q2 = questions[j]

                    # 跳过已经匹配的
                    key = (min(q1.atomic_question_id, q2.atomic_question_id),
                           max(q1.atomic_question_id, q2.atomic_question_id))
                    if key in seen:
                        continue

                    # 计算相似度
                    text1 = q1.question_text_norm or q1.question_text_raw
                    text2 = q2.question_text_norm or q2.question_text_raw
                    similarity = fuzz.ratio(text1, text2)

                    if similarity >= self.fuzzy_threshold:
                        pairs.append((q1.atomic_question_id, q2.atomic_question_id))

        return pairs

    def _embedding_match(
        self,
        questions: list[AtomicQuestion],
        seen: set[tuple[UUID, UUID]],
    ) -> list[tuple[UUID, UUID]]:
        """向量相似度匹配"""
        pairs = []

        # 提取文本
        texts = [
            q.question_text_norm or q.question_text_raw
            for q in questions
        ]

        # 计算嵌入
        logger.info("计算问题向量嵌入...")
        embeddings = self.embedding_model.encode(texts)

        # 计算相似度矩阵（使用批量计算优化）
        logger.info("计算相似度矩阵...")

        # 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / (norms + 1e-8)

        # 批量计算相似度
        for i in range(len(questions)):
            similarities = np.dot(normalized, normalized[i])

            # 找到相似度超过阈值的
            for j in range(i + 1, len(questions)):
                key = (
                    min(questions[i].atomic_question_id, questions[j].atomic_question_id),
                    max(questions[i].atomic_question_id, questions[j].atomic_question_id),
                )
                if key in seen:
                    continue

                if similarities[j] >= self.embedding_threshold:
                    pairs.append((questions[i].atomic_question_id, questions[j].atomic_question_id))

        return pairs
