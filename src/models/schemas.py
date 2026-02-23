"""Pydantic数据模型定义"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """数据来源类型"""

    MARKDOWN = "markdown"
    CSV = "csv"
    EXCEL = "excel"
    WEB = "web"


class QuestionType(str, Enum):
    """问题类型"""

    MAIN = "main"
    FOLLOWUP = "followup"


class ExtractPass(str, Enum):
    """抽取轮次"""

    FIRST = "first"
    COVERAGE = "coverage"


# ============ 原始数据模型 ============


class InterviewRecord(BaseModel):
    """原始面经记录"""

    record_id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    source_path: str
    source_url: str | None = None
    source_title: str | None = None

    # 公司信息
    company_raw: str | None = None
    company_norm: str | None = None

    # 岗位信息
    role_raw: str | None = None
    role_norm: str | None = None

    # 时间信息
    interview_date_raw: str | None = None
    interview_date_norm: datetime | None = None

    # 候选人信息
    candidate_level_raw: str | None = None  # 校招/社招/实习
    location_raw: str | None = None

    # 文本内容
    text_raw: str  # 完整原文（必须保留）
    text_clean: str | None = None  # 清洗后文本

    # 元数据
    ingest_meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


# ============ 切分模型 ============


class TextChunk(BaseModel):
    """文本分块"""

    chunk_id: UUID = Field(default_factory=uuid4)
    record_id: UUID
    chunk_index: int
    char_start: int
    char_end: int
    chunk_text: str
    created_at: datetime = Field(default_factory=datetime.now)


# ============ 原子问题模型 ============


class AtomicQuestion(BaseModel):
    """原子问题"""

    atomic_question_id: UUID = Field(default_factory=uuid4)
    record_id: UUID
    chunk_id: UUID

    # 问题文本
    question_text_raw: str
    question_text_norm: str | None = None

    # 问题分类
    question_type: QuestionType = QuestionType.MAIN

    # 上下文提示
    round_hint: str | None = None  # 一面/二面/HR面
    topic_hint: list[str] = Field(default_factory=list)

    # 证据追溯
    evidence_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    # 抽取信息
    extract_pass: ExtractPass = ExtractPass.FIRST
    llm_model: str | None = None
    prompt_version: str | None = None
    confidence_extract: float | None = None

    created_at: datetime = Field(default_factory=datetime.now)


# ============ 去重模型 ============


class CandidateSource(str, Enum):
    """候选对来源"""

    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"
    EMBEDDING = "embedding"


class DedupePair(BaseModel):
    """去重候选对"""

    pair_id: UUID = Field(default_factory=uuid4)
    qid_a: UUID
    qid_b: UUID
    candidate_source: CandidateSource

    # LLM裁决结果
    llm_is_duplicate: bool | None = None
    llm_confidence: float | None = None
    llm_reason: str | None = None
    canonical_question_candidate: str | None = None
    knowledge_tags: list[str] = Field(default_factory=list)

    # 复核标记
    review_flag: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class CanonicalQuestion(BaseModel):
    """规范化问题（去重后）"""

    canonical_question_id: UUID = Field(default_factory=uuid4)
    canonical_question_text: str

    # 聚类成员
    member_count: int = 1
    member_ids: list[UUID] = Field(default_factory=list)

    # 统计信息
    company_count: int = 0
    companies: list[str] = Field(default_factory=list)
    variants: list[str] = Field(default_factory=list)  # 变体问法
    source_refs: list[str] = Field(default_factory=list)  # 来源记录

    # 知识点分类
    primary_tag: str | None = None
    secondary_tags: list[str] = Field(default_factory=list)

    # 置信度统计
    avg_confidence: float | None = None
    merge_confidence_stats: dict[str, float] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=datetime.now)


# ============ 分类模型 ============


class ClassifiedQuestion(BaseModel):
    """分类后的问题"""

    canonical_question_id: UUID
    primary_tag: str
    secondary_tags: list[str] = Field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
    classified_at: datetime = Field(default_factory=datetime.now)


# ============ 审计模型 ============


class CoverageAudit(BaseModel):
    """覆盖率审计记录"""

    record_id: UUID
    has_atomic_questions: bool = False
    atomic_count: int = 0
    coverage_status: str = "pending"  # pending/covered/failed
    notes: str | None = None


class RunAudit(BaseModel):
    """运行审计报告"""

    # 基础统计
    total_records: int = 0
    total_chunks: int = 0
    total_atomic_questions: int = 0
    first_pass_questions: int = 0
    coverage_pass_questions: int = 0
    canonical_questions: int = 0

    # 覆盖率
    source_coverage_rate: float = 0.0

    # 错误统计
    extraction_failures: int = 0
    llm_empty_responses: int = 0
    error_codes: dict[str, int] = Field(default_factory=dict)

    # 未覆盖记录
    uncovered_records: list[str] = Field(default_factory=list)

    # 运行信息
    run_id: UUID = Field(default_factory=uuid4)
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None


# ============ LLM输出模型 ============


class ExtractedQuestion(BaseModel):
    """LLM抽取的单个问题"""

    question_text: str
    question_type: str = "main"
    round_hint: str | None = None
    topic_hint: list[str] = Field(default_factory=list)
    evidence_span: str
    is_multi_part: bool = False


class ExtractionResult(BaseModel):
    """LLM抽取结果"""

    questions: list[ExtractedQuestion] = Field(default_factory=list)


class MissedQuestion(BaseModel):
    """补漏检查发现的遗漏问题"""

    question_text: str
    question_type: str = "main"
    evidence_span: str
    reason: str


class CoverageCheckResult(BaseModel):
    """补漏检查结果"""

    missed_questions: list[MissedQuestion] = Field(default_factory=list)


class DedupeJudgeResult(BaseModel):
    """去重裁决结果"""

    is_duplicate: bool
    confidence: float
    same_concept_reason: str | None = None
    difference_reason: str | None = None
    canonical_question: str | None = None
    knowledge_tags: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    """知识点分类结果"""

    primary_tag: str
    secondary_tags: list[str] = Field(default_factory=list)
    confidence: float | None = None
    reason: str | None = None
