"""DailyAnalyisis 配置：显式 CONFIG_DEFAULT + StringConfig，与 SteamUID 写法一致。"""

from __future__ import annotations

import json
from typing import Any

from gsuid_core.logger import logger
from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsDivider,
    GsIntConfig,
    GsBoolConfig,
    GsFloatConfig,
    GsListStrConfig,
    GsRepeatGroupConfig,
)
from gsuid_core.utils.plugins_config.gs_config import StringConfig

from .config_default import (
    DATA_DIR,
    CONFIG_PATH,
    CONFIG_DEFAULT,
    LLM_CONFIG_PATH,
    DAILY_CONFIG_LLM,
    BASIC_CONFIG_PATH,
    DAILY_CONFIG_BASIC,
    LEGACY_CONFIG_PATH,
    PROMPT_CONFIG_PATH,
    DAILY_CONFIG_PROMPT,
    DISPLAY_CONFIG_PATH,
    DAILY_CONFIG_DISPLAY,
    LEGACY_GSCORE_CONFIG_PATH,
)

_NESTED_BEFORE = None
if CONFIG_PATH.exists():
    try:
        _NESTED_BEFORE = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(_NESTED_BEFORE, dict):
            _NESTED_BEFORE = None
    except (OSError, json.JSONDecodeError):
        _NESTED_BEFORE = None

BasicConfig = StringConfig("DailyAnalyisis基础配置", BASIC_CONFIG_PATH, DAILY_CONFIG_BASIC)
LLMConfig = StringConfig("DailyAnalyisis LLM配置", LLM_CONFIG_PATH, DAILY_CONFIG_LLM)
DisplayConfig = StringConfig("DailyAnalyisis展示配置", DISPLAY_CONFIG_PATH, DAILY_CONFIG_DISPLAY)
PromptConfig = StringConfig("DailyAnalyisis提示词配置", PROMPT_CONFIG_PATH, DAILY_CONFIG_PROMPT)
for _config in (BasicConfig, LLMConfig, DisplayConfig, PromptConfig):
    _config.plugin_name = "DailyAnalyisis"

_CONFIGS = (BasicConfig, LLMConfig, DisplayConfig, PromptConfig)


def _owner(key: str) -> StringConfig | None:
    for config in _CONFIGS:
        if key in config.config:
            return config
    return None


class _DailyConfigFacade:
    """兼容旧访问方式，按 key 路由到四张配置表。"""

    @property
    def config(self) -> dict[str, GSC]:
        merged: dict[str, GSC] = {}
        for config in _CONFIGS:
            merged.update(config.config)
        return merged

    def get_config(self, key: str, default_value: object = None) -> GSC:
        owner = _owner(key)
        if owner is None:
            raise KeyError(f"DailyAnalyisis 缺少配置项: {key}")
        return owner.get_config(key, default_value)

    def set_config(self, key: str, value: object) -> bool:
        owner = _owner(key)
        if owner is None:
            return False
        return bool(owner.set_config(key, value))  # type: ignore[arg-type]

    def write_config(self) -> None:
        for config in _CONFIGS:
            config.write_config()

    def pop(self, key: str, default: object = None) -> object:
        for config in _CONFIGS:
            if key in config.config:
                return config.config.pop(key, default)
        return default


DailyConfig = _DailyConfigFacade()


_LEGACY_OLD = DATA_DIR / "config_v2.legacy.json.old"
_LEGACY_GSCORE_OLD = DATA_DIR / "gscore_config.json.old"
_LEGACY_NESTED_OLD = DATA_DIR / "config_v2.json.old"
_SPLIT_MIGRATION_MARK = DATA_DIR / "config_split_migrated.flag"

_DIVIDER_ORDER = tuple(key.removeprefix("__divider__") for key in CONFIG_DEFAULT if key.startswith("__divider__"))


def group_keys() -> tuple[str, ...]:
    return _DIVIDER_ORDER


def get_field(key: str) -> GSC:
    return DailyConfig.config[key]


def get_config(key: str, default: object = None) -> object:
    field = DailyConfig.config.get(key)
    if field is None:
        if default is None:
            raise KeyError(f"DailyAnalyisis 缺少配置项: {key}")
        return default
    return field.data


