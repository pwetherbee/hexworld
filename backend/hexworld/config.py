"""Runtime configuration (env vars prefixed HEXWORLD_, or a .env at the repo root)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEXWORLD_",
        env_file=(REPO_ROOT / ".env", ".env"),
        extra="ignore",
    )

    data_dir: Path = REPO_ROOT / "data"

    # ---- LLM
    llm: Literal["openai", "fake"] = "openai"  # fake = scripted test double (pytest only)
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    super_model: str = "gpt-5"
    tile_model: str = "gpt-5-mini"
    # Optional reasoning effort per role ("minimal"/"low"/"medium"/"high"); empty = model default.
    super_reasoning: str = "low"
    tile_reasoning: str = "minimal"
    artist_model: str = ""  # material/sprite designers; "" = tile_model
    artist_reasoning: str = "low"
    llm_timeout_s: float = 120.0  # super agent (the planner writes thousands of tokens)
    small_llm_timeout_s: float = 25.0  # tile agents + artists: short calls (p99 ~10s); a stalled call retries fast
    fake_reject_rate: float = 0.15  # FakeClient: fraction of first attempts the fake super rejects

    # ---- images
    # "procedural" renders ground from the agent-designed material library ("stub" = old alias)
    image: Literal["procedural", "stub", "comfyui", "openai"] = "procedural"
    image_fallback: Literal["none", "procedural", "stub", "openai"] = "procedural"
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_dir: Path = REPO_ROOT / "services" / "comfyui" / "workflows"
    comfyui_timeout_s: float = 180.0
    openai_image_model: str = "gpt-image-1"
    sprite_image_model: str = "gpt-image-2.5-flare"  # "" = sprites drawn with the DSL instead
    sprite_image_quality: str = "low"
    paint_concurrency: int = 6  # simultaneous image-model paintings
    sprite_sheets: bool = True  # batch concurrent paintings into 2x2 sheets (1/4 of the image cost)
    prefetch_sprites: bool = True  # start painting the plan's features as soon as it is committed
    gen_px: int = 1024  # generation resolution before pixelization

    # ---- concurrency
    llm_concurrency: int = 8
    image_concurrency: int = 2
    tile_concurrency: int = 12  # tiles in flight at once (never two neighbours)

    # ---- validation thresholds
    max_seam_delta: float = 0.35  # 0..1, see art.pixelize.seam_delta; ~0.2 = continuous texture
    min_coverage: float = 0.97  # fraction of hex-mask pixels that must be non-transparent
    min_distinct_colors: int = 3

    # ---- server
    host: str = "127.0.0.1"
    port: int = 8000
    world_radius: int = 64  # the grid is drawn infinite; this bounds where runs may start


@lru_cache
def get_settings() -> Settings:
    return Settings()
