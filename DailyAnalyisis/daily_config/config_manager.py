"""
配置管理模块 - 基础设施层
负责处理插件配置
"""

import os
import re
import json
import random
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gsuid_core.utils.plugins_config.models import GSC, GsDivider

from .paths import PluginPaths
from .daily_config import get_config, set_config
from ..utils.logger import logger
from ..utils.constants import PLUGIN_NAME
from ..daily_report.template_utils import upgrade_str_format_template

_PROMPT_KEYS = {
    ("quality_analysis_prompts", "quality_v2_prompt"): "PromptQualityAnalysisPromptsQualityV2Prompt",
    ("quality_analysis_prompts", "quality_summary_prompt"): "PromptQualityAnalysisPromptsQualitySummaryPrompt",
    ("topic_analysis_prompts", "topic_prompt"): "PromptTopicAnalysisPromptsTopicPrompt",
    ("user_title_analysis_prompts", "user_title_prompt"): "PromptUserTitleAnalysisPromptsUserTitlePrompt",
    ("golden_quote_analysis_prompts", "golden_quote_v2_prompt"): "PromptGoldenQuoteAnalysisPromptsGoldenQuoteV2Prompt",
    ("comic_analysis_prompts", "comic_storyboard_prompt"): "PromptComicAnalysisPromptsComicStoryboardPrompt",
}


