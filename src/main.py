"""CLI主入口"""

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(
    name="interview-pipeline",
    help="AI算法工程师面经知识库处理流水线",
)
console = Console()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)],
)
logger = logging.getLogger(__name__)


@app.command()
def ingest(
    input_dir: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入目录路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    limit: int = typer.Option(
        None,
        "--limit",
        "-n",
        help="限制处理的文件数量（用于测试）",
    ),
):
    """数据接入：解析各种格式的面经文件"""
    from src.ingest import run_ingest

    input_path = input_dir or Path("../mian")
    output_path = output or Path("data/staging/interviews_raw.jsonl")

    console.print(f"[bold blue]开始数据接入[/]")
    console.print(f"  输入目录: {input_path}")
    console.print(f"  输出文件: {output_path}")

    result = run_ingest(input_path, output_path, limit=limit)

    console.print(f"[bold green]数据接入完成[/]")
    console.print(f"  处理文件数: {result['total_files']}")
    console.print(f"  成功记录数: {result['success_count']}")
    console.print(f"  失败记录数: {result['error_count']}")


@app.command()
def chunk(
    input_file: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入文件路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    chunk_size: int = typer.Option(
        3000,
        "--chunk-size",
        help="分块大小（中文字符）",
    ),
    overlap: int = typer.Option(
        300,
        "--overlap",
        help="分块重叠大小",
    ),
):
    """文本切分：将面经文本分块"""
    from src.preprocess.chunker import run_chunk

    input_path = input_file or Path("data/staging/interviews_raw.jsonl")
    output_path = output or Path("data/staging/chunks.jsonl")

    console.print(f"[bold blue]开始文本切分[/]")
    console.print(f"  输入文件: {input_path}")
    console.print(f"  输出文件: {output_path}")
    console.print(f"  分块大小: {chunk_size}")
    console.print(f"  重叠大小: {overlap}")

    result = run_chunk(input_path, output_path, chunk_size=chunk_size, overlap=overlap)

    console.print(f"[bold green]文本切分完成[/]")
    console.print(f"  输入记录数: {result['total_records']}")
    console.print(f"  输出分块数: {result['total_chunks']}")


@app.command()
def extract(
    input_file: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入文件路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    coverage: bool = typer.Option(
        True,
        "--coverage/--no-coverage",
        help="是否进行补漏检查",
    ),
    limit: int = typer.Option(
        None,
        "--limit",
        "-n",
        help="限制处理的分块数量（用于测试）",
    ),
):
    """原子问题抽取：从文本中提取面试问题"""
    from src.extract.extractor import run_extract

    input_path = input_file or Path("data/staging/chunks.jsonl")
    output_path = output or Path("data/processed/atomic_questions.jsonl")

    console.print(f"[bold blue]开始原子问题抽取[/]")
    console.print(f"  输入文件: {input_path}")
    console.print(f"  输出文件: {output_path}")
    console.print(f"  补漏检查: {coverage}")

    result = run_extract(input_path, output_path, coverage=coverage, limit=limit)

    console.print(f"[bold green]原子问题抽取完成[/]")
    console.print(f"  处理分块数: {result['total_chunks']}")
    console.print(f"  首次抽取问题数: {result['first_pass_count']}")
    console.print(f"  补漏问题数: {result['coverage_pass_count']}")
    console.print(f"  总问题数: {result['total_questions']}")


@app.command()
def normalize(
    input_file: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入文件路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
):
    """问题标准化：统一问题格式"""
    from src.preprocess.cleaner import run_normalize

    input_path = input_file or Path("data/processed/atomic_questions.jsonl")
    output_path = output or Path("data/processed/normalized_questions.jsonl")

    console.print(f"[bold blue]开始问题标准化[/]")

    result = run_normalize(input_path, output_path)

    console.print(f"[bold green]问题标准化完成[/]")
    console.print(f"  处理问题数: {result['total_questions']}")


@app.command()
def dedupe(
    input_file: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入文件路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    use_embedding: bool = typer.Option(
        True,
        "--embedding/--no-embedding",
        help="是否使用向量相似度召回",
    ),
    limit: int = typer.Option(
        None,
        "--limit",
        "-n",
        help="限制处理的问题数量（用于测试）",
    ),
):
    """去重：合并同一问题的不同问法"""
    from src.dedupe import run_dedupe

    input_path = input_file or Path("data/processed/normalized_questions.jsonl")
    output_path = output or Path("data/processed/canonical_questions.jsonl")

    console.print(f"[bold blue]开始去重处理[/]")
    console.print(f"  输入文件: {input_path}")
    console.print(f"  输出文件: {output_path}")
    console.print(f"  使用向量召回: {use_embedding}")

    result = run_dedupe(input_path, output_path, use_embedding=use_embedding, limit=limit)

    console.print(f"[bold green]去重处理完成[/]")
    console.print(f"  输入问题数: {result['total_questions']}")
    console.print(f"  去重后问题数: {result['canonical_count']}")
    console.print(f"  复核队列数: {result['review_count']}")


