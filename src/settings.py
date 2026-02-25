"""配置管理模块"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek API配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"

    # 兜底LLM配置（当主LLM失败时自动切换）
    llm_fallback_enabled: bool = False
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = "https://api.deepseek.com"
    llm_fallback_model: str = "deepseek-chat"
    llm_fallback_reasoner_model: str = "deepseek-reasoner"
    llm_primary_400_disable_threshold: int = 20

    # 向量嵌入配置
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: Literal["cuda", "cpu"] = "cuda"

    # 数据路径
    input_dir: Path = Path("../mian")
    output_dir: Path = Path("./data/output")

    # API调用配置
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: int = 600
    extract_max_tokens: int = 2048
    coverage_max_tokens: int = 2048

    # 切分配置
    chunk_size: int = 3000
    chunk_overlap: int = 300

    # 去重配置
    similarity_threshold: float = 0.85
    dedupe_confidence_low: float = 0.55
    dedupe_confidence_high: float = 0.8
    dedupe_embedding_top_k: int = 8
    dedupe_judge_workers: int = 8
    dedupe_fast_path_exact_normalized: bool = True
    classify_workers: int = 8

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return Path(__file__).parent.parent

    @property
    def configs_dir(self) -> Path:
        """配置目录"""
        return self.project_root / "configs"

    @property
    def prompts_dir(self) -> Path:
        """Prompt目录"""
        return self.project_root / "prompts"

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return self.project_root / "data"

    @property
    def staging_dir(self) -> Path:
        """中间数据目录"""
        return self.data_dir / "staging"

    @property
    def processed_dir(self) -> Path:
        """处理结果目录"""
        return self.data_dir / "processed"


# 全局配置实例
settings = Settings()
