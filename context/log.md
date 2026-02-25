# 面经知识库处理流水线 - 开发日志

## 项目概述

**目标**：处理3101条互联网公司AI算法工程师面经，生成：
1. 按公司汇总的面试问题库
2. 按知识点分类的全局问题库

**核心约束**：
- 不能漏掉任何问题（最高优先级）
- 所有问题可追溯到原始文件
- 低置信度结果进入人工复核队列
- **新增**：高频问题标记（出现5次以上🔥标记）

---

## 数据分析

### 数据源统计
- **总文件数**：3109个文件
- **目录结构**：23个公司目录 + 2个特殊目录
  - `nowcoder_xxx_suanfa/`：标准格式面经（~3050条）
  - `04-interview/`：知识点题库格式（16个文件）
  - `else/`：混合格式（CSV、Excel、特殊MD）

### 全量数据接入结果（已完成）
- 处理文件数：3109
- 成功记录数：**3260条**
- 失败记录数：0

### 文件格式
| 格式 | 数量 | 说明 |
|------|------|------|
| Markdown | ~3050 | 标准牛客网面经格式 |
| Markdown (题库) | 16 | 04-interview目录，带详细解析 |
| CSV | 1 | else/实习2.csv，结构化表格 |
| Excel | 2 | else目录下的xlsx文件 |
| Markdown (飞书剪存) | 3 | 面经1/2/3.md |

### 公司名称映射
目录名 → 标准公司名：
- `nowcoder_bytedance_suanfa` → 字节跳动
- `nowcoder_alibaba_suanfa` → 阿里巴巴
- `nowcoder_tencent_suanfa` → 腾讯
- 等等...（详见 `configs/company_alias.yaml`）

---

## 技术决策

### 1. LLM选择：从DeepSeek API切换到本地Qwen3-8B
**初始决策**：使用DeepSeek API
- 成本更低（相比Claude/OpenAI）
- 支持JSON输出模式
- 支持前缀缓存

**最终决策**：切换到本地Qwen3-8B（通过vLLM部署）
**原因**：
- 0 API调用成本
- 更快速度，无速率限制
- 数据隐私更好

**模型路径**：`../model/Qwen3-8B`
**部署方式**：vLLM（性能最优）

### 2. 两阶段问题抽取（首次+补漏）
**决策**：每个chunk进行两次LLM调用
- 第一次：正常抽取所有问题
- 第二次：输入原文+已抽取问题，检查遗漏

**原因**：单次抽取容易漏题，补漏机制大幅提高覆盖率

**验证结果**：
- 20个chunk首次抽取：~40个问题
- 补漏后：123个问题（补漏贡献~60%）

### 3. 使用bge-m3本地模型进行语义相似度
**决策**：使用本地bge-m3模型（而非API）计算embedding

**原因**：
- 免费无API调用成本
- 速度快，无速率限制
- 中文效果好

**模型路径**：`../model/bge-m3`
**向量维度**：1024
**加载方式**：sentence-transformers（兼容性比FlagEmbedding好）
**测试验证**：两个不同主题句子相似度0.3299，符合预期

### 4. 保守去重策略
**决策**：
- 多层召回：精确匹配 → 标准化匹配 → 模糊匹配 → 向量相似度
- LLM裁决：对候选对调用LLM判断是否同题
- 低置信度（0.55-0.8）进入人工复核队列

**原因**：宁可多保留也不要误合并

### 5. 分阶段流水线架构
**决策**：按阶段拆分，每个阶段独立可运行

```
ingest → chunk → extract → normalize → dedupe → classify → aggregate → audit
```

**原因**：
- 便于断点续跑
- 便于调试单个阶段
- 支持小样本验证

### 6. 高频问题标记功能（新增）
**决策**：根据出现次数标记高频问题