class ConfigManager:
    """配置管理器：直接读写扁平 StringConfig 字段。"""

    def __init__(self) -> None:
        self._migrate_daily_comic_characters()
        self._migrate_daily_comic_character_prompts()
        self._protect_upgrade_data()

    def _str(self, key: str) -> str:
        return str(get_config(key))

    def _bool(self, key: str) -> bool:
        return bool(get_config(key))

    def _int(self, key: str) -> int:
        return int(get_config(key))

    def _float(self, key: str) -> float:
        return float(get_config(key))

    def _list(self, key: str) -> list[str]:
        value = get_config(key)
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def _set(self, key: str, value: object) -> None:
        if not set_config(key, value):
            logger.warning("DailyAnalyisis 配置写入失败，保持原值: %s", key)

    def _protect_upgrade_data(self) -> None:
        """在插件升级时备份发生结构变更的旧配置，并保护用户修改的模板。"""
        plugin_root = self._get_plugin_root()
        current_version = self._get_plugin_version(plugin_root)
        current_schema_fingerprint = self._get_schema_fingerprint()
        state_path = PluginPaths.get_data_dir(PLUGIN_NAME) / "upgrade_protection_state.json"
        previous_state = self._read_upgrade_protection_state(state_path)
        previous_version = str(previous_state.get("version", "")).strip()
        version_changed = bool(previous_version and previous_version != current_version)

        if not previous_state:
            logger.debug("升级保护基线已建立，后续配置结构变化时可备份本次快照。")

        if previous_state.get("schema_fingerprint") != current_schema_fingerprint and isinstance(
            previous_state.get("config"), dict
        ):
            if not self._write_upgrade_config_backup(previous_state["config"], previous_version):
                logger.warning("插件旧配置备份失败，本次不会更新升级保护状态。")
                return

        template_hashes = self._protect_custom_t2i_templates(
            plugin_root,
            previous_state.get("template_hashes", {}),
            version_changed,
            bool(previous_state),
        )
        self._save_upgrade_protection_state(
            state_path,
            {
                "version": current_version,
                "schema_fingerprint": current_schema_fingerprint,
                "config": self._config_snapshot(),
                "template_hashes": template_hashes,
            },
        )

    @staticmethod
    def _config_snapshot() -> dict[str, object]:
        from .daily_config import config_snapshot

        return config_snapshot()

    @staticmethod
    def _get_plugin_root() -> Path:
        """获取插件根目录。"""
        return Path(__file__).resolve().parents[1]

    @staticmethod
    def _config_fields() -> dict[str, GSC]:
        from .daily_config import DailyConfig

        return DailyConfig.config

    @classmethod
    def _get_schema_fingerprint(cls) -> str:
        """计算扁平配置结构指纹，忽略描述等纯界面字段。"""
        shape = {}
        for key, field in cls._config_fields().items():
            if isinstance(field, GsDivider):
                continue
            shape[key] = {
                "type": type(field).__name__,
                "default": getattr(field, "data", None),
            }
        serialized_shape = json.dumps(
            shape,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized_shape.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_plugin_version(plugin_root: Path) -> str:
        """从 version.py 读取当前插件版本。"""
        from ..version import PLUGIN_VERSION

        return PLUGIN_VERSION

    @staticmethod
    def _read_upgrade_protection_state(state_path: Path) -> dict:
        """读取上一次正常启动记录的升级保护状态。"""
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save_upgrade_protection_state(state_path: Path, state: dict) -> None:
        """原子保存升级保护状态。"""
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = state_path.with_suffix(".tmp")
            temporary_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_path.replace(state_path)
        except OSError as exc:
            logger.warning(f"保存插件升级保护状态失败: {exc}")

    def _write_upgrade_config_backup(self, config: dict, version: str) -> bool:
        """保存旧版本配置快照，并最多保留二十份。"""
        try:
            backup_dir = PluginPaths.get_data_dir(PLUGIN_NAME) / "config_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            safe_version = re.sub(r"[^A-Za-z0-9._-]", "_", version) or "unknown"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = backup_dir / f"plugin_config_{safe_version}_{timestamp}.json"
            backup_path.write_text(
                json.dumps(
                    {
                        "backed_up_at": datetime.now().isoformat(),
                        "plugin_version": version,
                        "config": config,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            backups = sorted(
                backup_dir.glob("plugin_config_*.json"),
                key=lambda path: (path.stat().st_mtime, path.name),
            )
            for expired_backup in backups[:-20]:
                expired_backup.unlink()
            logger.info(
                "检测到插件配置结构变化，已备份上一次正常启动保存的配置快照："
                f"旧版本={version}，文件={backup_path.name}，路径={backup_path.resolve()}，"
                f"当前保留={min(len(backups), 20)} 份。"
            )
            return True
        except OSError as exc:
            logger.warning(f"备份插件旧配置失败: {exc}")
            return False

    def _protect_custom_t2i_templates(
        self,
        plugin_root: Path,
        previous_hashes: object,
        version_changed: bool,
        has_previous_state: bool,
    ) -> dict[str, str]:
        """将本版本内用户改动过的 T2I 模板保存到插件数据目录。"""
        known_hashes = previous_hashes if isinstance(previous_hashes, dict) else {}
        template_roots = {
            "reporting_templates": plugin_root / "templates",
            "standalone_templates": plugin_root / "data/t2i_templates",
        }
        current_hashes = {}
        plugin_data_dir = PluginPaths.get_data_dir(PLUGIN_NAME)
        for category, template_root in template_roots.items():
            if not template_root.is_dir():
                continue
            for template_path in template_root.rglob("*.html"):
                relative_path = template_path.relative_to(template_root)
                state_key = f"{category}/{relative_path.as_posix()}"
                try:
                    content_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
                except OSError as exc:
                    logger.warning(f"读取 T2I 模板失败，跳过保护: {template_path}: {exc}")
                    continue
                is_standalone_template = category == "standalone_templates"
                if (
                    (not has_previous_state and not is_standalone_template)
                    or (version_changed and not is_standalone_template)
                    or known_hashes.get(state_key) == content_hash
                ):
                    current_hashes[state_key] = content_hash
                    continue
                backup_path = plugin_data_dir / "custom_t2i_templates" / state_key
                try:
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(template_path, backup_path)
                    current_hashes[state_key] = content_hash
                    logger.info(f"已保护用户修改的 T2I 模板: {relative_path}")
                except OSError as exc:
                    if state_key in known_hashes:
                        current_hashes[state_key] = known_hashes[state_key]
                    logger.warning(f"保存用户 T2I 模板失败: {template_path}: {exc}")
        return current_hashes

    def get_custom_report_template_dir(self, template_name: str) -> Path | None:
        """获取指定报告模板的用户覆盖目录。"""
        custom_dir = PluginPaths.get_data_dir(PLUGIN_NAME) / "custom_t2i_templates/reporting_templates" / template_name
        return custom_dir if custom_dir.is_dir() else None

    def _migrate_daily_comic_characters(self) -> None:
        """迁移旧版漫画参考图配置，并保存迁移前备份。"""
        old_references = get_config("ComicDrawingReferenceImage", "[]")
        characters = get_config("ComicCharacters", [])
        if isinstance(characters, list) and characters:
            return
        if isinstance(old_references, str):
            try:
                parsed = json.loads(old_references)
            except json.JSONDecodeError:
                parsed = []
            old_references = parsed if isinstance(parsed, list) else []
        references = (
            [reference.strip() for reference in old_references if isinstance(reference, str) and reference.strip()]
            if isinstance(old_references, list)
            else []
        )
        if not references:
            return

        specific_persona_id = ""
        if self.get_use_plugin_specific_persona():
            specific_persona_id = self.get_plugin_specific_persona_id().strip()
        migrated_references = self._copy_legacy_comic_reference_images(references)
        if len(migrated_references) != len(references):
            logger.warning("旧版漫画参考图尚未完整迁移，将保留原配置并在下次重载时重试。")
            return
        backup_data = {
            "drawing_reference_image": references,
            "use_plugin_specific_persona": self.get_use_plugin_specific_persona(),
            "plugin_specific_persona_id": specific_persona_id,
        }
        if not self._write_comic_config_backup(backup_data):
            logger.warning("旧版漫画参考图备份失败，将保留原配置并在下次重载时重试。")
            return
        set_config(
            "ComicCharacters",
            [
                {
                    "__template_key": "character",
                    "name": "默认角色方案",
                    "enable": True,
                    "persona_id": specific_persona_id,
                    "reference_images": migrated_references,
                    "storyboard_prompt": self.get_comic_storyboard_prompt(),
                }
            ],
        )
        set_config("ComicDrawingReferenceImage", "[]")
        logger.info("已将旧版漫画参考图迁移到“默认角色方案”，原始配置已备份到插件数据目录。")

    def _migrate_daily_comic_character_prompts(self) -> None:
        """将旧版全局分镜提示词复制到既有角色方案。"""
        state_path = PluginPaths.get_data_dir(PLUGIN_NAME) / "comic_character_prompt_migration.json"
        if state_path.exists():
            return
        characters = get_config("ComicCharacters", [])
        default_prompt = self.get_comic_storyboard_prompt()
        modified = False
        if isinstance(characters, list):
            for character in characters:
                if not isinstance(character, dict):
                    continue
                if not str(character.get("storyboard_prompt", "")).strip():
                    character["storyboard_prompt"] = default_prompt
                    modified = True
        try:
            if modified:
                set_config("ComicCharacters", characters)
                logger.info("已将默认漫画场景分析提示词迁移到既有角色方案。")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"completed": True}), encoding="utf-8")
        except OSError as exc:
            logger.warning(f"迁移漫画角色场景提示词失败，将在下次重载时重试: {exc}")

    def _write_comic_config_backup(self, data: dict) -> bool:
        """写入漫画配置迁移备份。"""
        try:
            backup_dir = PluginPaths.get_data_dir(PLUGIN_NAME) / "config_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"comic_character_migration_{timestamp}.json"
            backup_path.write_text(
                json.dumps({"migrated_at": datetime.now().isoformat(), "config": data}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as exc:
            logger.warning(f"保存漫画配置迁移备份失败: {exc}")
            return False

    def _copy_legacy_comic_reference_images(self, references: list[str]) -> list[str]:
        """复制旧参考图到角色模板对应的原生上传目录。"""
        plugin_data_dir = PluginPaths.get_data_dir(PLUGIN_NAME)
        relative_dir = Path("files/daily_comic/comic_characters/templates/character/reference_images")
        target_dir = plugin_data_dir / relative_dir
        migrated_references = []
        for index, reference in enumerate(references, start=1):
            try:
                source_path = (plugin_data_dir / reference).resolve()
                source_path.relative_to(plugin_data_dir.resolve())
                if not source_path.is_file():
                    logger.warning(f"旧版漫画参考图不存在，跳过迁移: {reference}")
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                target_name = f"migrated_{index}_{source_path.name}"
                target_path = target_dir / target_name
                shutil.copy2(source_path, target_path)
                migrated_references.append((relative_dir / target_name).as_posix())
            except (OSError, ValueError) as exc:
                logger.warning(f"迁移旧版漫画参考图失败 {reference}: {exc}")
        return migrated_references

    def get_group_list_mode(self) -> str:
        """获取群组列表模式 (whitelist/blacklist/none)"""
        return self._str("BasicGroupListMode")

    def get_group_list(self) -> list[str]:
        """获取群组列表（用于黑白名单）"""
        return self._list("BasicGroupList")

    def is_group_allowed(self, group_id_or_umo: str) -> bool:
        """根据配置的白/黑名单判断是否允许在该群聊中使用。"""
        mode = self.get_group_list_mode().lower()
        if mode not in ("whitelist", "blacklist", "none"):
            mode = "none"
        if mode == "none":
            return True
        glist = [str(group).strip() for group in self.get_group_list()]
        target = str(group_id_or_umo).strip()
        is_in_list = any(self._is_group_match(target, item) for item in glist)
        return is_in_list if mode == "whitelist" else not is_in_list

    def _is_group_match(self, target: str, item: str) -> bool:
        """判断名单中的 item 是否匹配目标 UMO 或纯 ID。"""
        if item == target:
            return True
        if ":" in target:
            target_prefix, target_id = target.rsplit(":", 1)
        else:
            target_prefix, target_id = "", target
        candidates = {target_id}
        if "#" in target_id:
            candidates.add(target_id.split("#", 1)[0])
        if "_" in target_id:
            for part in target_id.split("_"):
                candidates.add(part)
        if ":" in item:
            i_prefix, i_id = item.rsplit(":", 1)
            if target_prefix and i_prefix != target_prefix:
                return False
        else:
            i_id = item
        item_variants = {i_id}
        if "#" in i_id:
            item_variants.add(i_id.split("#", 1)[0])
        if "_" in i_id:
            for part in i_id.split("_"):
                item_variants.add(part)
        return not item_variants.isdisjoint(candidates)

    def get_max_messages(self) -> int:
        """获取最大消息数量"""
        return self._int("BasicMaxMessages")

    def get_analysis_days(self) -> int:
        """获取分析天数"""
        return self._int("BasicAnalysisDays")

    def get_auto_analysis_time(self) -> list[str]:
        """获取自动分析时间列表"""
        values = self._list("AutoAnalysisTime")
        return values if values else ["09:00"]

    def get_enable_auto_analysis(self) -> bool:
        """获取是否启用自动分析（兼容旧接口）。"""
        return self.is_auto_analysis_enabled()

    def get_output_format(self) -> list[str]:
        """获取输出格式"""
        values = self._list("BasicOutputFormat")
        return values if values else ["image"]

    def get_qq_official_t2i_summary_dashboard_enabled(self) -> bool:
        """是否启用 QQ 官方 T2I 概览图。"""
        return self._bool("QQOfficialEnableT2iActivityHistogram")

    def get_min_messages_threshold(self) -> int:
        """获取最小消息阈值"""
        return self._int("BasicMinMessagesThreshold")

    def get_topic_analysis_enabled(self) -> bool:
        """获取是否启用话题分析"""
        return self._bool("AnalysisTopicAnalysisEnabled")

    def get_user_title_analysis_enabled(self) -> bool:
        """获取是否启用用户称号分析"""
        return self._bool("AnalysisUserTitleAnalysisEnabled")

    def get_golden_quote_analysis_enabled(self) -> bool:
        """获取是否启用金句分析"""
        return self._bool("AnalysisGoldenQuoteAnalysisEnabled")

    def get_chat_quality_analysis_enabled(self) -> bool:
        """获取是否启用聊天质量分析"""
        return self._bool("AnalysisChatQualityAnalysisEnabled")

    def get_max_topics(self) -> int:
        """获取最大话题数量"""
        return self._int("AnalysisMaxTopics")

    def get_max_user_titles(self) -> int:
        """获取最大用户称号数量"""
        return self._int("AnalysisMaxUserTitles")

    def get_max_golden_quotes(self) -> int:
        """获取最大金句数量"""
        return self._int("AnalysisMaxGoldenQuotes")

    def get_llm_retries(self) -> int:
        """获取LLM请求重试次数"""
        return self._int("LLMRetries")

    def get_llm_backoff(self) -> int:
        """获取LLM请求重试退避基值（秒），实际退避会乘以尝试次数"""
        return self._int("LLMBackoff")

    def get_enable_streaming_llm_call(self) -> bool:
        """获取是否启用流式 LLM 调用"""
        return self._bool("LLMEnableStreamingLlmCall")

    def get_debug_mode(self) -> bool:
        """获取是否启用调试模式"""
        return self._bool("BasicDebugMode")

    def get_enable_base64_image(self) -> bool:
        """获取是否启用 Base64 图片传输"""
        return self._bool("BasicEnableBase64Image")

    def get_napcat_stream_threshold_mb(self) -> float:
        """获取可触发 NapCat 流式上传兜底的本地图片最小大小。"""
        return max(0.0, self._float("BasicNapcatStreamThresholdMb"))

    def get_t2i_rendering_strategies(self) -> list[dict]:
        """获取用户配置的两轮 T2I 渲染策略"""
        viewport_width = max(1, self._int("T2IViewportWidth"))
        viewport_height = max(1, self._int("T2IViewportHeight"))
        return [
            {
                "full_page": True,
                "type": self._str("T2IR1Type"),
                "quality": self._int("T2IR1Quality"),
                "device_scale_factor_level": self._str("T2IR1DeviceScale"),
                "timeout": self._int("T2IR1Timeout"),
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
            },
            {
                "full_page": True,
                "type": self._str("T2IR2Type"),
                "quality": self._int("T2IR2Quality"),
                "device_scale_factor_level": self._str("T2IR2DeviceScale"),
                "timeout": self._int("T2IR2Timeout"),
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
            },
        ]

    def get_t2i_font_source(self) -> str:
        """获取 T2I 字体源 (Mainland/Overseas)"""
        return self._str("T2IFontSource")

    def get_t2i_google_fonts_mirror(self) -> str:
        """根据环境选择获取 Google Fonts 镜像地址"""
        return self._str(
            "T2IMainlandGoogleFonts" if self.get_t2i_font_source() == "Mainland" else "T2IOverseasGoogleFonts"
        )

    def get_t2i_gstatic_mirror(self) -> str:
        """根据环境选择获取 Gstatic 镜像地址"""
        return self._str("T2IMainlandGstatic" if self.get_t2i_font_source() == "Mainland" else "T2IOverseasGstatic")

    def get_t2i_atri_font_mirror(self) -> str:
        """获取 ATRI 主题字体镜像地址。"""
        return "https://tc.ciallo.ccwu.cc"

    def get_llm_provider_id(self) -> str:
        """获取主 LLM Provider ID"""
        return "plugin"

    def get_topic_provider_id(self) -> str:
        """获取话题分析专用 Provider ID"""
        return "plugin"

    def get_user_title_provider_id(self) -> str:
        """获取用户称号分析专用 Provider ID"""
        return "plugin"

    def get_golden_quote_provider_id(self) -> str:
        """获取金句分析专用 Provider ID"""
        return "plugin"

    def get_quality_provider_id(self) -> str:
        """获取聊天质量分析专用 Provider ID"""
        return "plugin"

    def get_drawing_prompt_provider_id(self) -> str:
        """获取画图提示词专用 Provider ID"""
        return "plugin"

    def get_keep_original_persona(self) -> bool:
        """获取是否继承会话原始人格设定"""
        return self._bool("AnalysisKeepOriginalPersona")

    def get_use_plugin_specific_persona(self) -> bool:
        """获取是否强制使用插件指定的人格设定"""
        return self._bool("AnalysisUsePluginSpecificPersona")

    def get_plugin_specific_persona_id(self) -> str:
        """获取插件指定的全局人格 ID"""
        return self._str("AnalysisPluginSpecificPersonaId")

    def get_bot_self_ids(self) -> list:
        """获取机器人自身的 ID 列表"""
        return self._list("BasicBotSelfIds")

    def get_filter_bot_messages(self) -> bool:
        """获取是否过滤机器人自己的消息。"""
        return self._bool("BasicFilterBotMessages")

    def set_filter_bot_messages(self, enabled: bool):
        """设置是否过滤机器人自己的消息。"""
        self._set("BasicFilterBotMessages", enabled)

    def get_html_output_dir(self) -> str:
        """获取HTML输出目录"""
        default_path = PluginPaths.get_data_dir(PLUGIN_NAME) / "self_hosted_html_reports"
        val = self._str("HTMLOutputDir")
        return val if val else str(default_path)

    def get_html_base_url(self) -> str:
        """获取HTML外链Base URL"""
        return self._str("HTMLBaseUrl")

    def get_html_only_url(self) -> bool:
        """获取是否仅输出外链而不发送文件本体"""
        return self._bool("HTMLOnlyUrl")

    def set_html_only_url(self, enabled: bool):
        """设置是否仅输出外链而不发送文件本体"""
        self._set("HTMLOnlyUrl", enabled)

    def get_html_filename_format(self) -> str:
        """获取HTML文件名格式"""
        return self._str("HTMLFilenameFormat")

    def _prompt_key(self, group: str, style: str) -> str | None:
        return _PROMPT_KEYS.get((group, style))

    def get_topic_analysis_prompt(self, style: str = "topic_prompt") -> str:
        """获取话题分析提示词模板"""
        key = self._prompt_key("topic_analysis_prompts", style)
        return self._str(key) if key else ""

    def get_user_title_analysis_prompt(self, style: str = "user_title_prompt") -> str:
        """获取用户称号分析提示词模板"""
        key = self._prompt_key("user_title_analysis_prompts", style)
        return self._str(key) if key else ""

    def get_golden_quote_analysis_prompt(self, style: str = "golden_quote_v2_prompt") -> str:
        """获取金句分析提示词模板"""
        key = self._prompt_key("golden_quote_analysis_prompts", style)
        return self._str(key) if key else ""

    def get_quality_analysis_prompt(self, style: str = "quality_v2_prompt") -> str:
        """获取聊天质量分析提示词模板"""
        key = self._prompt_key("quality_analysis_prompts", style)
        return self._str(key) if key else ""

    def get_quality_summary_prompt(self, style: str = "quality_summary_prompt") -> str:
        """获取聊天质量汇总分析提示词模板"""
        key = self._prompt_key("quality_analysis_prompts", style)
        return self._str(key) if key else ""

    def set_quality_analysis_prompt(self, prompt: str):
        """设置聊天质量分析提示词模板"""
        self._set("PromptQualityAnalysisPromptsQualityV2Prompt", prompt)

    def _upgrade_config_item(self, group: str, key: str, setter_func):
        """升级指定配置项的值（从 str.format -> string.Template），并回写。"""
        target = self._prompt_key(group, key)
        if target is None:
            return False
        val = self._str(target)
        if not val:
            return False
        upgraded_val, upgraded = upgrade_str_format_template(val)
        if upgraded and upgraded_val != val:
            setter_func(upgraded_val)
            logger.info(f"配置项 {group}.{key} 发现旧版语法并已自动升级为 string.Template 格式。")
            return True
        return False

    def upgrade_prompt_templates(self):
        """启动时调用，扫描并升级所有可配置的模板（含 prompt 和文件名）。"""
        modified = self._upgrade_config_item(
            "quality_analysis_prompts", "quality_v2_prompt", self.set_quality_analysis_prompt
        )
        modified |= self._upgrade_config_item(
            "quality_analysis_prompts", "quality_summary_prompt", self.set_quality_summary_prompt
        )
        modified |= self._upgrade_config_item("topic_analysis_prompts", "topic_prompt", self.set_topic_analysis_prompt)
        modified |= self._upgrade_config_item(
            "user_title_analysis_prompts", "user_title_prompt", self.set_user_title_analysis_prompt
        )
        modified |= self._upgrade_config_item(
            "golden_quote_analysis_prompts", "golden_quote_v2_prompt", self.set_golden_quote_analysis_prompt
        )
        modified |= self._upgrade_config_item(
            "comic_analysis_prompts", "comic_storyboard_prompt", self.set_comic_storyboard_prompt
        )
        modified |= self._upgrade_config_item("html", "html_filename_format", self.set_html_filename_format)
        if modified:
            logger.info("已完成所有配置模板从 str.format 到 string.Template 的安全迁移。（已自动回写配置）")
        return modified

    def migrate_legacy_configs(self):
        """升级旧版配置项的类型/结构，确保兼容新 schema。"""
        val = get_config("BasicOutputFormat")
        if isinstance(val, str):
            self._set("BasicOutputFormat", [val])
            logger.info("output_format 已从旧版 string 自动迁移为 list")

    def set_topic_analysis_prompt(self, prompt: str):
        """设置话题分析提示词模板"""
        self._set("PromptTopicAnalysisPromptsTopicPrompt", prompt)

    def set_quality_summary_prompt(self, prompt: str):
        """设置聊天质量汇总分析提示词模板"""
        self._set("PromptQualityAnalysisPromptsQualitySummaryPrompt", prompt)

    def set_user_title_analysis_prompt(self, prompt: str):
        """设置用户称号分析提示词模板"""
        self._set("PromptUserTitleAnalysisPromptsUserTitlePrompt", prompt)

    def set_golden_quote_analysis_prompt(self, prompt: str):
        """设置金句分析提示词模板"""
        self._set("PromptGoldenQuoteAnalysisPromptsGoldenQuoteV2Prompt", prompt)

    def set_comic_storyboard_prompt(self, prompt: str):
        """设置漫画场景分析提示词模板"""
        self._set("PromptComicAnalysisPromptsComicStoryboardPrompt", prompt)

    def set_output_format(self, format_types: str | list[str]):
        """设置输出格式"""
        if isinstance(format_types, str):
            format_types = [fmt.strip() for fmt in format_types.replace("，", ",").split(",")]
        for fmt in format_types:
            if fmt not in ("image", "text", "html"):
                raise ValueError(f"无效格式: {fmt}。有效: image, text, html")
        self._set("BasicOutputFormat", format_types)

    def set_group_list_mode(self, mode: str):
        """设置群组列表模式"""
        self._set("BasicGroupListMode", mode)

    def set_group_list(self, groups: list[str]):
        """设置群组列表"""
        self._set("BasicGroupList", groups)

    def get_max_concurrent_tasks(self) -> int:
        """获取自动分析最大并发群数"""
        return self._int("PerformanceMaxConcurrentGroups")

    def get_llm_max_concurrent(self) -> int:
        """获取全局 LLM 最大并发请求数"""
        return self._int("PerformanceMaxConcurrentLlm")

    def get_t2i_max_concurrent(self) -> int:
        """获取全局图片渲染（T2I）最大并发数"""
        return self._int("PerformanceMaxConcurrentT2i")

    def get_stagger_seconds(self) -> int:
        """获取多群分析任务启动时的交错间隔（秒）"""
        return self._int("PerformanceStaggerSeconds")

    def set_max_concurrent_tasks(self, count: int):
        """设置自动分析最大并发数"""
        self._set("PerformanceMaxConcurrentGroups", count)

    def set_max_messages(self, count: int):
        """设置最大消息数量"""
        self._set("BasicMaxMessages", count)

    def set_analysis_days(self, days: int):
        """设置分析天数"""
        self._set("BasicAnalysisDays", days)

    def set_auto_analysis_time(self, time_val: str | list[str]):
        """设置自动分析时间点"""
        self._set("AutoAnalysisTime", time_val)

    def is_auto_analysis_enabled(self) -> bool:
        """判断自动分析功能是否通过名单“按需开启”。"""
        mode = self.get_scheduled_group_list_mode()
        if mode == "inherit":
            return bool(self.get_group_list()) if self.get_group_list_mode().lower() == "whitelist" else True
        lst = self.get_scheduled_group_list()
        return (mode == "whitelist" and len(lst) > 0) or (mode == "blacklist")

    def get_scheduled_group_list_mode(self) -> str:
        """获取旧定时名单模式（仅兼容读取，不再决定定时目标）。"""
        mode = self._str("AutoAnalysisScheduledGroupListMode").lower()
        return mode if mode in ("inherit", "whitelist", "blacklist") else "whitelist"

    def set_scheduled_group_list_mode(self, mode: str):
        """仅兼容写入，不影响定时目标。"""
        self._set("AutoAnalysisScheduledGroupListMode", mode)

    def get_scheduled_group_list(self) -> list[str]:
        """获取旧定时目标群列表（仅兼容读取，不再决定定时目标）。"""
        return self._list("AutoAnalysisScheduledGroupList")

    def set_scheduled_group_list(self, groups: list[str]):
        """仅兼容写入，不影响定时目标。"""
        self._set("AutoAnalysisScheduledGroupList", groups)

    def is_scheduled_group_allowed(self, group_umo_or_id: str) -> bool:
        """判断当前群是否允许参与定时分析。"""
        if not self.is_group_allowed(group_umo_or_id):
            return False
        mode = self.get_scheduled_group_list_mode()
        if mode == "inherit":
            return True
        return self.is_group_in_filtered_list(group_umo_or_id, mode, self.get_scheduled_group_list())

    def is_group_in_filtered_list(self, group_umo_or_id: str, mode: str, group_list: list) -> bool:
        """通用名单判定逻辑。"""
        group_list = [str(x).strip() for x in group_list]
        target = str(group_umo_or_id).strip()
        if mode == "whitelist":
            if not group_list:
                return False
            return any(self._is_group_match(target, item) for item in group_list)
        if not group_list:
            return True
        return not any(self._is_group_match(target, item) for item in group_list)

    def set_min_messages_threshold(self, threshold: int):
        """设置最小消息阈值"""
        self._set("BasicMinMessagesThreshold", threshold)

    def set_topic_analysis_enabled(self, enabled: bool):
        """设置是否启用话题分析"""
        self._set("AnalysisTopicAnalysisEnabled", enabled)

    def set_user_title_analysis_enabled(self, enabled: bool):
        """设置是否启用用户称号分析"""
        self._set("AnalysisUserTitleAnalysisEnabled", enabled)

    def set_golden_quote_analysis_enabled(self, enabled: bool):
        """设置是否启用金句分析"""
        self._set("AnalysisGoldenQuoteAnalysisEnabled", enabled)

    def set_chat_quality_analysis_enabled(self, enabled: bool):
        """设置是否启用聊天质量分析"""
        self._set("AnalysisChatQualityAnalysisEnabled", enabled)

    def set_max_topics(self, count: int):
        """设置最大话题数量"""
        self._set("AnalysisMaxTopics", count)

    def set_max_user_titles(self, count: int):
        """设置最大用户称号数量"""
        self._set("AnalysisMaxUserTitles", count)

    def set_max_golden_quotes(self, count: int):
        """设置最大金句数量"""
        self._set("AnalysisMaxGoldenQuotes", count)

    def set_html_filename_format(self, format_str: str):
        """设置HTML文件名格式"""
        self._set("HTMLFilenameFormat", format_str)

    def get_report_template(self) -> str:
        """获取报告模板名称"""
        return self._str("BasicReportTemplate")

    def set_report_template(self, template_name: str):
        """设置报告模板名称"""
        self._set("BasicReportTemplate", template_name)

    def get_enable_user_card(self) -> bool:
        """获取是否使用用户群名片"""
        return self._bool("BasicEnableUserCard")

    def get_enable_analysis_reply(self) -> bool:
        """获取是否在群分析完成后发送文本回复"""
        return self._bool("BasicEnableAnalysisReply")

    def set_enable_analysis_reply(self, enabled: bool):
        """设置是否在群分析完成后发送文本回复"""
        self._set("BasicEnableAnalysisReply", enabled)

    def get_show_report_caption(self) -> bool:
        """获取是否发送 \"📊 每日群聊分析报告已生成\" 前缀文字。"""
        return self._bool("BasicShowReportCaption")

    def set_show_report_caption(self, enabled: bool):
        """设置是否发送 \"📊 每日群聊分析报告已生成\" 前缀文字。"""
        self._set("BasicShowReportCaption", enabled)

    def get_profile_display_mode(self) -> str:
        """获取人格标签展示模式。"""
        mode = self._str("BasicProfileDisplayMode").lower()
        return mode if mode in {"mbti", "sbti", "acgti"} else "mbti"

    def get_profile_image_opacity(self) -> float:
        """获取人格背景图透明度。"""
        try:
            return max(0.0, min(1.0, float(get_config("BasicProfileImageOpacity"))))
        except (TypeError, ValueError):
            return 0.12

    def get_profile_image_size_mode(self) -> str:
        """获取人格背景图尺寸模式。"""
        mode = self._str("BasicProfileImageSizeMode").lower()
        return mode if mode in {"contain", "cover"} else "contain"

    def get_profile_mapping_config(self) -> str:
        """获取人格映射配置(JSON 文本)。"""
        return self._str("BasicProfileMappingConfig").strip()

    def get_enable_group_file_upload(self) -> bool:
        """获取是否启用群文件上传"""
        return self._bool("UploadEnableGroupFileUpload")

    def get_group_file_folder(self) -> str:
        """获取群文件上传目录名，空字符串表示根目录"""
        return self._str("UploadGroupFileFolder")

    def get_enable_group_album_upload(self) -> bool:
        """获取是否启用群相册上传（仅 NapCat）"""
        return self._bool("UploadEnableGroupAlbumUpload")

    def get_group_album_name(self) -> str:
        """获取目标群相册名称，空字符串表示默认相册"""
        return self._str("UploadGroupAlbumName")

    def get_group_album_strict_mode(self) -> bool:
        """获取群相册上传严格模式开关。"""
        return self._bool("UploadGroupAlbumStrictMode")

    def set_group_album_strict_mode(self, enabled: bool):
        """设置群相册上传严格模式"""
        self._set("UploadGroupAlbumStrictMode", enabled)

    def get_incremental_enabled(self) -> bool:
        """获取是否开启了增量分析（由名单状态决定）"""
        mode = self.get_incremental_group_list_mode()
        if mode == "inherit":
            return self.is_auto_analysis_enabled()
        lst = self.get_incremental_group_list()
        return (mode == "whitelist" and len(lst) > 0) or (mode == "blacklist")

    def get_incremental_group_list_mode(self) -> str:
        """获取增量分析名单模式 (inherit/whitelist/blacklist)。"""
        mode = self._str("IncrementalGroupListMode").lower()
        return mode if mode in ("inherit", "whitelist", "blacklist") else "whitelist"

    def get_incremental_group_list(self) -> list[str]:
        """获取增量分析群列表"""
        return self._list("IncrementalGroupList")

    def is_incremental_group_allowed(self, group_umo_or_id: str) -> bool:
        """判断当前群是否应使用增量分析。"""
        if not self.is_scheduled_group_allowed(group_umo_or_id):
            return False
        mode = self.get_incremental_group_list_mode()
        if mode == "inherit":
            return True
        return self.is_group_in_filtered_list(group_umo_or_id, mode, self.get_incremental_group_list())

    def get_incremental_fallback_enabled(self) -> bool:
        """获取增量分析失败回退到全量分析的开关（默认启用）"""
        return self._bool("IncrementalFallbackEnabled")

    def get_incremental_report_immediately(self) -> bool:
        """获取是否启用增量分析立即发送报告（调试用）"""
        return self._bool("IncrementalReportImmediately")

    def set_incremental_report_immediately(self, enabled: bool):
        """设置增量分析是否立即发送报告"""
        self._set("IncrementalReportImmediately", enabled)

    def get_incremental_min_messages(self) -> int:
        """获取触发增量分析的最小消息数阈值"""
        return max(1, self._int("IncrementalMinMessages"))

    def get_incremental_topics_per_batch(self) -> int:
        """获取单次增量分析提取的最大话题数"""
        return self._int("IncrementalTopicsPerBatch")

    def get_incremental_quotes_per_batch(self) -> int:
        """获取单次增量分析提取的最大金句数"""
        return self._int("IncrementalQuotesPerBatch")

    def get_enable_daily_comic(self) -> bool:
        """获取漫画功能总开关。"""
        return self._bool("ComicEnableDailyComic")

    def get_enable_auto_daily_comic(self) -> bool:
        """获取是否在分析完成后自动生成漫画。"""
        return self._bool("ComicEnableAutoDailyComic")

    def get_comic_group_list_mode(self) -> str:
        """获取漫画生成名单模式。"""
        mode = self._str("ComicGroupListMode").lower()
        return mode if mode in ("inherit", "whitelist", "blacklist") else "inherit"

    def get_comic_group_list(self) -> list[str]:
        """获取漫画生成白/黑名单列表。"""
        return self._list("ComicGroupList")

    def is_comic_group_allowed(self, group_umo_or_id: str, inherit_allowed: bool | None = None) -> bool:
        """判断当前群是否允许生成漫画。"""
        mode = self.get_comic_group_list_mode()
        if mode == "inherit":
            if inherit_allowed is not None:
                return bool(inherit_allowed)
            return self.is_group_allowed(group_umo_or_id)
        return self.is_group_in_filtered_list(group_umo_or_id, mode, self.get_comic_group_list())

    def get_drawing_backend(self) -> str:
        """获取漫画绘图后端；GsCore 版本固定使用 builtin。"""
        return "builtin"

    def get_drawing_external_fallback(self) -> bool:
        """读取旧版外部绘图回退配置。"""
        return self._bool("ComicDrawingExternalFallback")

    def get_drawing_provider_configs(self) -> list[dict]:
        """获取按优先级排序的已启用绘图供应商候选。"""
        providers = get_config("ComicDrawingProviderOverrides", [])
        if not isinstance(providers, list):
            return []
        template_protocols = {
            "google": "google",
            "openai": "chat",
            "zai": "chat",
            "grok2api": "grok",
            "agnes_ai": "agnes_ai",
            "agnes_ai_china": "agnes_ai",
            "xai": "xai",
            "minimax": "minimax",
            "stepfun": "stepfun",
            "openai_images": "images",
            "doubao": "doubao",
            "sensenova": "sensenova",
            "dashscope": "dashscope",
        }
        valid_protocols = {"images", "chat", "grok", "gemini", *template_protocols}
        candidates = []
        for index, provider in enumerate(providers):
            if not isinstance(provider, dict) or not provider.get("enable", True):
                continue
            template_key = str(provider.get("__template_key", "")).strip()
            protocol = template_protocols.get(template_key, str(provider.get("api_protocol", "images")).strip())
            api_key = str(provider.get("api_key", "")).strip()
            if protocol not in valid_protocols or not api_key:
                logger.warning("跳过索引 %s 处无效的漫画绘图供应商配置", index)
                continue
            candidate = provider.copy()
            candidate["api_protocol"] = protocol
            candidate["api_key"] = api_key
            candidate["_index"] = index
            try:
                candidate["_priority"] = int(provider.get("priority", 0))
            except (TypeError, ValueError):
                candidate["_priority"] = 0
            candidates.append(candidate)
        return sorted(candidates, key=lambda item: (-item["_priority"], item["_index"]))

    def get_drawing_output_exception_retries(self) -> int:
        return self._int("ComicDrawingOutputExceptionRetries")

    def get_drawing_output_exception_retry_keywords(self) -> list[str]:
        keywords = get_config("ComicDrawingOutputExceptionRetryKeywords", [])
        if not isinstance(keywords, list):
            keywords = []
        return [str(keyword) for keyword in keywords if str(keyword).strip()]

    def get_drawing_retry_delay(self) -> int:
        return self._int("ComicDrawingRetryDelay")

    def get_drawing_network_retries(self) -> int:
        return self._int("ComicDrawingNetworkRetries")

    def get_drawing_download_proxy(self) -> str:
        return self._str("ComicDrawingDownloadProxy").strip()

    def get_drawing_proxy(self) -> str:
        """获取漫画生图 API 的全局代理地址。"""
        return self._str("ComicDrawingProxy").strip()

    def get_enable_comic_album_upload(self) -> bool:
        return self._bool("UploadEnableComicAlbumUpload")

    def get_comic_album_name(self) -> str:
        return self._str("UploadComicAlbumName").strip()

    def _legacy_comic_references(self) -> list:
        value = get_config("ComicDrawingReferenceImage", "[]")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        return value if isinstance(value, list) else []

    def get_drawing_reference_image(self) -> str:
        """获取当前选中的漫画参考图相对路径。"""
        character = self.get_selected_comic_character()
        reference_images = character.get("reference_images", []) if character else self._legacy_comic_references()
        if isinstance(reference_images, str):
            reference_images = [reference_images]
        if not isinstance(reference_images, list):
            return ""
        for reference_image in reversed(reference_images):
            if isinstance(reference_image, str) and reference_image.strip():
                return reference_image.strip()
        return ""

    def get_drawing_reference_images(self) -> list[str]:
        """Get every valid reference image for the selected comic character."""
        character = self.get_selected_comic_character()
        reference_images = character.get("reference_images", []) if character else self._legacy_comic_references()
        if isinstance(reference_images, str):
            reference_images = [reference_images]
        if not isinstance(reference_images, list):
            return []
        return [
            reference_image.strip()
            for reference_image in reference_images
            if isinstance(reference_image, str) and reference_image.strip()
        ]

    def get_selected_comic_character(self) -> dict | None:
        """获取本次漫画应使用的角色方案。"""
        characters = get_config("ComicCharacters", [])
        enabled_characters = (
            [character for character in characters if isinstance(character, dict) and character.get("enable", True)]
            if isinstance(characters, list)
            else []
        )
        if not enabled_characters:
            return None
        if not self._bool("ComicRandomDailyComicCharacter"):
            return enabled_characters[0]
        timezone_name = os.environ.get("TZ", "").strip()
        if timezone_name:
            try:
                current_time = datetime.now(ZoneInfo(timezone_name))
            except ZoneInfoNotFoundError:
                logger.warning(f"环境变量 TZ={timezone_name!r} 不是有效 IANA 时区，每日漫画角色将使用系统本地时区。")
                current_time = datetime.now().astimezone()
        else:
            current_time = datetime.now().astimezone()
        today = current_time.date().isoformat()
        state_path = self._get_comic_character_state_path()
        state = self._read_comic_character_state(state_path)
        selected_character = state.get("selected_character")
        if state.get("date") == today and selected_character in enabled_characters:
            return selected_character
        selected_character = random.choice(enabled_characters)
        self._save_comic_character_state(state_path, {"date": today, "selected_character": selected_character})
        character_name = str(selected_character.get("name", "")).strip() or "未命名方案"
        logger.info(f"今日漫画角色已随机选择: {character_name}")
        return selected_character

    def get_comic_character_persona_id(self, character: dict | None) -> str:
        """获取角色方案绑定的漫画专用人格 ID。"""
        if not isinstance(character, dict):
            return ""
        return str(character.get("persona_id", "")).strip()

    def get_comic_character_storyboard_prompt(self, character: dict | None) -> str:
        """获取角色专属分镜提示词，未配置时回退全局默认模板。"""
        if isinstance(character, dict):
            prompt = str(character.get("storyboard_prompt", "")).strip()
            if prompt:
                return prompt
        return self.get_comic_storyboard_prompt()

    @staticmethod
    def _get_comic_character_state_path() -> Path:
        """获取每日随机角色状态文件路径。"""
        return PluginPaths.get_data_dir(PLUGIN_NAME) / "comic_character_daily_state.json"

    @staticmethod
    def _read_comic_character_state(state_path: Path) -> dict:
        """读取每日随机角色状态。"""
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _save_comic_character_state(state_path: Path, state: dict) -> None:
        """原子写入每日随机角色状态。"""
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = state_path.with_suffix(".tmp")
            temporary_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            temporary_path.replace(state_path)
        except OSError as exc:
            logger.warning(f"保存每日漫画角色选择失败: {exc}")

    def get_comic_storyboard_prompt(self, style: str = "comic_storyboard_prompt") -> str:
        """获取分镜生成提示词模板"""
        key = self._prompt_key("comic_analysis_prompts", style)
        return self._str(key) if key else ""

    def save_config(self):
        """保存插件配置。"""
        logger.info("配置已保存")

    def reload_config(self):
        """重新加载配置"""
        logger.info("配置重载完成")
