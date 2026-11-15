"""GsCore 消息发送网关。

命令路径直接使用 ``bot.send``；定时路径使用 ``Subscribe.send``。
两条路径最终都经过 GsCore 的发送管线，不再经过插件自建适配器。
"""

from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

from gsuid_core.bot import Bot
from gsuid_core.models import Message
from gsuid_core.segment import MessageSegment
from gsuid_core.subscribe import gs_subscribe
from gsuid_core.utils.database.models import Subscribe

from ..utils.logger import logger


def text_message(text: str) -> Message:
    return MessageSegment.text(text)


def image_message(image: str | bytes | Path) -> Message:
    return MessageSegment.image(image)


def file_message(path: str | Path, name: str | None = None) -> Message:
    file_path = Path(path)
    return MessageSegment.file(file_path, name or file_path.name)


async def send_messages(bot: Bot, messages: Sequence[Message]) -> bool:
    if not messages:
        return False
    await bot.send(list(messages))
    return True


async def send_subscription(
    subscription: Subscribe,
    messages: Sequence[Message],
) -> bool:
    if not messages:
        return False
    result = await subscription.send(list(messages))
    if result < 0:
        logger.error(
            "订阅推送失败: task=%s group=%s user=%s",
            subscription.task_name,
            subscription.group_id,
            subscription.user_id,
        )
        return False
    return True


async def get_group_subscription(
    group_id: str,
    task_name: str = "DailyAnalyisis定时分析",
) -> Subscribe | None:
    """按群号取回定时分析订阅，供定时/WebUI 路径发送。"""
    rows = await gs_subscribe.get_subscribe(task_name)
    for row in rows or []:
        if not isinstance(row, Subscribe):
            continue
        if str(row.group_id or "") == str(group_id):
            return row
    return None


class MessageSender:
    """保留既有构造签名；实际发送已统一到 bot.send / Subscribe.send。"""

    def __init__(self, bot_manager, config_manager) -> None:
        self.bot_manager = bot_manager
        self.config_manager = config_manager


__all__ = [
    "file_message",
    "get_group_subscription",
    "image_message",
    "MessageSender",
    "send_messages",
    "send_subscription",
    "text_message",
]
