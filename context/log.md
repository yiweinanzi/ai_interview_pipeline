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