def set_config(key: str, value: object) -> bool:
    return bool(DailyConfig.set_config(key, value))  # type: ignore[arg-type]


def _plain_value(field: GSC) -> object:
    """把配置字段转成可 JSON 序列化的纯数据。"""
    if isinstance(field, GsDivider):
        return None
    if isinstance(field, GsRepeatGroupConfig):
        rows: list[dict[str, object]] = []
        for row in field.data:
            rows.append(
                {
                    name: _plain_value(sub_field)
                    for name, sub_field in row.items()
                    if not isinstance(sub_field, GsDivider)
                }
            )
        return rows
    return field.data


def config_snapshot() -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for key, field in DailyConfig.config.items():
        if isinstance(field, GsDivider):
            continue
        snapshot[key] = _plain_value(field)
    return snapshot


def _details_from_field(field: GSC) -> dict[str, Any]:
    details: dict[str, Any] = {
        "description": field.title,
        "hint": field.desc,
    }
    if isinstance(field, GsBoolConfig):
        details["type"] = "bool"
    elif isinstance(field, GsIntConfig):
        details["type"] = "int"
        if field.options:
            details["options"] = list(field.options)
        if field.max_value is not None:
            details["slider"] = {"max": field.max_value}
    elif isinstance(field, GsFloatConfig):
        details["type"] = "float"
        slider: dict[str, float] = {}
        if field.min_value is not None:
            slider["min"] = field.min_value
        if field.max_value is not None:
            slider["max"] = field.max_value
        if slider:
            details["slider"] = slider
    elif isinstance(field, GsListStrConfig):
        details["type"] = "list"
        details["items"] = {"type": "string"}
        if field.options:
            details["options"] = list(field.options)
    elif isinstance(field, GsRepeatGroupConfig):
        details["type"] = "template_list"
        details["templates"] = {
            "_default": {
                "items": {
                    name: _details_from_field(sub_field)
                    for name, sub_field in field.template.items()
                    if not isinstance(sub_field, GsDivider)
                }
            }
        }
    else:
        details["type"] = "text" if "\n" in field.desc else "string"
    if getattr(field, "secret", False):
        details["secret"] = True
    return details


def config_schema() -> dict[str, Any]:
    """按 GsCore 配置页结构生成 {group: {description, type, hint, items}}。"""
    schema: dict[str, Any] = {}
    current_group: str | None = None
    for config in _CONFIGS:
        current_group = None
        for key, field in config.config.items():
            if key.startswith("__divider__"):
                current_group = key.removeprefix("__divider__")
                schema[current_group] = {
                    "description": field.title,
                    "type": "object",
                    "hint": field.desc,
                    "items": {},
                }
                continue
            if current_group is None:
                current_group = "basic"
                schema.setdefault(
                    current_group,
                    {
                        "description": "基础设置",
                        "type": "object",
                        "hint": "",
                        "items": {},
                    },
                )
            schema[current_group]["items"][key] = _details_from_field(field)
    return schema


def _assign_legacy(raw: object) -> int:
    """把旧嵌套 config_v2.json 写入扁平 StringConfig。"""
    if not isinstance(raw, dict):
        return 0
    applied = 0
    for key, value in raw.items():
        if key in DailyConfig.config:
            if set_config(key, _unwrap_legacy_value(value)):
                applied += 1
            continue
        target = _LEGACY_KEYS.get(str(key))
        if target is not None and set_config(target, _unwrap_legacy_value(value)):
            applied += 1
    for group in _DIVIDER_ORDER:
        section = raw.get(group)
        if not isinstance(section, dict):
            continue
        for field_name, value in section.items():
            target = _legacy_key(group, field_name)
            if target is None:
                continue
            if set_config(target, _unwrap_legacy_value(value)):
                applied += 1
    for key in ("Enabled", "ExternalWebUIEnabled"):
        if key in raw and set_config(key, _unwrap_legacy_value(raw[key])):
            applied += 1
    return applied


