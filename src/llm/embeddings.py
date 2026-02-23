"""向量嵌入模块"""

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel

from src.settings import settings

logger = logging.getLogger(__name__)


class EmbeddingResult(BaseModel):
    """嵌入结果"""

    text: str
    embedding: list[float]
    model: str
    dimension: int


class EmbeddingModel:
    """向量嵌入模型封装

    支持本地模型进行语义相似度计算
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ):
        self.model_name = model_name or settings.embedding_model
        self.device = device or settings.embedding_device
        self._model = None
        self._dimension = None

    def _load_model(self):
        """延迟加载模型"""
        if self._model is not None:
            return

        logger.info(f"加载嵌入模型: {self.model_name}")

        try:
            # 使用sentence-transformers（兼容性更好）
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                trust_remote_code=True,
            )
            self._dimension = self._model.get_sentence_embedding_dimension()
            self._model_type = "st"

            logger.info(f"模型加载完成，维度: {self._dimension}")

        except ImportError as e:
            logger.warning(f"无法加载嵌入模型依赖: {e}")
            logger.warning("将使用简单的TF-IDF相似度作为后备方案")
            self._model = None
            self._model_type = "fallback"

    def encode(self, texts: str | list[str]) -> np.ndarray:
        """编码文本为向量

        Args:
            texts: 单个文本或文本列表

        Returns:
            向量数组，shape为(n, dimension)或(dimension,)
        """
        self._load_model()

        if isinstance(texts, str):
            texts = [texts]
            single = True
        else:
            single = False

        if self._model is None:
            # 后备方案：使用简单的词频向量
            return self._fallback_encode(texts, single)

        # SentenceTransformer编码
        embeddings = self._model.encode(texts, convert_to_numpy=True)

        if single:
            return embeddings[0]
        return embeddings

    def _fallback_encode(self, texts: list[str], single: bool) -> np.ndarray:
        """后备编码方案：基于词频的简单向量"""
        from collections import Counter
        from math import log

        # 构建词表
        all_words = set()
        for text in texts:
            all_words.update(text.lower().split())

        word_list = sorted(all_words)
        word_to_idx = {w: i for i, w in enumerate(word_list)}
        dim = len(word_list)

        # 计算TF-IDF风格的向量
        embeddings = []
        for text in texts:
            words = text.lower().split()
            counter = Counter(words)
            vec = np.zeros(dim)
            for word, count in counter.items():
                if word in word_to_idx:
                    # 简化的TF
                    vec[word_to_idx[word]] = count / len(words) if words else 0
            # L2归一化
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)

        result = np.array(embeddings)
        if single:
            return result[0]
        return result

    def similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算余弦相似度"""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

    def batch_similarity(
        self,
        query_vec: np.ndarray,
        corpus_vecs: np.ndarray,
    ) -> np.ndarray:
        """批量计算相似度

        Args:
            query_vec: 查询向量 (dimension,)
            corpus_vecs: 语料向量 (n, dimension)

        Returns:
            相似度数组 (n,)
        """
        # L2归一化
        query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        corpus_norms = corpus_vecs / (np.linalg.norm(corpus_vecs, axis=1, keepdims=True) + 1e-8)

        # 批量点积
        return np.dot(corpus_norms, query_norm)

    def get_dimension(self) -> int:
        """获取向量维度"""
        self._load_model()
        return self._dimension or 768


# 全局嵌入模型实例
_embedding_model: EmbeddingModel | None = None


def get_embedding_model() -> EmbeddingModel:
    """获取全局嵌入模型实例"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = EmbeddingModel()
    return _embedding_model
