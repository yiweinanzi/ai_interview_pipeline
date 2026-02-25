# AI Interview Pipeline

AI 算法工程师面经知识库处理流水线。  
目标是将多来源面经数据（Markdown/CSV/Excel）处理为可检索、可追溯、可汇总的结构化题库。

## 项目目标

- 按公司输出面试问题汇总（含高频标记）。
- 按知识点输出全局问题汇总（含分类与频次）。
- 保留来源追溯链路（原始记录 -> 分块 -> 原子问题 -> 去重后问题）。
- 优先保证“不漏题”，低置信结果进入人工复核队列。

## 核心流程

```text
ingest -> chunk -> extract -> normalize -> dedupe -> classify -> aggregate -> audit
```

## 目录结构

```text
ai_interview_pipeline/
├── configs/                     # 配置（公司映射/知识体系/流程参数）
├── context/                     # 开发日志
├── data/
│   ├── staging/                 # 中间产物（interviews_raw/chunks）
│   ├── processed/               # 处理结果（atomic/normalized/canonical/classified）
│   └── output/                  # 最终汇总（md/xlsx/json）
├── logs/                        # 运行日志
├── prompts/                     # Prompt 模板
├── src/                         # 代码
├── .env.example                 # 环境变量示例
└── pyproject.toml
```

## 环境要求

- GPU 推荐：RTX 4090 24GB 或更高。
- Python：推荐 3.11（当前环境 3.10 也可运行）。
- 模型：`../model/Qwen3-8B`（LLM，供 vLLM 服务使用）
- 模型：`../model/bge-m3`（embedding，供去重召回使用）

## 安装

```bash
cd ai_interview_pipeline
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 配置

复制并修改 `.env`：

```bash
cp .env.example .env
```

本项目默认使用 OpenAI 兼容接口（可接 DeepSeek API 或本地 vLLM）。
使用本地 vLLM 时建议配置：

```env
DEEPSEEK_API_KEY=EMPTY
DEEPSEEK_BASE_URL=http://127.0.0.1:8000/v1
DEEPSEEK_MODEL=Qwen3-8B
DEEPSEEK_REASONER_MODEL=Qwen3-8B

EMBEDDING_MODEL=../model/bge-m3
EMBEDDING_DEVICE=cuda

# 可选：主LLM失败时自动回退到DeepSeek
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_API_KEY=<your-deepseek-key>
LLM_FALLBACK_BASE_URL=https://api.deepseek.com
LLM_FALLBACK_MODEL=deepseek-chat
LLM_FALLBACK_REASONER_MODEL=deepseek-reasoner
LLM_PRIMARY_400_DISABLE_THRESHOLD=20
EXTRACT_MAX_TOKENS=2048
COVERAGE_MAX_TOKENS=2048
```

## 启动本地 vLLM

在新终端运行：

```bash
python -m vllm.entrypoints.openai.api_server \
  --model ../model/Qwen3-8B \
  --served-model-name Qwen3-8B \
  --host 127.0.0.1 \
  --port 8000 \
  --dtype auto \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 32 \
  --enforce-eager
```

检查服务：

```bash
curl http://127.0.0.1:8000/v1/models
```

## 运行方式

### 全流程

```bash
python -m src.main run-all
```

### 小样本验证

```bash
python -m src.main run-sample --sample-size 30
```

### 分阶段运行

```bash
python -m src.main ingest
python -m src.main chunk
python -m src.main extract --coverage
python -m src.main normalize
python -m src.main dedupe --embedding
python -m src.main classify
python -m src.main aggregate
python -m src.main audit
```

### 常用调试参数

```bash
python -m src.main extract --limit 20 --coverage
python -m src.main dedupe --limit 200 --embedding
```

## 日志与后台运行

前台带日志：

```bash
mkdir -p logs
python -m src.main run-all 2>&1 | tee logs/full_run_$(date +%Y%m%d_%H%M%S).log
```

后台（可持续）：

```bash
mkdir -p logs
LOG=logs/full_run_$(date +%Y%m%d_%H%M%S).log
setsid bash -lc "cd $(pwd) && stdbuf -oL -eL python -m src.main run-all" > "$LOG" 2>&1 < /dev/null &
echo "$!" > logs/latest_full_run.pid
echo "$LOG" > logs/latest_full_run_log.txt
```

查看进度：

```bash
tail -f "$(cat logs/latest_full_run_log.txt)"
```

停止任务：

```bash
kill "$(cat logs/latest_full_run.pid)"
```

## 输出说明

- `data/staging/interviews_raw.jsonl`：统一接入后的原始记录。
- `data/staging/chunks.jsonl`：文本分块结果。
- `data/processed/atomic_questions.jsonl`：原子问题（首次抽取 + 补漏抽取）。
- `data/processed/normalized_questions.jsonl`：标准化问题。
- `data/processed/canonical_questions.jsonl`：去重后 canonical 问题。
- `data/processed/classified_questions.jsonl`：知识点分类结果。
- `data/processed/review_queue.jsonl`：待人工复核队列。
- `data/output/company_summary.md/.xlsx`：按公司汇总。
- `data/output/knowledge_summary.md/.xlsx`：按知识点汇总。
- `data/output/coverage_audit.json`：覆盖率审计。
- `data/output/run_report.md`：可读运行报告。

## 质量控制策略

- 两轮抽取：`first pass + coverage pass`，降低漏题概率。
- 去重策略：规则召回 + embedding 召回 + LLM 裁决。
- 低置信度去重自动进入 `review_queue.jsonl`。
- 聚合阶段提供高频问题标记：`>=20` 次 `🔥🔥🔥`，`>=10` 次 `🔥🔥`，`>=5` 次 `🔥`。

## 常见问题

### 1) 抽取阶段出现 JSON 解析失败

可能原因：本地模型偶发输出非严格 JSON。  
当前代码已包含重试与清洗兜底，但仍建议：

- `extract` 使用 `--coverage`（保守补漏）。
- 保持 vLLM 稳定参数（尤其是 `--max-num-seqs`）。
- 长时间运行时观察日志是否持续增长。

### 2) vLLM 启动 OOM

降低并发和显存占用参数：

- `--max-num-seqs 16` 或 `32`
- `--gpu-memory-utilization 0.8~0.85`
- 保留 `--enforce-eager`

### 3) 从中断点续跑

如果 `ingest/chunk` 已完成，直接从 `extract` 开始按阶段继续执行即可。

## 安全提示

- 不要提交真实 API Key 到仓库。
- 提交前检查 `.env`，建议仅保留本地占位配置。

## 致谢

- [vLLM](https://github.com/vllm-project/vllm)
- [Sentence-Transformers](https://www.sbert.net/)
- [Typer](https://typer.tiangolo.com/)