_LEGACY_KEYS = {
    "basic.group_list_mode": "BasicGroupListMode",
    "basic.group_list": "BasicGroupList",
    "basic.analysis_days": "BasicAnalysisDays",
    "basic.max_messages": "BasicMaxMessages",
    "basic.min_messages_threshold": "BasicMinMessagesThreshold",
    "basic.bot_self_ids": "BasicBotSelfIds",
    "basic.filter_bot_messages": "BasicFilterBotMessages",
    "basic.enable_user_card": "BasicEnableUserCard",
    "basic.output_format": "BasicOutputFormat",
    "basic.report_template": "BasicReportTemplate",
    "basic.profile_display_mode": "BasicProfileDisplayMode",
    "basic.profile_image_opacity": "BasicProfileImageOpacity",
    "basic.profile_image_size_mode": "BasicProfileImageSizeMode",
    "basic.profile_mapping_config": "BasicProfileMappingConfig",
    "basic.debug_mode": "BasicDebugMode",
    "basic.enable_base64_image": "BasicEnableBase64Image",
    "basic.napcat_stream_threshold_mb": "BasicNapcatStreamThresholdMb",
    "basic.enable_analysis_reply": "BasicEnableAnalysisReply",
    "basic.show_report_caption": "BasicShowReportCaption",
    "webui.password": "WebUIPassword",
    "qq_official.enable_t2i_activity_histogram": "QQOfficialEnableT2iActivityHistogram",
    "t2i_rendering.t2i_r1_type": "T2IR1Type",
    "t2i_rendering.t2i_r1_quality": "T2IR1Quality",
    "t2i_rendering.t2i_r1_device_scale": "T2IR1DeviceScale",
    "t2i_rendering.t2i_r1_timeout": "T2IR1Timeout",
    "t2i_rendering.t2i_viewport_width": "T2IViewportWidth",
    "t2i_rendering.t2i_viewport_height": "T2IViewportHeight",
    "t2i_rendering.t2i_r2_type": "T2IR2Type",
    "t2i_rendering.t2i_r2_quality": "T2IR2Quality",
    "t2i_rendering.t2i_r2_device_scale": "T2IR2DeviceScale",
    "t2i_rendering.t2i_r2_timeout": "T2IR2Timeout",
    "t2i_rendering.t2i_font_source": "T2IFontSource",
    "t2i_rendering.t2i_mainland_google_fonts": "T2IMainlandGoogleFonts",
    "t2i_rendering.t2i_mainland_gstatic": "T2IMainlandGstatic",
    "t2i_rendering.t2i_overseas_google_fonts": "T2IOverseasGoogleFonts",
    "t2i_rendering.t2i_overseas_gstatic": "T2IOverseasGstatic",
    "auto_analysis.auto_analysis_time": "AutoAnalysisTime",
    "auto_analysis.scheduled_group_list_mode": "AutoAnalysisScheduledGroupListMode",
    "auto_analysis.scheduled_group_list": "AutoAnalysisScheduledGroupList",
    "llm.api_key": "LLMApiKey",
    "llm.api_url": "LLMApiUrl",
    "llm.model": "LLMModel",
    "llm.temperature": "LLMTemperature",
    "llm.max_tokens": "LLMMaxTokens",
    "llm.timeout": "LLMTimeout",
    "llm.llm_retries": "LLMRetries",
    "llm.llm_backoff": "LLMBackoff",
    "llm.enable_streaming_llm_call": "LLMEnableStreamingLlmCall",
    "analysis_features.topic_analysis_enabled": "AnalysisTopicAnalysisEnabled",
    "analysis_features.user_title_analysis_enabled": "AnalysisUserTitleAnalysisEnabled",
    "analysis_features.golden_quote_analysis_enabled": "AnalysisGoldenQuoteAnalysisEnabled",
    "analysis_features.chat_quality_analysis_enabled": "AnalysisChatQualityAnalysisEnabled",
    "analysis_features.max_topics": "AnalysisMaxTopics",
    "analysis_features.max_user_titles": "AnalysisMaxUserTitles",
    "analysis_features.max_golden_quotes": "AnalysisMaxGoldenQuotes",
    "analysis_features.keep_original_persona": "AnalysisKeepOriginalPersona",
    "analysis_features.use_plugin_specific_persona": "AnalysisUsePluginSpecificPersona",
    "analysis_features.plugin_specific_persona_id": "AnalysisPluginSpecificPersonaId",
    "daily_comic.enable_daily_comic": "ComicEnableDailyComic",
    "daily_comic.enable_auto_daily_comic": "ComicEnableAutoDailyComic",
    "daily_comic.comic_group_list_mode": "ComicGroupListMode",
    "daily_comic.comic_group_list": "ComicGroupList",
    "daily_comic.random_daily_comic_character": "ComicRandomDailyComicCharacter",
    "daily_comic.comic_characters": "ComicCharacters",
    "daily_comic.drawing_reference_image": "ComicDrawingReferenceImage",
    "daily_comic.drawing_backend": "ComicDrawingBackend",
    "daily_comic.drawing_external_fallback": "ComicDrawingExternalFallback",
    "daily_comic.drawing_provider_overrides": "ComicDrawingProviderOverrides",
    "daily_comic.drawing_proxy": "ComicDrawingProxy",
    "daily_comic.drawing_output_exception_retries": "ComicDrawingOutputExceptionRetries",
    "daily_comic.drawing_output_exception_retry_keywords": "ComicDrawingOutputExceptionRetryKeywords",
    "daily_comic.drawing_retry_delay": "ComicDrawingRetryDelay",
    "daily_comic.drawing_network_retries": "ComicDrawingNetworkRetries",
    "daily_comic.drawing_download_proxy": "ComicDrawingDownloadProxy",
    "incremental.incremental_group_list_mode": "IncrementalGroupListMode",
    "incremental.incremental_group_list": "IncrementalGroupList",
    "incremental.incremental_report_immediately": "IncrementalReportImmediately",
    "incremental.incremental_min_messages": "IncrementalMinMessages",
    "incremental.incremental_topics_per_batch": "IncrementalTopicsPerBatch",
    "incremental.incremental_quotes_per_batch": "IncrementalQuotesPerBatch",
    "incremental.incremental_fallback_enabled": "IncrementalFallbackEnabled",
    "html.html_base_url": "HTMLBaseUrl",
    "html.html_output_dir": "HTMLOutputDir",
    "html.html_only_url": "HTMLOnlyUrl",
    "html.html_filename_format": "HTMLFilenameFormat",
    "qq_group_upload.enable_group_file_upload": "UploadEnableGroupFileUpload",
    "qq_group_upload.group_file_folder": "UploadGroupFileFolder",
    "qq_group_upload.enable_group_album_upload": "UploadEnableGroupAlbumUpload",
    "qq_group_upload.group_album_name": "UploadGroupAlbumName",
    "qq_group_upload.group_album_strict_mode": "UploadGroupAlbumStrictMode",
    "qq_group_upload.enable_comic_album_upload": "UploadEnableComicAlbumUpload",
    "qq_group_upload.comic_album_name": "UploadComicAlbumName",
    "prompts.topic_analysis_prompts.topic_prompt": "PromptTopicAnalysisPromptsTopicPrompt",
    "prompts.user_title_analysis_prompts.user_title_prompt": "PromptUserTitleAnalysisPromptsUserTitlePrompt",
    "prompts.golden_quote_analysis_prompts.golden_quote_v2_prompt": "PromptGoldenQuoteAnalysisPromptsGoldenQuoteV2Prompt",
    "prompts.quality_analysis_prompts.quality_v2_prompt": "PromptQualityAnalysisPromptsQualityV2Prompt",
    "prompts.quality_analysis_prompts.quality_summary_prompt": "PromptQualityAnalysisPromptsQualitySummaryPrompt",
    "prompts.comic_analysis_prompts.comic_storyboard_prompt": "PromptComicAnalysisPromptsComicStoryboardPrompt",
    "performance.max_concurrent_groups": "PerformanceMaxConcurrentGroups",
    "performance.max_concurrent_llm": "PerformanceMaxConcurrentLlm",
    "performance.max_concurrent_t2i": "PerformanceMaxConcurrentT2i",
    "performance.stagger_seconds": "PerformanceStaggerSeconds",
}


