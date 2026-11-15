"""
DailyAnalyisis 插件
基于群聊记录生成精美的日常分析报告，包含话题总结、用户画像、统计数据等

重构版本 - 使用模块化架构，支持跨平台
"""

from __future__ import annotations

import os
import asyncio
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from collections.abc import Callable

from gsuid_core.bot import Bot
from gsuid_core.models import Event, Message
from gsuid_core.segment import MessageSegment

from .version import PLUGIN_VERSION
from .daily_help import get_help
from .utils.logger import logger
from .utils.gs_event import event_umo
from .utils.constants import PLUGIN_NAME
from .daily_ai.context import PluginBase, PluginContext, shutdown_playwright_browser
from .utils.resilience import GlobalRateLimiter
from .daily_config.paths import PluginPaths
from .utils.trace_context import TraceContext
from .daily_ai.llm_analyzer import LLMAnalyzer
from .daily_report.generators import ReportGenerator
from .daily_message.bot_manager import BotManager
from .daily_comic.drawing_client import DrawingClient
from .daily_config.config_manager import ConfigManager
from .daily_report.message_sender import (
    MessageSender,
    file_message,
    image_message,
    get_group_subscription,
)
from .daily_report.activity_charts import ActivityVisualizer
from .daily_report.overview_report import build_overview_html
from .daily_message.history_manager import HistoryManager
from .daily_message.checkpoint_store import CheckpointStore
from .daily_scheduler.auto_scheduler import AutoScheduler
from .daily_webui.plugin_page_bridge import PluginPageWebUIBridge
from .daily_message.incremental_store import IncrementalStore
from .daily_webui.active_task_manager import ActiveTaskManager
from .daily_message.trace_sqlite_store import TraceSQLiteStore
from .daily_analysis.statistics_service import StatisticsService
from .daily_comic.comic_application_service import ComicApplicationService
from .daily_message.platform_group_registry import (
    PlatformGroupRegistry,
)
from .daily_analysis.analysis_domain_service import AnalysisDomainService
from .daily_settings.template_command_service import (
    TemplateCommandService,
)
from .daily_analysis.incremental_merge_service import IncrementalMergeService
from .daily_analysis.analysis_application_service import (
    DuplicateGroupTaskError,
    AnalysisApplicationService,
)


