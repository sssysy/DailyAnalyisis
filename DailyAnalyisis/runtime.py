from __future__ import annotations

from collections.abc import Callable, Awaitable

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from .plugin import GroupDailyAnalysis
from .daily_config import DailyConfig
from .daily_ai.context import PluginContext


class PluginRuntime:
    def __init__(self) -> None:
        self.plugin: GroupDailyAnalysis | None = None

    async def initialize(self) -> None:
        if self.plugin is not None:
            return
        if not DailyConfig.get_config("Enabled").data:
            logger.info("DailyAnalyisis is disabled by configuration")
            return
        plugin = GroupDailyAnalysis(PluginContext())
        self.plugin = plugin
        await plugin.initialize()

    async def shutdown(self) -> None:
        plugin = self.plugin
        self.plugin = None
        if plugin is not None:
            await plugin.terminate()

    async def archive(self, bot: Bot, event: Event) -> None:
        if self.plugin is None:
            await self.initialize()
        if self.plugin is None:
            return
        await self.plugin.bot_manager.archive_gscore_event(bot, event)
        if self.plugin.auto_scheduler:
            await self.plugin.auto_scheduler.record_incremental_message(event)

    async def invoke(
        self,
        method_name: str,
        bot: Bot,
        event: Event,
        *args: object,
    ) -> None:
        if self.plugin is None:
            await self.initialize()
        if self.plugin is None:
            await bot.send("❌ DailyAnalyisis 插件当前已禁用")
            return
        self.plugin.bot_manager.update_from_event(bot, event)
        handler: Callable[..., Awaitable[None]] = getattr(self.plugin, method_name)
        await handler(bot, event, *args)


runtime = PluginRuntime()


__all__ = ["runtime"]
