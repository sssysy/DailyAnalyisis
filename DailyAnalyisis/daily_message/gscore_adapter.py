from __future__ import annotations

import json
import time
import asyncio
import sqlite3
from pathlib import Path

from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .platform_base import PlatformAdapter
from .unified_group import UnifiedGroup, UnifiedMember
from .unified_message import (
    MessageContent,
    UnifiedMessage,
    MessageContentType,
)
from .platform_capabilities import PlatformCapabilities


class GsCorePlatformAdapter(PlatformAdapter):
    """Persistent platform-neutral adapter fed by GsCore Event objects."""

    def __init__(self, platform_id: str, data_dir: Path) -> None:
        super().__init__(None, {"platform_id": platform_id})
        self.data_dir = data_dir
        self.db_path = data_dir / "messages.db"
        self._write_lock = asyncio.Lock()
        self._initialize_database()

    def _initialize_database(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_card TEXT,
                    timestamp INTEGER NOT NULL,
                    text_content TEXT NOT NULL,
                    contents_json TEXT NOT NULL,
                    PRIMARY KEY (platform_id, group_id, message_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_lookup ON messages(platform_id, group_id, timestamp)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    bot_self_id TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (platform_id, group_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    platform_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    nickname TEXT NOT NULL,
                    card TEXT,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (platform_id, group_id, user_id)
                )
                """
            )

    def _init_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform_name="gscore",
            platform_version="v1",
            supports_message_history=True,
            max_message_history_days=365,
            max_message_count=100000,
            supports_group_list=True,
            supports_group_info=True,
            supports_member_list=True,
            supports_member_info=True,
            supports_text_message=True,
            supports_image_message=True,
            supports_file_message=True,
            supports_forward_message=True,
            supports_user_avatar=True,
            supports_group_avatar=True,
            avatar_sizes=(40, 100, 140, 640),
        )

    async def record_event(self, bot: Bot, event: Event) -> None:
        if event.user_type == "direct" or not event.group_id:
            return
        bot_self_id = str(event.bot_self_id or "")
        if bot_self_id and bot_self_id not in self.bot_self_ids:
            self.bot_self_ids.append(bot_self_id)
        contents: list[MessageContent] = []
        for segment in event.content:
            segment_type = str(segment.type or "").lower()
            data = segment.data
            if segment_type == "text":
                contents.append(MessageContent(MessageContentType.TEXT, text=str(data or "")))
            elif segment_type == "image":
                contents.append(MessageContent(MessageContentType.IMAGE, url=str(data or "")))
            elif segment_type == "at":
                contents.append(MessageContent(MessageContentType.AT, at_user_id=str(data or "")))
            elif segment_type == "record":
                contents.append(MessageContent(MessageContentType.VOICE, url=str(data or "")))
            elif segment_type == "video":
                contents.append(MessageContent(MessageContentType.VIDEO, url=str(data or "")))
            elif segment_type == "file":
                contents.append(MessageContent(MessageContentType.FILE, url=str(data or "")))
            else:
                contents.append(
                    MessageContent(
                        MessageContentType.UNKNOWN,
                        raw_data={"type": segment_type, "data": data},
                    )
                )
        if not contents and event.raw_text:
            contents.append(MessageContent(MessageContentType.TEXT, text=event.raw_text))
        sender_name = str(
            event.sender.get("card") or event.sender.get("nickname") or event.sender.get("name") or event.user_id
        )
        sender_card = str(event.sender.get("card") or "") or None
        message_id = str(event.msg_id or "").strip()
        if not message_id or message_id == str(event.group_id):
            fallback_source = str(event.task_id or event.user_id or "event").strip()
            message_id = f"generated-{fallback_source}-{time.time_ns()}"
        timestamp = int(event.sender.get("timestamp") or time.time())
        group_name = str(event.sender.get("group_name") or event.group_id)
        payload = [self._content_to_dict(content) for content in contents]
        async with self._write_lock:
            await asyncio.to_thread(
                self._record_sync,
                str(event.group_id),
                message_id,
                str(event.user_id),
                sender_name,
                sender_card,
                timestamp,
                event.raw_text or event.text or "",
                payload,
                group_name,
                bot_self_id,
            )

    def _record_sync(
        self,
        group_id: str,
        message_id: str,
        sender_id: str,
        sender_name: str,
        sender_card: str | None,
        timestamp: int,
        text_content: str,
        contents: list[dict],
        group_name: str,
        bot_self_id: str,
    ) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.platform_id,
                    group_id,
                    message_id,
                    sender_id,
                    sender_name,
                    sender_card,
                    timestamp,
                    text_content,
                    json.dumps(self._json_safe(contents), ensure_ascii=False),
                ),
            )
            connection.execute(
                "INSERT OR REPLACE INTO groups VALUES (?, ?, ?, ?, ?)",
                (
                    self.platform_id,
                    group_id,
                    group_name,
                    bot_self_id,
                    int(time.time()),
                ),
            )
            connection.execute(
                "INSERT OR REPLACE INTO members VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.platform_id,
                    group_id,
                    sender_id,
                    sender_name,
                    sender_card,
                    int(time.time()),
                ),
            )

    @staticmethod
    def _json_safe(value: object) -> object:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, dict):
            return {str(key): GsCorePlatformAdapter._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [GsCorePlatformAdapter._json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _content_to_dict(content: MessageContent) -> dict:
        return {
            "type": content.type.value,
            "text": content.text,
            "url": content.url,
            "emoji_id": content.emoji_id,
            "emoji_name": content.emoji_name,
            "at_user_id": content.at_user_id,
            "raw_data": content.raw_data,
        }

    @staticmethod
    def _content_from_dict(data: dict) -> MessageContent:
        try:
            content_type = MessageContentType(str(data.get("type", "unknown")))
        except ValueError:
            content_type = MessageContentType.UNKNOWN
        return MessageContent(
            type=content_type,
            text=str(data.get("text", "")),
            url=str(data.get("url", "")),
            emoji_id=str(data.get("emoji_id", "")),
            emoji_name=str(data.get("emoji_name", "")),
            at_user_id=str(data.get("at_user_id", "")),
            raw_data=data.get("raw_data"),
        )

    async def fetch_messages(
        self,
        group_id: str,
        days: int = 1,
        max_count: int = 1000,
        before_id: str | None = None,
        since_ts: int | None = None,
    ) -> list[UnifiedMessage]:
        cutoff = int(since_ts if since_ts is not None else time.time() - max(days, 1) * 86400)
        rows = await asyncio.to_thread(self._fetch_sync, str(group_id), cutoff, max_count, before_id)
        messages = []
        for row in reversed(rows):
            contents_data = json.loads(row[7])
            messages.append(
                UnifiedMessage(
                    message_id=row[0],
                    sender_id=row[1],
                    sender_name=row[2],
                    sender_card=row[3],
                    group_id=str(group_id),
                    timestamp=row[4],
                    text_content=row[5],
                    platform=self.platform_id,
                    contents=tuple(self._content_from_dict(item) for item in contents_data),
                )
            )
        return messages

    def _fetch_sync(self, group_id: str, cutoff: int, max_count: int, before_id: str | None) -> list[tuple]:
        query = (
            "SELECT message_id, sender_id, sender_name, sender_card, timestamp, "
            "text_content, group_id, contents_json FROM messages "
            "WHERE platform_id=? AND group_id=? AND timestamp>=?"
        )
        params: list[object] = [self.platform_id, group_id, cutoff]
        if before_id:
            query += (
                " AND timestamp < COALESCE((SELECT timestamp FROM messages "
                "WHERE platform_id=? AND group_id=? AND message_id=?), "
                "9223372036854775807)"
            )
            params.extend([self.platform_id, group_id, before_id])
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(max(1, int(max_count)))
        with sqlite3.connect(self.db_path) as connection:
            return list(connection.execute(query, params).fetchall())

    def convert_to_raw_format(self, messages: list[UnifiedMessage]) -> list[dict]:
        return [
            {
                "message_id": message.message_id,
                "time": message.timestamp,
                "sender": {
                    "user_id": message.sender_id,
                    "nickname": message.sender_name,
                    "card": message.sender_card or "",
                },
                "message": [self._raw_content(content) for content in message.contents],
                "group_id": message.group_id,
                "raw_message": message.text_content,
                "user_id": message.sender_id,
            }
            for message in messages
        ]

    @staticmethod
    def _raw_content(content: MessageContent) -> dict:
        if content.type == MessageContentType.TEXT:
            return {"type": "text", "data": {"text": content.text}}
        if content.type == MessageContentType.AT:
            return {"type": "at", "data": {"qq": content.at_user_id}}
        if content.type in {MessageContentType.IMAGE, MessageContentType.EMOJI}:
            return {"type": "image", "data": {"url": content.url}}
        return {"type": content.type.value, "data": content.raw_data or {"url": content.url}}

    async def get_group_info(self, group_id: str) -> UnifiedGroup | None:
        row = await asyncio.to_thread(
            self._one_sync,
            "SELECT group_name FROM groups WHERE platform_id=? AND group_id=?",
            (self.platform_id, str(group_id)),
        )
        if row is None:
            return None
        return UnifiedGroup(
            str(group_id),
            str(row[0]),
            member_count=len(await self.get_member_list(group_id)),
            platform=self.platform_id,
        )

    async def get_group_list(self) -> list[str]:
        rows = await asyncio.to_thread(
            self._all_sync,
            "SELECT group_id FROM groups WHERE platform_id=? ORDER BY updated_at DESC",
            (self.platform_id,),
        )
        return [str(row[0]) for row in rows]

    async def get_member_list(self, group_id: str) -> list[UnifiedMember]:
        rows = await asyncio.to_thread(
            self._all_sync,
            "SELECT user_id, nickname, card FROM members WHERE platform_id=? AND group_id=?",
            (self.platform_id, str(group_id)),
        )
        return [UnifiedMember(str(row[0]), str(row[1]), str(row[2]) if row[2] else None) for row in rows]

    async def get_member_info(self, group_id: str, user_id: str) -> UnifiedMember | None:
        row = await asyncio.to_thread(
            self._one_sync,
            "SELECT nickname, card FROM members WHERE platform_id=? AND group_id=? AND user_id=?",
            (self.platform_id, str(group_id), str(user_id)),
        )
        return UnifiedMember(str(user_id), str(row[0]), str(row[1]) if row and row[1] else None) if row else None

    def _all_sync(self, query: str, params: tuple) -> list[tuple]:
        with sqlite3.connect(self.db_path) as connection:
            return list(connection.execute(query, params).fetchall())

    def _one_sync(self, query: str, params: tuple) -> tuple | None:
        with sqlite3.connect(self.db_path) as connection:
            return connection.execute(query, params).fetchone()

    async def get_user_avatar_url(self, user_id: str, size: int = 100) -> str | None:
        return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s={size}" if str(user_id).isdigit() else None

    async def get_user_avatar_data(self, user_id: str, size: int = 100) -> str | None:
        return None

    async def get_group_avatar_url(self, group_id: str, size: int = 100) -> str | None:
        return f"https://p.qlogo.cn/gh/{group_id}/{group_id}/{size}" if str(group_id).isdigit() else None

    async def batch_get_avatar_urls(self, user_ids: list[str], size: int = 100) -> dict[str, str | None]:
        return {user_id: await self.get_user_avatar_url(user_id, size) for user_id in user_ids}


__all__ = ["GsCorePlatformAdapter"]