**标记规则**：
| 出现次数 | 标记 | 等级 |
|----------|------|------|
| ≥20次 | 🔥🔥🔥 | 超高频 |
| ≥10次 | 🔥🔥 | 高频 |
| ≥5次 | 🔥 | 中频 |

**输出位置**：
- Markdown：每个知识点分类下的高频问题速览
- Excel：单独的"高频问题"sheet
- 排序：高频问题优先显示

---

## 成本与时间估算

### 全量处理估算（基于DeepSeek API）

**数据规模**：
- 3109个文件 → 3260条记录 → ~4,500个分块 → ~25,000个问题（预估）

**API调用次数**：
| 阶段 | 调用次数 |
|------|----------|
| 问题抽取（首次） | ~4,500 |
| 补漏检查 | ~4,500 |
| 去重裁决 | ~2,000-5,000 |
| 分类 | ~3,000-5,000 |
| **总计** | ~14,000-19,000 |

**成本估算**：
- 小样本测试：30文件→20chunk→123问题，花费0.21元
- 全量预估（API）：**~100-150元**
- 全量预估（本地模型）：**0元**（仅电费）

**时间估算**：
- API方式：每次调用约2-3秒，**~15-20小时**
- 本地模型（vLLM）：**~5-10小时**（无API限速）

---

## 小样本验证结果

**测试规模**：30个文件

| 阶段 | 结果 |
|------|------|
| 数据接入 | 30文件 → 181条记录 |
| 文本切分 | 181记录 → 261分块 |
| 问题抽取 | 20分块 → 123问题 |
| 标准化 | 123问题已标准化 |
| 去重 | 100问题（无重复） |
| 分类 | 100问题已分类（全部nlp_llm） |

**花费**：0.21元（DeepSeek API调用）

---

## 遇到的问题与解决方案

### 1. JSON序列化datetime失败
**问题**：`TypeError: Object of type datetime is not JSON serializable`

**解决**：在JSONEncoder中添加datetime处理：
```python
if isinstance(obj, datetime):
    return obj.isoformat()
```

**影响文件**：所有模块的JSONEncoder

### 2. DeepSeek JSON模式要求prompt包含"json"
**问题**：`Prompt must contain the word 'json' in some form to use 'response_format' of type 'json_object'`

**解决**：
- 将`call()`方法的`json_mode`默认值改为`False`
- 只在`call_json()`中启用JSON模式（prompt已包含json关键词）

### 3. DedupePair的candidate_source类型错误
**问题**：传入UUID而非枚举类型

**解决**：修改`judge_pair()`方法接收source参数，直接传入正确的枚举值

### 4. FlagEmbedding与transformers版本不兼容
**问题**：`cannot import name 'is_torch_fx_available' from 'transformers.utils.import_utils'`

**原因**：新版transformers移除了该函数

**解决**：改用sentence-transformers加载bge-m3：
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer(model_name, device=device, trust_remote_code=True)
```

---

## 项目结构

```
ai_interview_pipeline/
├── .env                    # 环境配置（含API Key）
├── pyproject.toml          # 依赖管理
├── configs/
│   ├── company_alias.yaml      # 公司名称归一化（23家公司）
│   ├── knowledge_taxonomy.yaml # AI知识点分类体系
│   └── pipeline.yaml           # 流程参数配置
├── data/
│   ├── staging/            # 中间数据
│   │   └── interviews_raw.jsonl  # 已完成：3260条记录
│   ├── processed/          # 处理结果
│   └── output/             # 最终汇总
├── prompts/                # Prompt模板
│   ├── extract_atomic.md   # 原子问题抽取
│   ├── coverage_check.md   # 补漏检查
│   ├── dedupe_judge.md     # 去重裁决
│   └── classify.md         # 知识点分类
├── src/
│   ├── main.py            # CLI入口
│   ├── settings.py        # 配置加载
│   ├── models/schemas.py  # Pydantic数据模型
│   ├── llm/
│   │   ├── deepseek_client.py  # DeepSeek API封装（可复用于本地）
│   │   └── embeddings.py       # bge-m3向量嵌入
│   ├── ingest/            # 数据接入（MD/CSV/Excel解析）
│   ├── preprocess/        # 文本清洗和切分
│   ├── extract/           # 原子问题抽取
│   ├── dedupe/            # 去重（候选召回+LLM裁决）
│   ├── classify/          # 知识点分类
│   ├── aggregate/         # 汇总生成（含高频标记）
│   └── audit/             # 覆盖率审计
├── context/
│   └── log.md             # 本开发日志
└── ../model/
    ├── bge-m3/            # Embedding模型（已下载）
    └── Qwen3-8B/          # LLM模型（已下载）
