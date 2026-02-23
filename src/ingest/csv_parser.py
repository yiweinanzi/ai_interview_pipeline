"""CSV/Excel文件���析器"""

import logging
import re
from io import StringIO
from pathlib import Path

import pandas as pd

from src.models import InterviewRecord, SourceType

logger = logging.getLogger(__name__)


def parse_csv_file(file_path: Path) -> list[InterviewRecord]:
    """解析CSV格式的面经文件

    适用于 else/实习2.csv 等结构化数据

    Args:
        file_path: 文件路径

    Returns:
        InterviewRecord列表
    """
    try:
        # 尝试不同编码
        for encoding in ["utf-8", "gbk", "gb2312"]:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            logger.error(f"无法解析CSV文件编码: {file_path}")
            return []
    except Exception as e:
        logger.error(f"读取CSV文件失败: {file_path}, 错误: {e}")
        return []

    records = []

    # 获取列名
    columns = df.columns.tolist()

    for idx, row in df.iterrows():
        # 尝试提取公司名
        company_raw = None
        for col in ["公司名称", "公司", "company"]:
            if col in columns and pd.notna(row[col]):
                company_raw = str(row[col])
                break

        # 尝试提取岗位
        role_raw = None
        for col in ["岗位方向", "岗位", "role", "职位"]:
            if col in columns and pd.notna(row[col]):
                role_raw = str(row[col])
                break

        # 尝试提取面试轮次
        round_info = None
        for col in ["面试轮次", "轮次", "round"]:
            if col in columns and pd.notna(row[col]):
                round_info = str(row[col])
                break

        # 尝试提取日期
        date_raw = None
        for col in ["面试时间", "时间", "date", "日期"]:
            if col in columns and pd.notna(row[col]):
                date_raw = str(row[col])
                break

        # 尝试提取核心问题
        questions_text = None
        for col in ["核心面试问题", "面试问题", "问题", "questions"]:
            if col in columns and pd.notna(row[col]):
                questions_text = str(row[col])
                break

        # 尝试提取结果
        result = None
        for col in ["面试结果", "结果", "result"]:
            if col in columns and pd.notna(row[col]):
                result = str(row[col])
                break

        if not questions_text:
            continue

        # 构建完整文本
        text_parts = []
        if round_info:
            text_parts.append(f"面试轮次: {round_info}")
        if questions_text:
            text_parts.append(f"面试问题:\n{questions_text}")

        text_raw = "\n\n".join(text_parts)

        record = InterviewRecord(
            source_type=SourceType.CSV,
            source_path=str(file_path),
            source_title=f"{company_raw or '未知公司'}-{role_raw or '面试'}",
            company_raw=company_raw,
            role_raw=role_raw,
            interview_date_raw=date_raw,
            text_raw=text_raw,
            text_clean=clean_csv_text(text_raw),
            ingest_meta={
                "parser": "csv",
                "row_index": idx,
                "round": round_info,
                "result": result,
                "columns": columns,
            },
        )
        records.append(record)

    return records


def parse_excel_file(file_path: Path) -> list[InterviewRecord]:
    """解析Excel格式的面经文件

    Args:
        file_path: 文件路径

    Returns:
        InterviewRecord列表
    """
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        logger.error(f"读取Excel文件失败: {file_path}, 错误: {e}")
        return []

    records = []
    columns = df.columns.tolist()

    for idx, row in df.iterrows():
        # 提取各字段
        company_raw = extract_field(row, columns, ["公司名称", "公司", "company"])
        role_raw = extract_field(row, columns, ["岗位方向", "岗位", "role", "职位"])
        date_raw = extract_field(row, columns, ["面试时间", "时间", "date", "日期"])
        questions_text = extract_field(
            row,
            columns,
            ["核心面试问题", "面试问题", "问题", "questions", "内容"],
        )
        round_info = extract_field(row, columns, ["面试轮次", "轮次", "round"])
        result = extract_field(row, columns, ["面试结果", "结果", "result"])

        if not questions_text:
            continue

        # 构建完整文本
        text_parts = []
        if round_info:
            text_parts.append(f"面试轮次: {round_info}")
        if questions_text:
            text_parts.append(f"面试问题:\n{questions_text}")

        text_raw = "\n\n".join(text_parts)

        record = InterviewRecord(
            source_type=SourceType.EXCEL,
            source_path=str(file_path),
            source_title=f"{company_raw or '未知公司'}-{role_raw or '面试'}",
            company_raw=company_raw,
            role_raw=role_raw,
            interview_date_raw=date_raw,
            text_raw=text_raw,
            text_clean=clean_csv_text(text_raw),
            ingest_meta={
                "parser": "excel",
                "row_index": idx,
                "round": round_info,
                "result": result,
            },
        )
        records.append(record)

    return records


def extract_field(row: pd.Series, columns: list[str], possible_names: list[str]) -> str | None:
    """从行中提取字段值"""
    for name in possible_names:
        if name in columns and pd.notna(row[name]):
            return str(row[name])
    return None


def clean_csv_text(text: str) -> str:
    """清洗CSV/Excel中的文本"""
    if not text:
        return ""

    # 去除多余的空白
    text = re.sub(r"\s+", " ", text)

    # 处理常见的分隔符
    text = text.replace("；", ";")
    text = text.replace("：", ":")

    # 分割问题（如果是一段连续的问题描述）
    # 尝试识别编号问题
    if re.search(r"[一二三四五六七八九十]+[：:.]", text):
        # 中文数字编号
        parts = re.split(r"([一二三四五六七八九十]+[：:.])", text)
        if len(parts) > 1:
            lines = []
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    lines.append(f"{parts[i]}{parts[i+1].strip()}")
            text = "\n".join(lines)
    elif re.search(r"\d+[.、）]", text):
        # 阿拉伯数字编号
        parts = re.split(r"(\d+[.、）])", text)
        if len(parts) > 1:
            lines = []
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    lines.append(f"{parts[i]}{parts[i+1].strip()}")
            text = "\n".join(lines)

    return text.strip()