@app.command()
def classify(
    input_file: Path = typer.Option(
        None,
        "--input",
        "-i",
        help="输入文件路径",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
):
    """分类：按知识点对问题分类"""
    from src.classify.classifier import run_classify

    input_path = input_file or Path("data/processed/canonical_questions.jsonl")
    output_path = output or Path("data/processed/classified_questions.jsonl")

    console.print(f"[bold blue]开始知识点分类[/]")

    result = run_classify(input_path, output_path)

    console.print(f"[bold green]知识点分类完成[/]")
    console.print(f"  处理问题数: {result['total_questions']}")


@app.command()
def aggregate(
    company_output: Path = typer.Option(
        None,
        "--company-output",
        help="按公司汇总输出路径",
    ),
    knowledge_output: Path = typer.Option(
        None,
        "--knowledge-output",
        help="按知识点汇总输出路径",
    ),
):
    """汇总生成：生成汇总文件"""
    from src.aggregate import run_aggregate

    console.print(f"[bold blue]开始汇总生成[/]")

    result = run_aggregate(
        company_output=company_output,
        knowledge_output=knowledge_output,
    )

    console.print(f"[bold green]汇总生成完成[/]")
    console.print(f"  公司汇总: {result['company_output']}")
    console.print(f"  知识点汇总: {result['knowledge_output']}")


@app.command()
def audit():
    """审计：生成覆盖率审计报告"""
    from src.audit.coverage import run_audit

    console.print(f"[bold blue]开始审计分析[/]")

    result = run_audit()

    console.print(f"[bold green]审计分析完成[/]")
    console.print(f"  覆盖率: {result['coverage_rate']:.2%}")
    console.print(f"  审计报告: {result['audit_file']}")


@app.command()
def run_sample(
    sample_size: int = typer.Option(
        30,
        "--sample-size",
        "-n",
        help="样本数量",
    ),
):
    """小样本验证：运行完整流程进行验证"""
    console.print(f"[bold blue]开始小样本验证[/]")
    console.print(f"  样本数量: {sample_size}")

    # 依次运行各个阶段
    console.print("\n[bold]Stage 1: 数据接入[/]")
    ingest(input_dir=None, output=None, limit=sample_size)

    console.print("\n[bold]Stage 2: 文本切分[/]")
    chunk(input_file=None, output=None, chunk_size=3000, overlap=300)

    console.print("\n[bold]Stage 3: 问题抽取[/]")
    extract(input_file=None, output=None, coverage=True, limit=sample_size * 2)

    console.print("\n[bold]Stage 4: 问题标准化[/]")
    normalize(input_file=None, output=None)

    console.print("\n[bold]Stage 5: 去重[/]")
    dedupe(input_file=None, output=None, use_embedding=True, limit=100)

    console.print("\n[bold]Stage 6: 分类[/]")
    classify(input_file=None, output=None)

    console.print("\n[bold]Stage 7: 汇总[/]")
    aggregate(company_output=None, knowledge_output=None)

    console.print("\n[bold]Stage 8: 审计[/]")
    audit()

    console.print(f"\n[bold green]小样本验证完成[/]")


@app.command()
def run_all():
    """全流程运行：执行完整处理流程"""
    console.print(f"[bold blue]开始全流程运行[/]")

    # 依次运行各个阶段
    console.print("\n[bold]Stage 1: 数据接入[/]")
    ingest(input_dir=None, output=None, limit=None)

    console.print("\n[bold]Stage 2: 文本切分[/]")
    chunk(input_file=None, output=None, chunk_size=3000, overlap=300)

    console.print("\n[bold]Stage 3: 问题抽取[/]")
    extract(input_file=None, output=None, coverage=True, limit=None)

    console.print("\n[bold]Stage 4: 问题标准化[/]")
    normalize(input_file=None, output=None)

    console.print("\n[bold]Stage 5: 去重[/]")
    dedupe(input_file=None, output=None, use_embedding=True, limit=None)

    console.print("\n[bold]Stage 6: 分类[/]")
    classify(input_file=None, output=None)

    console.print("\n[bold]Stage 7: 汇总[/]")
    aggregate(company_output=None, knowledge_output=None)

    console.print("\n[bold]Stage 8: 审计[/]")
    audit()

    console.print(f"\n[bold green]全流程运行完成[/]")


if __name__ == "__main__":
    app()