```

---

## CLI命令

```bash
# 分阶段运行
python -m src.main ingest      # 数据接入 ✅ 已完成
python -m src.main chunk       # 文本切分
python -m src.main extract     # 问题抽取
python -m src.main normalize   # 标准化
python -m src.main dedupe      # 去重
python -m src.main classify    # 分类
python -m src.main aggregate   # 汇总
python -m src.main audit       # 审计

# 一键运行
python -m src.main run-sample  # 小样本测试
python -m src.main run-all     # 全流程
```

---

## 待解决问题

### 1. vLLM安装与配置（进行中）
- 需要安装vLLM推理框架
- 配置本地Qwen3-8B模型服务
- 修改`deepseek_client.py`的base_url指向本地服务

### 2. 去重效果验证
- 小样本测试中没有发现重复问题
- 全量运行后需要人工检查去重效果

### 3. 分类准确性
- 小样本测试中100个问题全部被分类为nlp_llm
- 可能是测试数据偏NLP方向，需要更多样化的数据验证

### 4. 长时间运行稳定性
- 全量运行预计5-10小时（本地模型）
- 需要实现checkpoint机制，支持断点续跑

---

## 下一步行动

### 立即
1. [x] 数据接入（已完成：3260条记录）
2. [ ] 安装vLLM
3. [ ] 启动本地Qwen3-8B服务
4. [ ] 修改代码指向本地LLM服务

### 短期
5. [ ] 文本切分
6. [ ] 问题抽取
7. [ ] 标准化、去重、分类

### 中期
8. [ ] 全量运行
9. [ ] 人工审核复核队列
10. [ ] 检查高频问题标记效果

### 长期
11. [ ] 优化输出格式
12. [ ] 添加增量更新功能
13. [ ] 更新log.md

---

## 环境信息

**硬件**：
- GPU：NVIDIA RTX 4090 (24GB) ← 已升级
- 适合运行bge-m3 + Qwen3-8B（可同时加载）

**软件**：
- Python 3.10
- PyTorch 2.10.0
- transformers >= 4.45.0
- sentence-transformers
- vLLM（待安装）

**本地模型**：
- `../model/bge-m3` - Embedding模型（已集成）
- `../model/Qwen3-8B` - LLM模型（待集成）

---

## 配置文件

### .env 当前配置
```env
# DeepSeek API配置（备用）
DEEPSEEK_API_KEY=sk-5526df59697e47b4a879816f0461a547
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 模型配置
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_REASONER_MODEL=deepseek-reasoner

# 向量嵌入模型配置
EMBEDDING_MODEL=../model/bge-m3
EMBEDDING_DEVICE=cuda

# 数据路径
INPUT_DIR=../mian
OUTPUT_DIR=./data/output

# API调用配置
MAX_RETRIES=3
RETRY_DELAY=1.0
REQUEST_TIMEOUT=600
```

### 待修改：切换到本地LLM
```env
# 本地vLLM服务
DEEPSEEK_BASE_URL=http://localhost:8000/v1
DEEPSEEK_MODEL=../model/Qwen3-8B
```

---

## 高频问题标记功能说明

### 实现位置
- `src/aggregate/by_knowledge.py` - `get_freq_level()` 函数
- `src/aggregate/by_company.py` - `get_freq_level()` 函数

### 输出效果

**Markdown输出示例**：
```markdown
## 高频问题速览