class GroupDailyAnalysis(PluginBase):
    """群分析插件主类"""

    # ── 显式类型声明 (由 __init__ 初始化) ──
    config_manager: ConfigManager
    bot_manager: BotManager
    history_manager: HistoryManager
    report_generator: ReportGenerator
    html_render: Callable
    platform_group_registry: PlatformGroupRegistry
    statistics_service: StatisticsService
    analysis_domain_service: AnalysisDomainService
    llm_analyzer: LLMAnalyzer
    incremental_store: IncrementalStore
    incremental_merge_service: IncrementalMergeService
    analysis_service: AnalysisApplicationService
    template_command_service: TemplateCommandService
    auto_scheduler: AutoScheduler
    message_sender: MessageSender
    trace_store: TraceSQLiteStore
    checkpoint_store: CheckpointStore
    active_task_manager: ActiveTaskManager
    webui_bridge: PluginPageWebUIBridge

    def __init__(self, context: PluginContext, config: SimpleNamespace | None = None):
        super().__init__(context)

        # 1. 基础设施层
        self.config_manager = ConfigManager()
        self.bot_manager = BotManager(self.config_manager)
        self.bot_manager.set_context(context)
        self.bot_manager.set_plugin_instance(self)
        self.history_manager = HistoryManager(self)

        plugin_data_dir = PluginPaths.get_data_dir(PLUGIN_NAME)
        self.plugin_data_dir = plugin_data_dir

        self.report_generator = ReportGenerator(self.config_manager, plugin_data_dir)

        # Telegram 注册表 (持久层)
        self.platform_group_registry = PlatformGroupRegistry(self)

        # 1.1 Trace & Checkpoint 基础设施 (持久化)
        self.trace_store = TraceSQLiteStore(plugin_data_dir / "traces.db")
        TraceContext.set_global_store(self.trace_store)
        self.checkpoint_store = CheckpointStore(plugin_data_dir / "traces.db")

        # 2. 领域层
        activity_visualizer = ActivityVisualizer()
        self.statistics_service = StatisticsService(activity_visualizer)
        self.analysis_domain_service = AnalysisDomainService()

        # 3. 分析核心 (LLM Bridge)
        self.llm_analyzer = LLMAnalyzer(context, self.config_manager)

        # 4. 增量分析组件
        self.incremental_store = IncrementalStore(self)
        self.incremental_merge_service = IncrementalMergeService()

        # 5. 应用层
        self.analysis_service = AnalysisApplicationService(
            self.config_manager,
            self.bot_manager,
            self.history_manager,
            self.report_generator,
            self.llm_analyzer,
            self.statistics_service,
            self.analysis_domain_service,
            incremental_store=self.incremental_store,
            incremental_merge_service=self.incremental_merge_service,
            checkpoint_store=self.checkpoint_store,
            html_render=self.html_render,
        )
        self.drawing_client = DrawingClient(self.config_manager)
        self.comic_service = ComicApplicationService(
            self.llm_analyzer,
            self.drawing_client,
            self.config_manager,
            plugin_data_dir,
            context=context,
        )

        # 漫画生成并发与同群任务去重。
        self._comic_semaphore = asyncio.Semaphore(max(1, self.config_manager.get_t2i_max_concurrent()))
        self._comic_group_tasks: dict[str, asyncio.Task] = {}
        self.template_command_service = TemplateCommandService(plugin_root=os.path.dirname(__file__))
        # 调度与发送
        self.message_sender = MessageSender(self.bot_manager, self.config_manager)
        self.auto_scheduler = AutoScheduler(
            self.config_manager,
            self.analysis_service,
            self.bot_manager,
            self.report_generator,
            self.html_render,
            plugin_instance=self,
        )

        # 1.2 WebUI 控制台与 Task Reaper 孤儿回收器
        self.active_task_manager = ActiveTaskManager(trace_store=self.trace_store)
        self.active_task_manager.start_reaper(interval_seconds=30, timeout_seconds=600)
        self.webui_bridge = PluginPageWebUIBridge(
            context=context,
            trace_store=self.trace_store,
            active_task_manager=self.active_task_manager,
            analysis_service=self.analysis_service,
            report_dispatcher=self.auto_scheduler.report_dispatcher,
            report_output_dir=plugin_data_dir / "reports",
        )
        self.webui_bridge.register_routes()

        # 同步全局限流并进行初始化配置
        GlobalRateLimiter.get_instance(self.config_manager.get_llm_max_concurrent())

        self._initialized = False
        self._terminating = False  # 生命周期标志
        self._init_lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

        # 异步注册任务，处理插件重载情况
        try:
            loop = asyncio.get_running_loop()
            self._init_task = loop.create_task(self._run_initialization("Plugin Reload/Init"))
            self._background_tasks.add(self._init_task)
            self._init_task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            self._init_task = None

    # orchestrators 缓存已移至 应用层逻辑 (分析服务) 或 暂时移除以简化。
    # 如果需要高性能缓存，后续可由 AnalysisApplicationService 内部维护。

    async def on_platform_loaded(self):
        """平台加载完成后初始化"""
        await self._run_initialization("Platform Loaded")

    async def initialize(self):
        """在 GsCore 插件生命周期中确认初始化已经完成。

        Returns:
            None: 初始化任务完成或恢复初始化完成后返回。
        """
        init_task = getattr(self, "_init_task", None)
        if init_task is None:
            await self._run_initialization("Plugin Lifecycle")
            return

        try:
            # 构造函数中的任务负责避免阻塞 GsCore 启动；生命周期入口负责等待
            # 它完成，确保插件重载不会在平台刷新之前被判定为加载成功。
            await asyncio.shield(init_task)
        except asyncio.CancelledError:
            if self._terminating:
                raise
            logger.warning("插件生命周期初始化任务被取消，正在执行恢复初始化。")
            await self._run_initialization("Plugin Lifecycle Recovery")

        if not self._initialized and not self._terminating:
            logger.warning("插件初始化未完成，正在执行一次生命周期恢复初始化。")
            await self._run_initialization("Plugin Lifecycle Recovery")

    async def _run_initialization(self, source: str):
        """执行插件初始化，避免阻塞平台启动流程。

        Args:
            source: 触发本次初始化的来源标识。

        Returns:
            None: 就地完成插件状态初始化或刷新。
        """
        async with self._init_lock:
            if self._terminating or not self.bot_manager:
                return

            try:
                # 核心配置迁移和定时任务只执行一次。
                if not self._initialized:
                    logger.info(f"开始初始化插件（来源：{source}）...")

                    # 升级旧版 prompt 模板并回写迁移后的配置。
                    try:
                        self.config_manager.upgrade_prompt_templates()
                    except Exception as e:
                        logger.warning(f"升级 prompt 模板失败：{e}")

                    try:
                        self.config_manager.migrate_legacy_configs()
                    except Exception as e:
                        logger.warning(f"迁移旧版配置失败：{e}")

                # GsCore 事件会持续刷新平台状态。平台发现只检查已创建的
                # 平台对象，可以安全重复执行；这样后加载的平台也不会被遗漏。
                await self.bot_manager.initialize_from_config()

                if self._initialized:
                    logger.debug(f"插件已完成初始化，已刷新平台状态（来源：{source}）。")
                    return

                # 插件基础设施准备完成后注册定时任务。
                if self.auto_scheduler:
                    self.auto_scheduler.schedule_jobs(self.context)
                    await self.auto_scheduler.start_incremental_trigger()

                self._initialized = True
                self._discovery_run = True
                logger.info(f"插件初始化完成（来源：{source}）")

            except Exception as e:
                logger.error(f"插件初始化失败：{e}", exc_info=True)

    async def terminate(self):
        """插件被卸载/停用时调用，清理资源"""
        if self._terminating:
            return
        self._terminating = True

        try:
            logger.info("开始清理 DailyAnalyisis 插件资源...")

            # 1. 停止所有后台任务
            if self._background_tasks:
                logger.info(f"正在取消 {len(self._background_tasks)} 个运行中的任务...")
                for task in self._background_tasks:
                    if not task.done():
                        task.cancel()

                # 等待任务结束，给予 3 秒宽限期
                try:
                    await asyncio.wait(list(self._background_tasks), timeout=3.0)
                except Exception:
                    pass
                self._background_tasks.clear()

            # 2. 停止各个组件 (顺序：先调度器，后底层服务)
            if self.auto_scheduler:
                logger.debug("正在停止自动调度器...")
                await self.auto_scheduler.shutdown(self.context)

            if self.report_generator:
                await self.report_generator.close()

            await shutdown_playwright_browser()

            # 3. [关键修复] 只有在任务全部清理后，才清理引用。
            # 实际上，在 terminate 结束后，self 本身就会被 GC 释放，
            # 这里的显式 None 更多是为了协助循环引用清理，但由于异步任务存在竞态，
            # 我们可以通过 check _terminating 标志位来保护。
            # 为了彻底解决 #125，我们保留引用，让 GC 自然回收。
            logger.info("DailyAnalyisis 插件资源清理完成")

        except Exception as e:
            logger.error(f"插件资源清理失败: {e}")

    # ==================== 群消息增量计数与事件缓存 ====================

    async def count_incremental_group_message(self, event: Event):
        """记录目标群消息，达到配置阈值后触发增量分析。

        Args:
            event: GsCore 群消息事件。

        Returns:
            None: 计数完成后继续消息流水线。
        """
        # QQ 官方和 Telegram 会在各自的持久化钩子成功后计数，避免任务先于入库启动。
        if str(event.real_bot_id or event.bot_id or "").strip().lower() in {
            "qq_official",
            "qq_official_webhook",
            "telegram",
        }:
            return
        if self.auto_scheduler:
            await self.auto_scheduler.record_incremental_message(event)

    async def get_telegram_seen_group_ids(self, platform_id: str | None = None) -> list[str]:
        """读取 Telegram 已见群/话题列表（给调度器回退使用）。"""
        return await self.platform_group_registry.get_all_group_ids(platform_id)

    async def get_seen_group_ids(self, platform_id: str | None = None) -> list[str]:
        """读取任意事件驱动平台已经见过的群组。"""
        return await self.platform_group_registry.get_all_group_ids(platform_id)

    def _get_group_id_from_event(self, event: Event) -> str | None:
        """从消息事件中安全获取群组 ID"""
        return str(event.group_id) if event.group_id else None

    def _get_platform_id_from_event(self, event: Event) -> str:
        """从消息事件中获取平台唯一 ID"""
        return str(event.WS_BOT_ID or event.real_bot_id or event.bot_id or "gscore")

    async def analyze_group_daily(self, bot: Bot, event: Event, days: int | None = None) -> None:
        """分析群聊日常活动。用法: day群分析 [天数]"""
        if self._terminating:
            return
        current_task = asyncio.current_task()
        if current_task:
            self._background_tasks.add(current_task)

        trace = None
        trace_id = ""
        try:
            group_id = self._get_group_id_from_event(event)
            platform_id = self._get_platform_id_from_event(event)
            if not group_id:
                await bot.send("❌ 请在群聊中使用此命令")
                return

            self.bot_manager.update_from_event(bot, event)
            if not self.config_manager.is_group_allowed(event_umo(event)):
                await bot.send("❌ 此群未启用日常分析功能")
                return

            group_name = ""
            adapter = self.bot_manager.get_adapter(platform_id)
            if adapter:
                info = await adapter.get_group_info(group_id)
                if info and info.group_name:
                    group_name = info.group_name

            trace_id = TraceContext.generate(prefix="manual", group_name=group_name or group_id)
            trace = TraceContext.set(
                trace_id=trace_id,
                group_id=group_id,
                group_name=group_name,
                platform=platform_id or "",
                trigger_type="manual",
            )
            if self.active_task_manager:
                await self.active_task_manager.register_task(
                    task_id=trace_id,
                    group_id=group_id,
                    group_name=group_name,
                    platform=platform_id or "",
                    trigger_type="manual",
                    current_stage="FETCH_MESSAGES",
                    asyncio_task=current_task,
                )

            await bot.send("🔍 正在启动分析引擎，正在拉取最近消息...")
            result = await self.analysis_service.execute_daily_analysis(
                group_id=group_id, platform_id=platform_id, manual=True, days=days
            )

            if not result.get("success"):
                reason = result.get("reason")
                if trace and trace.status == "running":
                    trace.finish(
                        status="failed",
                        error_message=f"Analysis skipped/failed: {reason}",
                    )
                if reason == "no_messages":
                    await bot.send("❌ 未找到足够的群聊记录")
                elif reason == "muted":
                    logger.warning(
                        "群 %s 开启了全群禁言或对 Bot 禁言，跳过本次群分析",
                        group_id,
                    )
                else:
                    await bot.send("❌ 分析失败，原因未知")
                return

            if self.active_task_manager:
                await self.active_task_manager.update_stage(trace_id, "RENDER_REPORT")

            await self._send_analysis_report(bot, result)
            if trace and trace.status == "running":
                trace.finish(status="succeeded")

        except DuplicateGroupTaskError:
            if trace and trace.status == "running":
                trace.finish(status="aborted", error_message="Task already running in group")
            await bot.send("📊 该群的分析任务正在执行中，请稍后再试哦~")
        except asyncio.CancelledError:
            if trace and trace.status == "running":
                trace.finish(status="aborted", error_message="Task cancelled by system")
            logger.info("群分析任务被取消 (插件重载或卸载)")
        except Exception as e:
            if trace and trace.status == "running":
                trace.finish(status="failed", error_message=str(e))
            logger.error("群分析失败: %s", e, exc_info=True)
            await bot.send(f"❌ 分析失败: {e}。请检查网络连接和LLM配置，或联系管理员")
        finally:
            if trace_id and self.active_task_manager:
                await self.active_task_manager.finish_task(trace_id)
            if current_task:
                self._background_tasks.discard(current_task)

    async def generate_group_comic(self, bot: Bot, event: Event, days: int | None = None) -> None:
        """生成群聊趣味漫画。用法: day群漫画 [天数]"""
        if self._terminating:
            return
        current_task = asyncio.current_task()
        if current_task:
            self._background_tasks.add(current_task)

        try:
            group_id = self._get_group_id_from_event(event)
            platform_id = self._get_platform_id_from_event(event)
            if not group_id:
                await bot.send("❌ 请在群聊中使用此命令")
                return

            self.bot_manager.update_from_event(bot, event)
            check_target = event_umo(event)

            if not self.config_manager.get_enable_daily_comic():
                await bot.send("❌ 漫画生成功能未启用")
                return
            if not self.config_manager.is_comic_group_allowed(check_target):
                await bot.send("❌ 此群未启用漫画生成功能")
                return

            task_key = f"{platform_id or 'default'}:{group_id}"
            existing_task = self._comic_group_tasks.get(task_key)
            if existing_task and not existing_task.done():
                await bot.send("🎨 该群已有漫画任务正在执行，请稍后再试哦~")
                return

            TraceContext.set(TraceContext.generate(prefix="comic", group_name=group_id))
            await bot.send("🎨 正在提取群聊话题并生成漫画...")

            result = await self.analysis_service.execute_comic_topic_analysis(
                group_id=group_id, platform_id=platform_id, days=days
            )
            if not result.get("success"):
                reason = result.get("reason")
                if reason == "no_messages":
                    await bot.send("❌ 未找到可用于生成漫画的群聊记录")
                elif reason == "no_topics":
                    await bot.send("❌ 未提取到可用于生成漫画的话题")
                elif reason == "muted":
                    logger.warning("群 %s 开启了禁言，跳过手动漫画回复", group_id)
                else:
                    await bot.send("❌ 漫画话题提取失败，原因未知")
                return

            status = self._try_trigger_comic_generation(
                group_id,
                platform_id,
                {"topics": result.get("topics", [])},
                require_auto_enabled=False,
                bot=bot,
            )
            if status == "started":
                await bot.send("✅ 漫画生成任务已启动，完成后会发送到群里")
            elif status == "duplicate":
                await bot.send("🎨 该群已有漫画任务正在执行，请稍后再试哦~")
            elif status == "blocked":
                await bot.send("❌ 此群未启用漫画生成功能")
            elif status == "no_topics":
                await bot.send("❌ 未提取到可用于生成漫画的话题")
            else:
                await bot.send("⚠️ 漫画生成任务未启动，请查看插件日志")

        except DuplicateGroupTaskError:
            await bot.send("🎨 该群的漫画话题提取任务正在执行，请稍后再试哦~")
        except asyncio.CancelledError:
            logger.info("手动漫画任务被取消（插件正在关闭或重载）")
        except Exception as e:
            logger.error("手动漫画生成失败: %s", e, exc_info=True)
            await bot.send(f"❌ 漫画生成失败: {e}。请检查消息获取、LLM 和绘图配置")
        finally:
            if current_task:
                self._background_tasks.discard(current_task)

    def _save_report_to_history(self, image_url: str, group_id: str) -> None:
        """将生成的图片报告副本保存到持久化 reports 目录。"""
        try:
            reports_dir = self.plugin_data_dir / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = reports_dir / f"report_{group_id}_{ts_str}.jpg"
            if Path(image_url).exists():
                import shutil

                shutil.copy2(image_url, dest)
            elif image_url.startswith("base64://"):
                import base64

                dest.write_bytes(base64.b64decode(image_url[9:]))
        except Exception as e:
            logger.warning("保存历史报告副本失败: %s", e)

    async def _send_analysis_report(self, bot: Bot, result: dict) -> bool:
        """渲染并发送分析报告，返回是否至少发送成功一次。"""
        if self._terminating or not self.config_manager:
            logger.warning("插件正在关闭，停止发送报告")
            return False

        group_id = result["group_id"]
        platform_id = result["platform_id"]
        analysis_result = result["analysis_result"]
        adapter = result["adapter"]
        self._try_trigger_comic_generation(group_id, platform_id, analysis_result, bot=bot)
        output_format = self.config_manager.get_output_format()[0]
        is_qq_official = adapter.get_platform_name() in {
            "qq_official",
            "qq_official_webhook",
        }

        async def avatar_url_getter(user_id: str) -> str | None:
            return await adapter.get_user_avatar_url(user_id)

        async def nickname_getter(user_id: str) -> str | None:
            member = await adapter.get_member_info(group_id, user_id)
            if member:
                return member.card or member.nickname
            return None

        trace = TraceContext.current()
        if output_format == "image":
            if trace:
                with trace.span("RENDER_REPORT", {"format": "image"}):
                    image_url, _html = await self.report_generator.generate_image_report(
                        analysis_result,
                        group_id,
                        self.html_render,
                        avatar_url_getter=avatar_url_getter,
                        nickname_getter=nickname_getter,
                        avatar_cache_namespace=platform_id,
                        allow_alphanumeric_user_ids=is_qq_official,
                    )
            else:
                image_url, _html = await self.report_generator.generate_image_report(
                    analysis_result,
                    group_id,
                    self.html_render,
                    avatar_url_getter=avatar_url_getter,
                    nickname_getter=nickname_getter,
                    avatar_cache_namespace=platform_id,
                    allow_alphanumeric_user_ids=is_qq_official,
                )

            if image_url:
                self._save_report_to_history(image_url, group_id)
                caption = TraceContext.make_report_caption() if self.config_manager.get_show_report_caption() else ""
                await bot.send(image_message(image_url))
                if caption:
                    await bot.send(caption)
                return True

            logger.warning("图片报告发送失败，正在发送文本回退报告。群: %s", group_id)
            return await self._send_text_reports(bot, analysis_result, is_qq_official)

        if output_format == "html":
            cur_trace_id = trace.trace_id if trace else None
            html_path, _json_path = await self.report_generator.generate_html_report(
                analysis_result,
                group_id,
                avatar_url_getter=avatar_url_getter,
                nickname_getter=nickname_getter,
                avatar_cache_namespace=platform_id,
                allow_alphanumeric_user_ids=is_qq_official,
                trace_id=cur_trace_id,
            )
            if not html_path:
                await bot.send("⚠️ HTML 生成失败。")
                return False

            if self.config_manager.get_html_only_url():
                base_url = self.config_manager.get_html_base_url()
                if base_url and base_url.strip():
                    html_output_dir = self.config_manager.get_html_output_dir()
                    if not html_output_dir:
                        html_output_dir = str(PluginPaths.get_data_dir(PLUGIN_NAME) / "self_hosted_html_reports")
                    rel_path = os.path.relpath(html_path, html_output_dir)
                    encoded_url_path = quote(rel_path.replace(os.sep, "/").lstrip("/"), safe="/")
                    await bot.send(f"📊 今日群聊分析报告已生成：\n{base_url.rstrip('/')}/{encoded_url_path}")
                    return True
                logger.warning(
                    "群 %s 开启了仅发送外链，但未配置 html_base_url，回退发送文件。",
                    group_id,
                )

            caption = self.report_generator.build_html_caption(html_path)
            await bot.send(file_message(html_path))
            if caption:
                await bot.send(caption)
            return True

        return await self._send_text_reports(bot, analysis_result, is_qq_official)

    async def show_overview(self, bot: Bot, event: Event) -> None:
        """生成并发送插件运行总览图片。"""
        try:
            summary = self.trace_store.get_metrics_summary()
            trends = self.trace_store.get_analytics_trends("day", 14)
            active_tasks = self.active_task_manager.get_active_tasks()
            overview_html = build_overview_html(summary, trends, active_tasks)
            image_data = await self.html_render(
                overview_html,
                {},
                options={
                    "type": "png",
                    "quality": 95,
                    "viewport": {"width": 1120, "height": 900},
                },
            )
            if isinstance(image_data, bytes) and image_data:
                await bot.send(MessageSegment.image(image_data))
                return
            logger.warning("概览图片渲染结果为空")
            await bot.send("⚠️ 概览图片生成失败，请稍后重试")
        except Exception as exc:
            logger.error("生成运行概览失败: %s", exc, exc_info=True)
            await bot.send("⚠️ 运行概览生成失败，请检查 WebUI 渲染日志")

    def _try_trigger_comic_generation(
        self,
        group_id: str,
        platform_id: str | None,
        analysis_result: dict,
        *,
        require_auto_enabled: bool = True,
        bot: Bot | None = None,
    ) -> str:
        if self._terminating:
            return "terminating"
        if not self.config_manager.get_enable_daily_comic():
            return "disabled"
        if require_auto_enabled and not self.config_manager.get_enable_auto_daily_comic():
            return "auto_disabled"

        umo = f"{platform_id}:GroupMessage:{group_id}" if platform_id else group_id
        if not self.config_manager.is_comic_group_allowed(umo, require_auto_enabled):
            logger.info(
                "群 %s 未通过漫画名单判定，跳过漫画生成。platform=%s",
                group_id,
                platform_id or "default",
            )
            return "blocked"

        topics = analysis_result.get("topics", [])
        statistics = analysis_result.get("statistics")
        if not topics and statistics:
            topics = getattr(statistics, "topics", [])

        comic_topics = []
        for topic in topics if isinstance(topics, list) else []:
            title = topic.get("topic", "") if isinstance(topic, dict) else getattr(topic, "topic", "")
            detail = topic.get("detail", "") if isinstance(topic, dict) else getattr(topic, "detail", "")
            if str(title).strip():
                comic_topics.append({"topic": str(title).strip(), "detail": str(detail).strip()})
        if not comic_topics:
            logger.warning("群 %s 没有有效话题，跳过漫画生成。", group_id)
            return "no_topics"

        task_key = f"{platform_id or 'default'}:{group_id}"
        existing_task = self._comic_group_tasks.get(task_key)
        if existing_task and not existing_task.done():
            logger.info("群 %s 已有漫画任务等待或执行，跳过重复任务。", group_id)
            return "duplicate"

        task = asyncio.create_task(self._trigger_comic_generation(comic_topics, group_id, platform_id, umo, bot=bot))
        self._comic_group_tasks[task_key] = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(
            lambda completed_task: (
                self._comic_group_tasks.pop(task_key, None)
                if self._comic_group_tasks.get(task_key) is completed_task
                else None
            )
        )
        return "started"

    async def _trigger_comic_generation(
        self,
        topics: list[dict],
        group_id: str,
        platform_id: str | None,
        umo: str,
        bot: Bot | None = None,
    ) -> None:
        """后台生成并发送漫画。"""
        async with self._comic_semaphore:
            if self._terminating:
                return
            try:
                comic_bytes, fallback_url = await self.comic_service.generate_comic(topics, group_id, umo)
                if comic_bytes:
                    ext = self._detect_image_ext(comic_bytes)
                    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    trace = TraceContext.current()
                    trace_suffix = f"_{trace.trace_id}" if trace else ""
                    filename = f"comic_{group_id}_{ts_str}{trace_suffix}{ext}"
                    reports_dir = self.plugin_data_dir / "reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    comic_file_path = reports_dir / filename
                    comic_file_path.write_bytes(comic_bytes)

                    if trace:
                        rfiles = trace.metadata.setdefault("report_files", [])
                        rfiles.append(
                            {
                                "filename": filename,
                                "format": "image",
                                "report_type": "comic",
                                "path": str(comic_file_path.resolve()),
                            }
                        )

                    await self._send_comic_message(
                        group_id,
                        MessageSegment.image(comic_file_path),
                        bot=bot,
                    )
                elif fallback_url:
                    logger.warning(
                        "群 %s 漫画下载失败，发送 fallback URL: %s",
                        group_id,
                        fallback_url,
                    )
                    await self._send_comic_message(
                        group_id,
                        MessageSegment.text(
                            f"✨ 今日群聊趣味漫画已生成，但图片下载失败，请点击链接查看：\n{fallback_url}"
                        ),
                        bot=bot,
                    )
            except Exception as e:
                logger.error("群 %s 生成/发送漫画失败: %s", group_id, e, exc_info=True)

    @staticmethod
    def _detect_image_ext(data: bytes) -> str:
        """从图片字节嗅探扩展名，无法识别时回退 .png。"""
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return ".gif"
        if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
            return ".avif"
        return ".png"

    async def _send_comic_message(
        self,
        bot: Bot | None,
        group_id: str,
        message: Message | str,
    ) -> None:
        """命令路径用 Bot 发送，定时路径用该群的定时分析订阅发送。"""
        if bot is not None:
            await bot.send(message)
            return

        subscription = await get_group_subscription(group_id)
        if subscription is None:
            logger.warning("群 %s 漫画推送跳过：没有可用的 Bot 或定时分析订阅", group_id)
            return
        await subscription.send(message)

    async def _trigger_comic_generation(
        self,
        topics: list[dict],
        group_id: str,
        platform_id: str | None,
        umo: str,
        bot: Bot | None = None,
    ):
        """后台生成并上传漫画，通过信号量控制并发"""
        async with self._comic_semaphore:
            if self._terminating:
                return
            try:
                comic_bytes, fallback_url = await self.comic_service.generate_comic(topics, group_id, umo)
                if comic_bytes:
                    logger.info(f"群 {group_id} 漫画生成成功，准备发送和保存副本...")
                    ext = self._detect_image_ext(comic_bytes)
                    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    trace = TraceContext.current()
                    trace_suffix = f"_{trace.trace_id}" if trace else ""
                    filename = f"comic_{group_id}_{ts_str}{trace_suffix}{ext}"

                    reports_dir = (
                        getattr(self, "plugin_data_dir", None) or PluginPaths.get_data_dir(PLUGIN_NAME)
                    ) / "reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    comic_file_path = reports_dir / filename
                    comic_file_path.write_bytes(comic_bytes)

                    if trace:
                        rfiles = trace.metadata.setdefault("report_files", [])
                        rfiles.append(
                            {
                                "filename": filename,
                                "format": "image",
                                "report_type": "comic",
                                "path": str(comic_file_path.resolve()),
                            }
                        )

                    try:
                        if self._terminating:
                            return

                        # 命令路径走 bot.send，定时路径回退到定时分析订阅
                        await self._send_comic_message(
                            bot,
                            group_id,
                            MessageSegment.image(comic_file_path),
                        )
                    except Exception as e:
                        logger.warning(f"投递群 {group_id} 漫画失败: {e}")
                elif fallback_url:
                    # 图片 API 返回了 URL 但下载失败，把链接发到群里作为兜底
                    logger.warning(f"群 {group_id} 漫画下载失败，发送 fallback URL 到群中: {fallback_url}")
                    try:
                        await self._send_comic_message(
                            bot,
                            group_id,
                            f"✨ 今日群聊趣味漫画已生成，但图片下载失败，请点击链接查看：\n{fallback_url}",
                        )
                    except Exception as e:
                        logger.warning(f"投递群 {group_id} 漫画链接失败: {e}")
            except Exception as e:
                logger.error(f"群 {group_id} 生成/上传漫画时发生错误: {e}", exc_info=True)

    async def _generate_text_reports(
        self, analysis_result: dict, use_qq_official_markdown: bool
    ) -> tuple[str, str | None]:
        """Generate text or QQ-official-markdown reports."""
        if use_qq_official_markdown:
            return await self.report_generator.generate_qq_official_markdown_report(analysis_result, self.html_render)
        return self.report_generator.generate_text_report(analysis_result), None

    async def _send_text_reports(
        self,
        bot: Bot,
        analysis_result: dict,
        use_qq_official_markdown: bool,
    ) -> bool:
        """通过 GsCore Bot 发送文本报告。"""
        text_report, _fallback = await self._generate_text_reports(analysis_result, use_qq_official_markdown)
        if not text_report.strip():
            return False
        await bot.send(text_report)
        return True

    async def set_output_format(self, bot: Bot, event: Event, format_input: str = "") -> None:
        """
        设置分析报告输出格式（跨平台支持）
        用法: day设置格式 [格式名称或序号] 或 image,html 等逗号分隔的组合
        """
        available_formats = ["image", "text", "html"]
        format_display_names = {
            "image": "图片格式 (默认)",
            "text": "文本格式",
            "html": "交互式 HTML 网页",
        }

        if not format_input:
            current = ", ".join(self.config_manager.get_output_format())
            format_list_str = "\n".join(
                [f"【{i}】{f} - {format_display_names[f]}" for i, f in enumerate(available_formats, start=1)]
            )
            await bot.send(f"""📊 当前输出格式: {current}

可用格式:
{format_list_str}

用法: day设置格式 [名称或序号] 如 day设置格式 image,html""")
            return

        target_format = None
        # 尝试由序号选择
        if format_input.isdigit():
            idx = int(format_input) - 1
            if 0 <= idx < len(available_formats):
                target_format = available_formats[idx]

        # 尝试按名称选择
        if not target_format:
            input_lower = format_input.lower()
            if input_lower in available_formats:
                target_format = input_lower

        # 支持逗号分隔的多个格式
        if not target_format:
            parts = [f.strip() for f in format_input.replace("，", ",").split(",")]
            if all(p in available_formats for p in parts) and len(parts) > 1:
                try:
                    self.config_manager.set_output_format(parts)
                    await bot.send(f"✅ 输出格式已设置为: {', '.join(parts)}")
                except Exception as e:
                    await bot.send(f"❌ 设置失败: {e}")
                return

        if not target_format:
            await bot.send(
                f"❌ 无效的格式类型 '{format_input}'。可用: "
                f"{', '.join(available_formats)} 或序号 1-{len(available_formats)}"
            )
            return

        try:
            self.config_manager.set_output_format(target_format)  # type: ignore[arg-type]
            await bot.send(f"✅ 输出格式已设置为: {target_format}")
        except Exception as e:
            await bot.send(f"❌ 设置失败: {e}")

    async def set_report_template(self, bot: Bot, event: Event, template_input: str = "") -> None:
        """
        设置分析报告模板（跨平台支持）
        用法: day设置模板 [模板名称或序号]
        """
        available_templates = await self.template_command_service.list_available_templates()

        if not template_input:
            current_template = self.config_manager.get_report_template()
            template_list_str = "\n".join([f"【{i}】{t}" for i, t in enumerate(available_templates, start=1)])
            random_hint = "【随机】随机模板（每份报告随机选择一个可用主题）"
            await bot.send(f"""🎨 当前报告模板: {current_template}

可用模板:
{random_hint}
{template_list_str}

用法: day设置模板 [模板名称或序号]
随机模式: day设置模板 随机
💡 使用 day查看模板 查看预览图""")
            return

        template_name, parse_error = self.template_command_service.parse_template_input(
            template_input, available_templates
        )
        if parse_error:
            await bot.send(parse_error)
            return

        if not template_name:
            await bot.send(f"❌ 无法解析模板输入: {template_input}")
            return

        if template_name != "random" and not await self.template_command_service.template_exists(template_name):
            await bot.send(f"❌ 模板 '{template_name}' 不存在")
            return

        self.config_manager.set_report_template(template_name)
        if template_name == "random":
            await bot.send("✅ 报告模板已设置为: 随机（每份报告随机选择一个可用主题）")
        else:
            await bot.send(f"✅ 报告模板已设置为: {template_name}")

    async def view_templates(self, bot: Bot, event: Event) -> None:
        """
        查看所有可用的报告模板及预览图（跨平台支持）
        用法: day查看模板
        """
        available_templates = await self.template_command_service.list_available_templates()

        if not available_templates:
            await bot.send("❌ 未找到任何可用的报告模板")
            return

        current_template = self.config_manager.get_report_template()
        bot_id = str(event.bot_self_id or "")
        preview_nodes = self.template_command_service.build_template_preview_nodes(
            available_templates=available_templates,
            current_template=current_template,
            bot_id=bot_id,
        )
        await bot.send(preview_nodes)

    async def show_help(self, bot: Bot, event: Event) -> None:
        """发送插件指令与配置帮助。"""
        await bot.send(await get_help())

    async def show_changelog(self, bot: Bot, event: Event) -> None:
        """发送插件版本与更新日志。"""
        await bot.send(
            f"""📝 DailyAnalyisis 更新日志

当前版本: v{PLUGIN_VERSION}

v5.0.17
• 新增通过 JSON 生成的图片帮助，并接入 core帮助 插件帮助列表
• 更新插件 Logo，并同步 README 与 WebUI 展示头像

v5.0.16
• 为报告模板图标补充显式内联尺寸，并增强 SVG 尺寸兜底，兼容不同 GsCore/Takumi 渲染环境

v5.0.15
• 将绘图供应商配置改为可视化结构化表单，支持多供应商添加、编辑、删除及优先级配置

v5.0.14
• 在 GsCore 控制台新增独立的 DailyAnalyisis LLM配置 标签，集中管理 API Key、端点、模型及请求参数

v5.0.13
• 恢复插件独立 LLM 配置，API Key、端点和模型重新由本插件管理

v5.0.12
• 更新插件头像，并同步 README 与 WebUI 展示头像
• LLM 连接配置改为统一读取 GsCore AI 配置，插件不再重复保存 API Key、端点和模型

v5.0.11
• 更新插件头像，并同步 README 与 WebUI 展示头像

v5.0.10
• 修复 scrapbook（第 7 号模板）在部分生产渲染器中 SVG 图标异常放大的问题
• LLM 默认 API 端点改为 https://chisa.akiyo.fun/v1
• 新增 day帮助 和 day更新日志
• 完善帮助文档与版本信息

v5.0.9
• 增加报告模板随机模式
• 外部 WebUI 默认关闭，并支持独立密码保护
• README 增加完整效果图展示

提示: 更新插件后请重载 DailyAnalyisis；已有配置会保留，需要时可执行 day设置模板 ATRI。"""
        )

    async def analysis_settings(self, bot: Bot, event: Event, action: str = "status") -> None:
        """
        管理分析设置（跨平台支持）
        用法: day分析设置 [enable|disable|status|reload|test]
        - enable: 启用当前群的分析功能
        - disable: 禁用当前群的分析功能
        - status: 查看当前状态
        - reload: 重新加载配置并重启定时任务
        - test: 测试自动分析功能
        - filter_bot: 切换是否在分析中包含机器人自己的消息
        - incremental_debug: 切换增量分析立即报告模式（调试用）
        """
        group_id = self._get_group_id_from_event(event)

        if not group_id:
            await bot.send("❌ 请在群聊中使用此命令")
            return

        if action == "enable":
            await self._handle_settings_enable(bot, event, group_id)
            return
        elif action == "disable":
            await self._handle_settings_disable(bot, event, group_id)
            return

        elif action == "reload":
            self.auto_scheduler.schedule_jobs(self.context)
            await self._refresh_incremental_target_states()
            await bot.send("✅ 已重新加载配置并重启定时任务")
            return

        elif action == "test":
            check_target = event_umo(event)

            if not self.config_manager.is_group_allowed(check_target):
                await bot.send("❌ 请先启用当前群的分析功能")
                return

            await bot.send("🧪 开始测试自动分析功能...")

            self.bot_manager.update_from_event(bot, event)

            try:
                result = await self.auto_scheduler._perform_auto_analysis_for_group(group_id)
                if isinstance(result, dict) and result.get("success"):
                    await bot.send("✅ 自动分析及报告发送成功，请查看群消息")
                else:
                    reason = result.get("reason", "unknown") if isinstance(result, dict) else "invalid_result"
                    await bot.send(f"❌ 自动分析或报告发送失败: {reason}")
            except DuplicateGroupTaskError:
                await bot.send("📊 该群的分析任务正在执行中，请稍后再试哦~")
            except Exception as e:
                await bot.send(f"❌ 自动分析测试失败: {str(e)}")
            return

        elif action == "incremental_debug":
            current_state = self.config_manager.get_incremental_report_immediately()
            new_state = not current_state
            self.config_manager.set_incremental_report_immediately(new_state)
            status_text = "已启用" if new_state else "已禁用"
            await bot.send(f"✅ 增量分析立即报告模式: {status_text}")
            return

        elif action == "filter_bot":
            current = self.config_manager.get_filter_bot_messages()
            new_state = not current
            self.config_manager.set_filter_bot_messages(new_state)
            status_text = "已启用" if new_state else "已禁用"
            await bot.send(f"✅ 过滤机器人消息: {status_text}")
            return

        else:  # status
            check_target = event_umo(event)

            is_allowed = self.config_manager.is_group_allowed(check_target)
            status = "已启用" if is_allowed else "未启用"
            mode = self.config_manager.get_group_list_mode()

            auto_status = "已启用" if self.config_manager.is_auto_analysis_enabled() else "未启用"
            auto_time = self.config_manager.get_auto_analysis_time()

            output_format = self.config_manager.get_output_format()[0]
            min_threshold = self.config_manager.get_min_messages_threshold()

            # 增量分析状态
            incremental_enabled = self.config_manager.get_incremental_enabled()
            incremental_status_text = "未启用"
            if incremental_enabled:
                batch_messages = self.config_manager.get_incremental_min_messages()
                incremental_status_text = f"已启用 (每 {batch_messages} 条消息触发)"

            debug_report = self.config_manager.get_incremental_report_immediately()
            debug_status = "✅ 开启" if debug_report else "❌ 关闭"
            filter_bot = self.config_manager.get_filter_bot_messages()
            filter_bot_status = "✅ 开启" if filter_bot else "❌ 关闭"

            await bot.send(f"""📊 当前群分析功能状态:
• 群分析功能: {status} (模式: {mode})
• 自动分析: {auto_status} ({auto_time})
• 增量分析: {incremental_status_text}
• 调试模式: {debug_status} (增量立即报告)
• 过滤机器人: {filter_bot_status}
• 输出格式: {output_format}
• 最小消息数: {min_threshold}

💡 可用命令: enable, disable, status, reload, test, filter_bot, incremental_debug
💡 支持的输出格式: image, text (图片包含活跃度可视化)
💡 其他命令: day设置格式, day增量状态""")

    async def incremental_status(self, bot: Bot, event: Event) -> None:
        """查看当前增量分析状态（滑动窗口）"""
        group_id = self._get_group_id_from_event(event)
        if not group_id:
            await bot.send("❌ 请在群聊中使用此命令")
            return

        if not self.config_manager.get_incremental_enabled():
            await bot.send("ℹ️ 增量分析模式未启用，请在插件配置中开启")
            return

        import time as time_mod

        # 计算滑动窗口范围
        analysis_days = self.config_manager.get_analysis_days()
        window_end = time_mod.time()
        window_start = window_end - (analysis_days * 24 * 3600)

        # 查询窗口内的批次
        batches = await self.incremental_store.query_batches(group_id, window_start, window_end)

        if not batches:
            from datetime import datetime

            start_str = datetime.fromtimestamp(window_start).strftime("%m-%d %H:%M")
            end_str = datetime.fromtimestamp(window_end).strftime("%m-%d %H:%M")
            await bot.send(f"📊 滑动窗口 ({start_str} ~ {end_str}) 内尚无增量分析数据")
            return

        # 合并批次获取聚合视图
        state = self.incremental_merge_service.merge_batches(batches, window_start, window_end)
        summary = state.get_summary()

        await bot.send(
            f"📊 增量分析状态 (窗口: {summary['window']})\n"
            f"• 分析次数: {summary['total_analyses']}\n"
            f"• 累计消息: {summary['total_messages']}\n"
            f"• 话题数: {summary['topics_count']}\n"
            f"• 金句数: {summary['quotes_count']}\n"
            f"• 参与者: {summary['participants']}\n"
            f"• 高峰时段: {summary['peak_hours']}"
        )

    async def _handle_settings_enable(self, bot: Bot, event: Event, group_id: str) -> None:
        """协助逻辑：处理启用设置的分支逻辑"""
        mode = self.config_manager.get_group_list_mode()
        target_id = event_umo(event)

        if mode == "whitelist":
            glist = self.config_manager.get_group_list()
            if not self.config_manager.is_group_allowed(target_id):
                glist.append(target_id)
                self.config_manager.set_group_list(glist)
                self.auto_scheduler.schedule_jobs(self.context)
                await self._refresh_incremental_target_states()
                await bot.send(f"✅ 已将当前群加入白名单\nID: {target_id}")
            else:
                await bot.send("ℹ️ 当前群已在白名单中")
        elif mode == "blacklist":
            glist = self.config_manager.get_group_list()
            removed = False
            if target_id in glist:
                glist.remove(target_id)
                removed = True
            if group_id in glist:
                glist.remove(group_id)
                removed = True

            if removed:
                self.config_manager.set_group_list(glist)
                self.auto_scheduler.schedule_jobs(self.context)
                await self._refresh_incremental_target_states()
                await bot.send("✅ 已将当前群从黑名单移除")
            else:
                await bot.send("ℹ️ 当前群不在黑名单中")
        else:
            await bot.send("ℹ️ 当前为无限制模式，所有群聊默认启用")

    async def _handle_settings_disable(self, bot: Bot, event: Event, group_id: str) -> None:
        """协助逻辑：处理禁用设置的分支逻辑"""
        mode = self.config_manager.get_group_list_mode()
        target_id = event_umo(event)

        if mode == "whitelist":
            glist = self.config_manager.get_group_list()
            removed = False
            if target_id in glist:
                glist.remove(target_id)
                removed = True
            if group_id in glist:
                glist.remove(group_id)
                removed = True

            if removed:
                self.config_manager.set_group_list(glist)
                self.auto_scheduler.schedule_jobs(self.context)
                await self._refresh_incremental_target_states()
                await bot.send("✅ 已将当前群从白名单移除")
            else:
                await bot.send("ℹ️ 当前群不在白名单中")
        elif mode == "blacklist":
            glist = self.config_manager.get_group_list()
            if self.config_manager.is_group_allowed(target_id):
                glist.append(target_id)
                self.config_manager.set_group_list(glist)
                self.auto_scheduler.schedule_jobs(self.context)
                await self._refresh_incremental_target_states()
                await bot.send(f"✅ 已将当前群加入黑名单\nID: {target_id}")
            else:
                await bot.send("ℹ️ 当前群已在黑名单中")
        else:
            await bot.send("ℹ️ 当前为无限制模式，如需禁用请切换到黑名单模式")

    async def _refresh_incremental_target_states(self) -> None:
        """在插件内修改名单后立即同步增量状态。"""
        incremental_trigger = self.auto_scheduler.incremental_trigger
        if incremental_trigger:
            await incremental_trigger.refresh_target_states()
