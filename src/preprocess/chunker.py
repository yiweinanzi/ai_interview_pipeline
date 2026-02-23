"""文本切分器"""

import json
from datetime import datetime
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from src.models import InterviewRecord, TextChunk
from src.settings import settings

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    """支持UUID和datetime的JSON编码器"""

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class TextChunker:
    """文本切分器

    支持按段落切分，带重叠，防止跨块问题被截断
    """

    def __init__(
        self,
        chunk_size: int = 3000,
        chunk_overlap: int = 300,
        min_chunk_size: int = 500,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_text(self, text: str) -> list[dict[str, Any]]:
        """将文本切分成多个块

        Args:
            text: 输入文本

        Returns:
            切分结果列表，每个元素包含 {text, char_start, char_end}
        """
        if not text:
            return []

        # 按段落分割
        paragraphs = self._split_paragraphs(text)

        chunks = []
        current_chunk = []
        current_length = 0
        char_start = 0

        for para in paragraphs:
            para_length = len(para)

            # 如果单个段落超过chunk_size，需要进一步切分
            if para_length > self.chunk_size:
                # 先保存当前chunk
                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append({
                        "text": chunk_text,
                        "char_start": char_start,
                        "char_end": char_start + len(chunk_text),
                    })
                    char_start += len(chunk_text) - self.chunk_overlap
                    current_chunk = []
                    current_length = 0

                # 切分大段落
                sub_chunks = self._split_large_paragraph(para, char_start)
                chunks.extend(sub_chunks)
                if sub_chunks:
                    char_start = sub_chunks[-1]["char_end"] - self.chunk_overlap

            elif current_length + para_length > self.chunk_size and current_chunk:
                # 当前chunk满了，保存它
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({
                    "text": chunk_text,
                    "char_start": char_start,
                    "char_end": char_start + len(chunk_text),
                })

                # 计算overlap
                char_start = max(char_start, char_start + len(chunk_text) - self.chunk_overlap)

                # 保留最后几个段落作为overlap
                overlap_paras, overlap_length = self._get_overlap_paragraphs(
                    current_chunk,
                    self.chunk_overlap,
                )

                current_chunk = overlap_paras + [para]
                current_length = overlap_length + para_length

            else:
                current_chunk.append(para)
                current_length += para_length + 2  # +2 for "\n\n"

        # 保存最后一个chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            # 只有不满足min_chunk_size且前面有chunk时才合并
            if len(chunk_text) < self.min_chunk_size and chunks:
                # 将最后一个小块合并到前一个chunk
                # 但这里我们选择保留它，以免丢失内容
                pass
            chunks.append({
                "text": chunk_text,
                "char_start": char_start,
                "char_end": char_start + len(chunk_text),
            })

        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """将文本分割成段落"""
        # 按空行分割
        paragraphs = text.split("\n\n")
        # 过滤空段落并清理
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_large_paragraph(
        self,
        para: str,
        start_pos: int,
    ) -> list[dict[str, Any]]:
        """切分过大的段落"""
        chunks = []
        sentences = self._split_sentences(para)

        current_chunk = []
        current_length = 0
        char_start = start_pos

        for sentence in sentences:
            sent_length = len(sentence)

            if current_length + sent_length > self.chunk_size and current_chunk:
                chunk_text = "".join(current_chunk)
                chunks.append({
                    "text": chunk_text,
                    "char_start": char_start,
                    "char_end": char_start + len(chunk_text),
                })
                char_start = char_start + len(chunk_text) - self.chunk_overlap

                # overlap处理
                overlap_text = chunk_text[-self.chunk_overlap:] if len(chunk_text) > self.chunk_overlap else chunk_text
                current_chunk = [overlap_text, sentence]
                current_length = len(overlap_text) + sent_length
            else:
                current_chunk.append(sentence)
                current_length += sent_length

        if current_chunk:
            chunk_text = "".join(current_chunk)
            chunks.append({
                "text": chunk_text,
                "char_start": char_start,
                "char_end": char_start + len(chunk_text),
            })

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """将文本分割成句子"""
        import re

        # 中文和英文句子分割
        # 匹配句号、问号、感叹号（中英文）
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        return [s.strip() for s in sentences if s.strip()]

    def _get_overlap_paragraphs(
        self,
        paragraphs: list[str],
        overlap_size: int,
    ) -> tuple[list[str], int]:
        """获取重叠部分的段落"""
        overlap_paras = []
        overlap_length = 0

        # 从后往前取段落直到满足overlap大小
        for para in reversed(paragraphs):
            if overlap_length + len(para) > overlap_size and overlap_paras:
                break
            overlap_paras.insert(0, para)
            overlap_length += len(para) + 2

        return overlap_paras, overlap_length


def run_chunk(
    input_file: Path,
    output_file: Path,
    chunk_size: int = 3000,
    overlap: int = 300,
) -> dict[str, Any]:
    """运行文本切分

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径
        chunk_size: 分块大小
        overlap: 重叠大小

    Returns:
        统计信息
    """
    chunker = TextChunker(chunk_size=chunk_size, chunk_overlap=overlap)

    # 确保输出目录存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    total_records = 0
    total_chunks = 0

    with open(input_file, encoding="utf-8") as f_in, open(output_file, "w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue

            record_data = json.loads(line)
            record = InterviewRecord(**record_data)
            total_records += 1

            # 切分文本
            text = record.text_clean or record.text_raw
            chunk_results = chunker.chunk_text(text)

            for idx, chunk_info in enumerate(chunk_results):
                chunk = TextChunk(
                    record_id=record.record_id,
                    chunk_index=idx,
                    char_start=chunk_info["char_start"],
                    char_end=chunk_info["char_end"],
                    chunk_text=chunk_info["text"],
                )
                f_out.write(json.dumps(chunk.model_dump(), cls=JSONEncoder, ensure_ascii=False))
                f_out.write("\n")
                total_chunks += 1

    logger.info(f"文本切分完成: {total_records}条记录 -> {total_chunks}个分块")

    return {
        "total_records": total_records,
        "total_chunks": total_chunks,
    }