- 🔥🔥🔥 **Transformer的注意力机制是什么** (25次 | 字节跳动, 阿里巴巴, 腾讯)
- 🔥🔥 **BatchNorm和LayerNorm的区别** (15次 | 美团, 快手)

## NLP与大模型

**题目数量**: 100 (高频 15 个)

### 1. 🔥🔥🔥 Transformer的注意力机制是什么
**出现公司**: 字节跳动, 阿里巴巴, 腾讯 等5家公司
**出现次数**: **25** (高频)
```

**Excel输出**：
- 新增"高频标记"列
- 新增"高频问题"sheet
- 按高频等级优先排序

---

## 关键文件路径

| 文件 | 用途 | 状态 |
|------|------|------|
| `.env` | API配置 | ✅ |
| `configs/company_alias.yaml` | 公司名归一化字典 | ✅ |
| `configs/knowledge_taxonomy.yaml` | 知识点分类体系 | ✅ |
| `data/staging/interviews_raw.jsonl` | 接入后的原始数据 | ✅ 3260条 |
| `data/staging/chunks.jsonl` | 文本分块 | ⏳ 待生成 |
| `data/processed/atomic_questions.jsonl` | 原子问题 | ⏳ 待生成 |
| `data/processed/canonical_questions.jsonl` | 去重后问题 | ⏳ 待生成 |
| `data/processed/classified_questions.jsonl` | 分类后问题 | ⏳ 待生成 |
| `data/processed/review_queue.jsonl` | 人工复核队列 | ⏳ 待生成 |
| `data/output/company_summary.md` | 按公司汇总 | ⏳ 待生成 |
| `data/output/knowledge_summary.md` | 按知识点汇总 | ⏳ 待生成 |

---

*最后更新：2026-02-23 22:00*

---

## 2026-02-24 ~ 2026-02-25 执行记录（本轮会话追加）

### 本轮目标
- 在不打断主实验的前提下，排查大量 WARNING/ERROR 的根因。
- 保证“本地模型优先，失败再 fallback 到 DeepSeek API（非思考模式）”。
- 对已报错样本单独开新实验修复，并保留完整日志与可追踪产物。

### 关键决策（已执行）
1. **抽取阶段 token 上限下调，避免本地 vLLM 400**
   - 根因复现：`max_tokens=8192` 在 `max_model_len=8192` 下会触发 400（`input + output` 超限）。
   - 代码改动：
     - `src/settings.py` 新增：
       - `extract_max_tokens=2048`
       - `coverage_max_tokens=2048`
     - `src/extract/extractor.py` 不再硬编码 8192，改读 settings。
     - `.env` / `.env.example` / `README.md` 同步参数。

2. **本地优先策略强化**
   - `LLM_PRIMARY_400_DISABLE_THRESHOLD` 从 3 调整到 20（减少过早熔断到 API）。
   - 目标是“优先本地 vLLM，只有失败再 fallback”。

3. **fallback 统一为非思考模式**
   - 所有新开的 API 修复实验均用 `deepseek-chat`，不启用 `deepseek-reasoner`。
   - 通过环境变量明确：
     - `DEEPSEEK_REASONER_MODEL=deepseek-chat`
     - `LLM_FALLBACK_REASONER_MODEL=deepseek-chat`

4. **报错样本单独抽取实验，不影响主实验**
   - 从主日志反查错误片段，映射到 `chunks.jsonl`，抽取出报错关联 chunk 子集。
   - 新实验使用独立目录、独立日志、独立输出。

### 关键排查结论
1. **主实验曾出现大量 fallback 的直接原因**
   - 当时本地 vLLM 服务挂掉（`127.0.0.1:8000` 不可达），导致主流程持续走 DeepSeek API。
   - 已重启并验证 vLLM：
     - 启动日志：`logs/vllm_20260224_184238.log`
     - 关键迹象：模型加载完成、`Starting vLLM API server on http://127.0.0.1:8000`、并出现本地 200 请求。