def _legacy_key(group: str, field_name: str) -> str | None:
    return _LEGACY_KEYS.get(f"{group}.{field_name}")


def _unwrap_legacy_value(value: object) -> object:
    """兼容旧 GsCore 配置条目的 {type, data, ...} 包装。"""
    if isinstance(value, dict) and "data" in value and "type" in value:
        return value["data"]
    return value


def _migrate_once() -> None:
    """旧配置一次性迁移：迁移后旧文件改名，避免重复导入。"""
    migrated = 0
    split_imported = True
    if not _SPLIT_MIGRATION_MARK.exists() and _NESTED_BEFORE is not None:
        try:
            migrated += _assign_legacy(_NESTED_BEFORE)
            logger.info("已将单表配置导入四张配置表")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            split_imported = False
            logger.error("导入单表配置失败: %s", exc)
    dotted_keys = [key for key in (DailyConfig.config or {}) if "." in key or key.startswith("__group__.")]
    if dotted_keys:
        for key in dotted_keys:
            target = _LEGACY_KEYS.get(key)
            field = DailyConfig.config.get(key)
            if target is not None and field is not None and set_config(target, _unwrap_legacy_value(field.data)):
                migrated += 1
            DailyConfig.config.pop(key, None)
        logger.info("已清理旧点号配置键，共 %s 项", len(dotted_keys))
    if _NESTED_BEFORE is not None and any(
        "." in key or (isinstance(value, dict) and key in _DIVIDER_ORDER and any("." in sub_key for sub_key in value))
        for key, value in _NESTED_BEFORE.items()
    ):
        try:
            migrated += _assign_legacy(_NESTED_BEFORE)
            CONFIG_PATH.replace(_LEGACY_NESTED_OLD)
            logger.info("旧嵌套 config_v2.json 已迁移并重命名为 %s", _LEGACY_NESTED_OLD.name)
        except OSError as exc:
            logger.error("迁移旧嵌套 config_v2.json 失败: %s", exc)
    if LEGACY_CONFIG_PATH.exists():
        try:
            raw = json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
            migrated += _assign_legacy(raw)
            LEGACY_CONFIG_PATH.replace(_LEGACY_OLD)
            logger.info("旧插件配置已迁移并重命名为 %s", _LEGACY_OLD.name)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("迁移旧插件配置失败: %s", exc)
    if LEGACY_GSCORE_CONFIG_PATH.exists():
        try:
            raw_flat = json.loads(LEGACY_GSCORE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw_flat, dict):
                for key, item in raw_flat.items():
                    if key in ("Enabled", "ExternalWebUIEnabled"):
                        if set_config(key, _unwrap_legacy_value(item)):
                            migrated += 1
                        continue
                    target = _LEGACY_KEYS.get(str(key))
                    if target is None and str(key) in DailyConfig.config:
                        target = str(key)
                    if target is not None and set_config(target, _unwrap_legacy_value(item)):
                        migrated += 1
            LEGACY_GSCORE_CONFIG_PATH.replace(_LEGACY_GSCORE_OLD)
            logger.info("旧 GsCore 配置已迁移并重命名为 %s", _LEGACY_GSCORE_OLD.name)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("迁移旧 GsCore 配置失败: %s", exc)
    if migrated:
        DailyConfig.write_config()
        logger.info("DailyAnalyisis 配置迁移完成，共写入 %s 项", migrated)
    if split_imported:
        try:
            _SPLIT_MIGRATION_MARK.write_text("1", encoding="utf-8")
        except OSError as exc:
            logger.warning("写入配置迁移标记失败: %s", exc)


_migrate_once()

__all__ = [
    "DailyConfig",
    "config_schema",
    "config_snapshot",
    "get_config",
    "get_field",
    "group_keys",
    "legacy_key",
    "set_config",
]


def legacy_key(group: str, field_name: str) -> str | None:
    """返回旧嵌套配置键对应的扁平字段名。"""
    return _legacy_key(group, field_name)
