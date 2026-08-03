from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml

SUPPORTED_TRANSLATION_PROVIDERS = {"deep_translator_google"}
SUPPORTED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class TranslationConfig:
    provider: str


@dataclass(frozen=True)
class LoggingConfig:
    directory: str
    level: str


@dataclass(frozen=True)
class CaptionsConfig:
    state_file: str


@dataclass(frozen=True)
class Config:
    source_language: str
    target_languages: list[str]
    translation: TranslationConfig
    logging: LoggingConfig
    protected_terms: list[str]
    english_localization_key: str
    captions: CaptionsConfig


def load_config(path: Union[str, Path] = "config/config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigError(f"Config file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping at the top level.")

    return _build_config(raw)


def _build_config(raw: dict) -> Config:
    source_language = _require_str(raw, "source_language")
    target_languages = _require_str_list(raw, "target_languages")

    if not target_languages:
        raise ConfigError("target_languages must contain at least one language code.")

    duplicates = sorted({lang for lang in target_languages if target_languages.count(lang) > 1})
    if duplicates:
        raise ConfigError(f"target_languages contains duplicates: {duplicates}")

    if source_language in target_languages:
        raise ConfigError(
            f"source_language '{source_language}' must not also appear in target_languages."
        )

    translation_raw = _require_dict(raw, "translation")
    provider = _require_str(translation_raw, "provider", parent="translation")
    if provider not in SUPPORTED_TRANSLATION_PROVIDERS:
        raise ConfigError(
            f"translation.provider '{provider}' is not supported. "
            f"Supported providers: {sorted(SUPPORTED_TRANSLATION_PROVIDERS)}"
        )

    logging_raw = _require_dict(raw, "logging")
    log_directory = _require_str(logging_raw, "directory", parent="logging")
    log_level = _require_str(logging_raw, "level", parent="logging").upper()
    if log_level not in SUPPORTED_LOG_LEVELS:
        raise ConfigError(
            f"logging.level '{log_level}' is invalid. Supported levels: {sorted(SUPPORTED_LOG_LEVELS)}"
        )

    protected_terms = _optional_str_list(raw, "protected_terms")
    english_localization_key = _optional_str(raw, "english_localization_key", default="en")

    captions_raw = raw.get("captions", {})
    if not isinstance(captions_raw, dict):
        raise ConfigError("Config section 'captions' must be a mapping.")
    caption_state_file = _optional_str(
        captions_raw, "state_file", default="state/caption_progress.json"
    )

    return Config(
        source_language=source_language,
        target_languages=target_languages,
        translation=TranslationConfig(provider=provider),
        logging=LoggingConfig(directory=log_directory, level=log_level),
        protected_terms=protected_terms,
        english_localization_key=english_localization_key,
        captions=CaptionsConfig(state_file=caption_state_file),
    )


def _require_str(d: dict, key: str, parent: Optional[str] = None) -> str:
    label = f"{parent}.{key}" if parent else key
    if key not in d:
        raise ConfigError(f"Missing required config field: {label}")
    value = d[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field '{label}' must be a non-empty string.")
    return value.strip()


def _require_str_list(d: dict, key: str) -> list[str]:
    if key not in d:
        raise ConfigError(f"Missing required config field: {key}")
    value = d[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"Config field '{key}' must be a list of non-empty strings.")
    return [v.strip() for v in value]


def _optional_str(d: dict, key: str, default: str) -> str:
    if key not in d:
        return default
    value = d[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field '{key}' must be a non-empty string.")
    return value.strip()


def _optional_str_list(d: dict, key: str) -> list[str]:
    if key not in d:
        return []
    value = d[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"Config field '{key}' must be a list of non-empty strings.")
    return [v.strip() for v in value]


def _require_dict(d: dict, key: str) -> dict:
    if key not in d:
        raise ConfigError(f"Missing required config section: {key}")
    value = d[key]
    if not isinstance(value, dict):
        raise ConfigError(f"Config section '{key}' must be a mapping.")
    return value