2. **主实验最终失败点不是抽取，而是去重阶段 OOM**
   - 主日志：`logs/resume_extract_20260223_234055.log`
   - 已完成：
     - extract: `3344` chunks
     - normalize: `35007` questions
   - 失败于 dedupe 加载 embedding 时：
     - `OutOfMemoryError: CUDA out of memory`
     - 触发位置：`src/llm/embeddings.py` + `sentence-transformers` 上 GPU
   - 结论：vLLM 常驻占用显存，dedupe 再上 CUDA embedding 导致显存冲突。

### 新增实验（本轮）

#### A) API 报错修复实验（已完成）
- 目录：`data/experiments/api_error_repair_20260224_184825`
- 输入：`staging/error_chunks_from_log.jsonl`（从主日志反查得到 `122` 个报错关联分块）
- 配置：API-only，`deepseek-chat`，无 reasoner
- 输出：`processed/atomic_questions_api_repair.jsonl`
- 结果：
  - 处理分块：`122`
  - 输出问题：`1999`
  - 已完成标志：日志包含 `原子问题抽取完成`
- 日志：`repair_extract.log`

#### B) 混合修复实验（本地优先，失败 fallback API，非思考）（未完成/已停止）
- 目录：`data/experiments/local_first_fallback_api_20260225_114348`
- 配置：
  - Primary：`http://127.0.0.1:8000/v1` + `Qwen3-8B`
  - Fallback：`https://api.deepseek.com` + `deepseek-chat`
  - `LLM_PRIMARY_400_DISABLE_THRESHOLD=20`
- 行为验证：
  - 日志出现本地 `http://127.0.0.1... 200 OK`
  - 本地解析失败后切换到 DeepSeek（符合预期）
- 当前状态：
  - 进程已停止（用户要求停止，且有一次 turn 中断）
  - 非完整完成：日志未出现 `原子问题抽取完成`
  - 当前输出：`53` 行（部分结果）

### 本轮统计（按日志文本计数）

#### 主实验（`logs/resume_extract_20260223_234055.log`）
- ERROR: `747`
- WARNING: `2081`
- 关键类别：
  - OOM: `1`
  - JSON解析失败相关: `984`
  - 抽取问题失败: `240`
  - 补漏检查失败: `6`

#### API 修复实验（`data/experiments/api_error_repair_20260224_184825/repair_extract.log`）
- ERROR: `350`
- WARNING: `443`
- 关键类别：
  - OOM: `0`
  - JSON解析失败相关: `525`
  - 抽取问题失败: `161`
  - 补漏检查失败: `14`

#### 混合修复实验（`data/experiments/local_first_fallback_api_20260225_114348/hybrid_extract.log`，中断前）
- ERROR: `4`
- WARNING: `13`
- 本地请求计数（日志出现次数）: `15`
- DeepSeek 请求计数（日志出现次数）: `6`
- 已输出行数：`53`
- 完成状态：未完成

### 重要假设（本轮执行时采用）
1. 报错日志中的 `question_text` 片段可用于回溯到原始 `chunk_text`（通过字符串匹配反查 chunk）。
2. 对“报错修复实验”仅处理报错关联分块，足以快速评估修复策略有效性。
3. “非思考模式”定义为不使用 reasoner 模型（统一使用 `deepseek-chat`）。
4. 主实验失败后，不回滚已完成产物（`atomic_questions.jsonl` / `normalized_questions.jsonl`），而是在后续阶段断点续跑。

