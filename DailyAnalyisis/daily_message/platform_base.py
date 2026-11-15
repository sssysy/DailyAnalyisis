"""
平台适配器基类
"""

from abc import ABC, abstractmethod
from typing import Any
from collections.abc import Mapping

from .unified_message import UnifiedMessage
from .avatar_repository import IAvatarRepository
from .message_repository import IMessageRepository, IGroupInfoRepository
from .platform_capabilities import PlatformCapabilities


class PlatformAdapter(IMessageRepository, IGroupInfoRepository, IAvatarRepository, ABC):
    """
    基础设施：平台适配器基类

    继承自多个领域接口（仓储、群组信息、头像），
    充当领域层与具体聊天平台（如 OneBot, Discord）之间的中转站。

    Attributes:
        bot (Any): 平台对应的机器人 SDK 实例，显式标注为 Any 以支持动态属性调用
        config (dict): 针对该平台的特定配置
    """

    bot: Any

    def __init__(
        self,
        bot_instance: Any,
        config: Mapping[str, Any] | None = None,
    ):
        """
        初始化平台适配器。

        Args:
            bot_instance (Any): 后端机器人实例
            config (dict, optional): 平台特定配置项
        """
        self.bot = bot_instance
        self.config: dict[str, object] = dict(config) if config is not None else {}
        self._platform_id: str = str(self.config.get("platform_id", "")).strip()
        self.bot_self_ids: list[str] = []
        self._capabilities: PlatformCapabilities | None = None

    @property
    def platform_id(self) -> str:
        """获取当前适配器的平台实例 ID（如 nuits）"""
        return self._platform_id

    def set_context(self, context: Any):
        """
        设置上下文对象（用于部分需要 ctx 的平台如 Telegram）。

        Args:
            context (Any): 上下文对象
        """
        pass

    @property
    def capabilities(self) -> PlatformCapabilities:
        """
        获取当前平台的能力描述对象。

        采用延迟加载机制，在首次访问时调用 `_init_capabilities`。

        Returns:
            PlatformCapabilities: 平台能力对象
        """
        if self._capabilities is None:
            self._capabilities = self._init_capabilities()
        return self._capabilities

    @abstractmethod
    def _init_capabilities(self) -> PlatformCapabilities:
        """
        初始化并返回当前平台的能力定义。

        子类必须实现此方法以声明其对历史记录、图片发送等功能的支持情况。

        Returns:
            PlatformCapabilities: 初始化后的能力对象
        """
        raise NotImplementedError

    def get_capabilities(self) -> PlatformCapabilities:
        """获取平台能力的便捷入口。"""
        return self.capabilities

    def get_platform_name(self) -> str:
        """获取当前适配器的平台标识名称。"""
        return self.capabilities.platform_name

    @abstractmethod
    def convert_to_raw_format(self, messages: list[UnifiedMessage]) -> list[dict]:
        """
        将平台无关的统一消息列表转换回当前平台的原生字典格式。

        此方法主要用于向后兼容，使新的统一接口能与依赖原生数据结构的旧版分析逻辑协同工作。

        Args:
            messages (list[UnifiedMessage]): 待转换的统一消息列表

        Returns:
            list[dict]: 转换后的平台原生消息字典列表
        """
        raise NotImplementedError

    async def is_group_muted(self, group_id: str) -> bool:
        """
        检查群聊是否被禁言（包括全体禁言或对 Bot 自身禁言）。
        默认返回 False。各平台适配器可以根据需要重写此方法。
        """
        return False
