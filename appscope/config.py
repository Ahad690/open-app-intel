"""Configuration loading for AppScope (§12).

All estimator constants live in ``config.json`` (design principle P7:
determinism). API keys are read from the *named* environment variables and are
never stored in the config file or the database.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


class StorageConfig(BaseModel):
    backend: str = "sqlite"
    path: str = "appscope.db"


class TrackingConfig(BaseModel):
    countries: list[str] = Field(default_factory=lambda: ["us", "gb"])
    categories: list[str] = Field(default_factory=lambda: ["all"])
    apps: list[str] = Field(default_factory=list)


class EstimatorConfig(BaseModel):
    min_anchors_for_medium: int = 5
    band_factor_low: float = 3.0
    band_factor_medium: float = 1.8
    store_cut: str = "small_business"
    bucket_tolerance: float = 1.25


class AdsConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["meta", "google"])
    tiktok_enabled: bool = False


class CreatorsConfig(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["youtube"])
    tiktok_enabled: bool = False
    min_confidence: float = 0.6
    brand_hashtags_by_app: dict[str, list[str]] = Field(default_factory=dict)


class AbuseConfig(BaseModel):
    """L4 anti-abuse thresholds for auto-merge (suspicious -> HOLD for review)."""

    max_rank: int = 2000
    max_window_days: int = 365
    max_monthly_downloads: int = 100_000_000
    min_unique_ratio: float = 0.5
    outlier_factor: float = 10
    outlier_min_rows: int = 3


class FederationConfig(BaseModel):
    dataset_repo: str = "https://huggingface.co/datasets/Ahad690/app-rank-anchors"
    auto_contribute: bool = False
    min_new_on_refresh: int = 50
    max_corrupt_ratio: float = 0.25
    # Recovery layer: pin refresh to a reviewed commit SHA/tag so a bad
    # auto-merge on main cannot reach you. None => pull main HEAD.
    pinned_revision: str | None = None
    # Anti-flood ceiling for auto-merge (rows a single PR may add).
    max_rows_per_pr: int = 2000
    abuse: AbuseConfig = Field(default_factory=AbuseConfig)


class ScheduleConfig(BaseModel):
    daily_hour_utc: int = 6


class KeysConfig(BaseModel):
    meta_ad_library_token_env: str = "META_AD_TOKEN"
    youtube_api_key_env: str = "YOUTUBE_API_KEY"
    hf_token_env: str = "HF_TOKEN"


class Config(BaseModel):
    storage: StorageConfig = Field(default_factory=StorageConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    estimator: EstimatorConfig = Field(default_factory=EstimatorConfig)
    ads: AdsConfig = Field(default_factory=AdsConfig)
    creators: CreatorsConfig = Field(default_factory=CreatorsConfig)
    federation: FederationConfig = Field(default_factory=FederationConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)

    # -- key resolution (env-only; never persisted) ---------------------------

    def meta_ad_token(self) -> str | None:
        return os.environ.get(self.keys.meta_ad_library_token_env)

    def youtube_api_key(self) -> str | None:
        return os.environ.get(self.keys.youtube_api_key_env)

    def hf_token(self) -> str | None:
        return os.environ.get(self.keys.hf_token_env)


DEFAULT_CONFIG_PATH = "config.json"


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load and validate config from ``path``.

    Falls back to ``config.sample.json`` next to it if the primary file is
    missing, and finally to library defaults so the package is importable
    without any config on disk.
    """
    p = Path(path)
    if not p.exists():
        sample = p.with_name("config.sample.json")
        if sample.exists():
            p = sample
        else:
            return Config()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read config at {p}: {exc}") from exc
    return Config.model_validate(raw)