### 未解决问题
1. **主流程 dedupe 与 vLLM 并存导致显存竞争（阻断全流程完成）**
   - 需要确定标准运行策略：
     - A: dedupe 改 CPU embedding（慢但稳）
     - B: dedupe 前暂停/关闭 vLLM，再恢复
     - C: 降低 vLLM 显存占用参数 + dedupe 控批
2. **抽取阶段 JSON 解析失败仍较多**
   - 已有 split-retry 与 fallback，但仍存在长尾样本失败。
3. **密钥管理风险**
   - `.env` / `ds_api.py` 中存在明文 key 管理习惯，需统一为环境变量和安全忽略策略。
4. **hybrid 实验未完成**
   - 目前仅有部分输出（53行），需决定是否重跑完整 122 分块。

### 下一步行动（建议执行顺序）
1. **先处理主流程阻断点（dedupe OOM）**
   - 优先建议：`EMBEDDING_DEVICE=cpu` 单独跑 dedupe，完成全流程闭环。
2. **整合三组产物**
   - 主实验已完成抽取/标准化产物 + API修复产物 + hybrid部分产物。
   - 形成可复现的“错误补丁集”（chunk_id 对齐，避免重复写入）。
3. **重启新的“hybrid 全量修复实验”（若需要）**
   - 固化日志、PID、中间统计文件，确保可中断续跑。
4. **补充自动化错误台账**
   - 每次实验自动导出 `error_summary.json`（错误类型、次数、受影响 chunk_id、是否恢复）。

### 本轮关键文件与路径
- 主实验日志：`logs/resume_extract_20260223_234055.log`
- vLLM 启动日志：`logs/vllm_20260224_184238.log`
- API 修复实验：
  - `data/experiments/api_error_repair_20260224_184825/meta.json`
  - `data/experiments/api_error_repair_20260224_184825/repair_extract.log`
  - `data/experiments/api_error_repair_20260224_184825/processed/atomic_questions_api_repair.jsonl`
- 混合修复实验（本地优先+fallback）：
  - `data/experiments/local_first_fallback_api_20260225_114348/meta.json`
  - `data/experiments/local_first_fallback_api_20260225_114348/hybrid_extract.log`
  - `data/experiments/local_first_fallback_api_20260225_114348/processed/atomic_questions_hybrid_repair.jsonl`

*追加更新时间：2026-02-25 12:00（Asia/Shanghai）*

---

## 2026-02-25 12:20+（本轮追加：全量实验与JSON解析修复）

### 用户指令调整
- 不再做仅报错子集修复实验，切换到“整流程下一步实验”。
- 明确要求：**使用向量召回，且使用 bge-m3 模型**。
- 之后进一步要求：**直接启动全量实验**。

### 本轮新增工程改动
1. **Dedupe裁决输出上限收敛**
   - 文件：`src/dedupe/judge.py`
   - 改动：`call_json(..., max_tokens=512)`
   - 目的：降低单次裁决时延与因超长输出导致的JSON不稳定。

2. **JSON解析容错增强**
   - 文件：`src/llm/deepseek_client.py`
   - 关键增强：
     - `_try_parse_json()` 增加“修复后候选 + 尾部裁剪重试”路径。
     - 新增 `_repair_json_text()`：处理控制字符、尾部残缺字段、引号/括号闭合。
     - 新增 `_has_unbalanced_quotes()`、`_close_json_delimiters()`。
   - 结果：对 markdown 包裹、尾逗号、截断尾部等常见异常可自动恢复。

### 本轮数据整合（用于整流程输入）
- 基线：`data/processed/atomic_questions.jsonl`
- 追加：
  - `data/experiments/api_error_repair_20260224_184825/processed/atomic_questions_api_repair.jsonl`
  - `data/experiments/local_first_fallback_api_20260225_114348/processed/atomic_questions_hybrid_repair.jsonl`
- 合并去重结果：
  - `data/experiments/whole_pipeline_merge_next_20260225_121055/processed/atomic_questions_merged.jsonl`
  - 行数：`35903`

### 全量实验（已启动）
- 目录：`data/experiments/whole_pipeline_full_embed_20260225_122728`
- 脚本：`run_full_pipeline_with_embedding.sh`
- 日志：`full_pipeline_with_embedding.log`
- 状态：`stage_status.tsv`
- 流程：`normalize -> dedupe(embedding) -> classify -> aggregate -> audit`
- 向量召回配置：
  - `EMBEDDING_MODEL=../model/bge-m3`
  - `EMBEDDING_DEVICE=cpu`（避免与vLLM显存冲突）

### 当前进度（启动后）
- `normalize` 已完成：`35903` 条
- `dedupe` 进行中：
  - 加载问题：`35903`
  - 精确匹配：`125961` 对
  - 标准化匹配累计：`139249` 对
  - 正在执行全量 embedding（`1122` batches）


### 2026-02-25 13:24 提速改造（在现有基础上）

为缩短 dedupe 长尾耗时，已做以下代码级优化并重启全量实验：

1. `src/dedupe/__init__.py`
- 增加规则直判 fast-path：`exact` / `normalized` 候选直接判重，不再走LLM。
- 增加并发LLM裁决：`ThreadPoolExecutor`，由 `DEDUPE_JUDGE_WORKERS` 控制。
- 统计输出新增：`fast_path_pairs` / `llm_judged_pairs` / `judge_workers`。

2. `src/dedupe/candidates.py`
- embedding召回改为 top-k 策略（每题仅保留最相近k个候选再过阈值），
  避免全量 O(n^2) 枚举导致候选对爆炸。

3. `src/settings.py`
- 新增配置：
  - `dedupe_embedding_top_k`（默认 8）
  - `dedupe_judge_workers`（默认 8）
  - `dedupe_fast_path_exact_normalized`（默认 true）

4. 全量实验脚本参数（当前运行）
- `data/experiments/whole_pipeline_full_embed_20260225_122728/run_full_pipeline_with_embedding.sh`
- dedupe 环境变量：
  - `DEDUPE_JUDGE_WORKERS=12`
  - `DEDUPE_EMBEDDING_TOP_K=6`
  - `DEDUPE_FAST_PATH_EXACT_NORMALIZED=true`
  - `EMBEDDING_MODEL=../model/bge-m3`
  - `EMBEDDING_DEVICE=cpu`

5. 2026-02-25 13:21 的 2000 条 smoke 验证（提速有效）
- 候选总数：630
- 规则直判：249
- 需LLM裁决：381
- 并发裁决日志显示明显快于串行。

### 2026-02-25 17:40 汇总补跑记录（aggregate rerun）

#### 触发原因
- 全量实验首次 `aggregate` 失败：
  - `IllegalCharacterError`（openpyxl）
  - 原因是部分问题文本包含 Excel 不允许的控制字符。

#### 修复内容
- 文件：
  - `src/aggregate/by_company.py`
  - `src/aggregate/by_knowledge.py`
- 改动：
  - 新增非法字符清洗（正则 `[
\x00-\x08\x0B\x0C\x0E-\x1F]` 实际为控制字符区间）
  - 在 `to_excel` 前对 DataFrame 的 object 列做统一清洗。

#### 补跑动作
- 仅补跑汇总阶段（不重跑 dedupe/classify）：
```bash
python -m src.main aggregate \
  --company-output data/experiments/whole_pipeline_full_embed_20260225_122728/output/company_summary.md \
  --knowledge-output data/experiments/whole_pipeline_full_embed_20260225_122728/output/knowledge_summary.md
```

#### 补跑结果
- 成功生成：
  - `output/company_summary.md`
  - `output/company_summary.xlsx`
  - `output/knowledge_summary.md`
  - `output/knowledge_summary.xlsx`
- 其中知识点汇总此前缺失，现已补齐。

