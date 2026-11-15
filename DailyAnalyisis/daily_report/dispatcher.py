import os
import time
import base64
from typing import Any
from pathlib import Path
from datetime import datetime
from contextlib import nullcontext
from urllib.parse import quote
from collections.abc import Callable

from ..utils.logger import logger
from .message_sender import (
    file_message,
    text_message,
    image_message,
    send_messages,
    send_subscription,
)
from ..utils.trace_context import TraceContext


class ReportDispatcher:
    """
    报告分发器
    负责协调报告生成、格式选择、消息发送和失败重试
    """

    def __init__(
        self,
        config_manager,
        report_generator,
        message_sender,
    ):
        self.config_manager = config_manager
        self.report_generator = report_generator
        self.message_sender = message_sender
        self._html_render_func: Callable | None = None

    async def _send(
        self,
        messages: list,
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        if bot is not None:
            return await send_messages(bot, messages)
        if subscription is not None:
            return await send_subscription(subscription, messages)
        logger.error("报告发送失败：没有可用的 Bot 或订阅目标")
        return False

    async def _send_text(
        self,
        text: str,
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        return await self._send([text_message(text)], bot, subscription)

    async def _send_image(
        self,
        image: str | bytes,
        caption: str = "",
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        messages = [image_message(image)]
        if caption:
            messages.append(text_message(caption))
        return await self._send(messages, bot, subscription)

    async def _send_file(
        self,
        path: str,
        caption: str = "",
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        messages = [file_message(path)]
        if caption:
            messages.append(text_message(caption))
        return await self._send(messages, bot, subscription)

    def set_html_render(self, render_func: Callable):
        """设置 HTML 渲染函数 (运行时注入)"""
        self._html_render_func = render_func

    def _is_qq_official(self, platform_id: str | None) -> bool:
        adapter = self.message_sender.bot_manager.get_adapter(platform_id)
        return bool(adapter and adapter.get_platform_name() == "qq_official")

    async def dispatch(
        self,
        bot: object | None,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None = None,
    ) -> bool:
        """分发分析报告，并返回至少一种格式是否实际发送成功。"""
        return await self._dispatch_impl(
            group_id,
            analysis_result,
            platform_id,
            bot=bot,
            subscription=None,
            log_prefix="报告",
        )

    async def dispatch_to_subscription(
        self,
        subscription: object,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None = None,
    ) -> bool:
        """定时路径：通过 gs_subscribe 订阅目标发送。"""
        return await self._dispatch_impl(
            group_id,
            analysis_result,
            platform_id,
            bot=None,
            subscription=subscription,
            log_prefix="订阅报告",
        )

    async def _dispatch_impl(
        self,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None,
        *,
        bot: object | None,
        subscription: object | None,
        log_prefix: str,
    ) -> bool:
        trace_id = TraceContext.get()
        trace_ctx = TraceContext.current()
        output_formats = self.config_manager.get_output_format()
        if isinstance(output_formats, str):
            output_formats = [output_formats]

        logger.info(f"[{trace_id}] 正在分发群 {group_id} 的{log_prefix} (格式: {', '.join(output_formats)})")

        span_exists = bool(
            trace_ctx
            and any(s.get("stage_name") == "DISPATCH_REPORT" and s.get("status") == "running" for s in trace_ctx._spans)
        )
        span_ctx = (
            nullcontext()
            if span_exists
            else (
                trace_ctx.span(
                    "DISPATCH_REPORT",
                    {
                        "platform": platform_id or "auto",
                        "group_id": group_id,
                        "formats": output_formats,
                    },
                )
                if trace_ctx
                else nullcontext()
            )
        )

        dispatch_map = {
            "image": self._dispatch_image,
            "html": self._dispatch_html,
            "text": self._dispatch_text,
        }
        selected_template = self._resolve_template_theme()
        sent_any = False
        format_results: dict[str, bool] = {}

        with span_ctx:
            for fmt in output_formats:
                handler = dispatch_map.get(fmt)
                if not handler:
                    logger.warning(f"[{trace_id}] 不支持的报告格式: {fmt}")
                    continue
                try:
                    if fmt in {"image", "html"}:
                        ok = bool(
                            await handler(
                                group_id,
                                analysis_result,
                                platform_id,
                                template_theme=selected_template,
                                bot=bot,
                                subscription=subscription,
                            )
                        )
                    else:
                        ok = bool(
                            await handler(
                                group_id,
                                analysis_result,
                                platform_id,
                                bot=bot,
                                subscription=subscription,
                            )
                        )
                    format_results[fmt] = ok
                    sent_any = ok or sent_any
                except Exception as e:
                    logger.error(
                        f"[{trace_id}] 群 {group_id} 的 {fmt} 报告发送异常: {e}",
                        exc_info=True,
                    )
                    format_results[fmt] = False

            if trace_ctx:
                for s in reversed(trace_ctx._spans):
                    if s.get("stage_name") == "DISPATCH_REPORT":
                        s.setdefault("payload", {}).update(
                            {
                                "platform": platform_id or "auto",
                                "formats": output_formats,
                                "format": ", ".join(output_formats),
                                "success": sent_any,
                                "group_id": group_id,
                                "format_results": format_results,
                            }
                        )
                        break

        if sent_any:
            logger.info(f"[{trace_id}] 群 {group_id} 的{log_prefix}分发完成，至少一种格式发送成功")
        else:
            logger.error(f"[{trace_id}] 群 {group_id} 的{log_prefix}分发失败，未发送任何报告")
        return sent_any

    def _resolve_template_theme(self) -> str:
        trace = TraceContext.current()
        override_theme = trace.metadata.get("override_template_name") if trace else None
        configured_theme = override_theme or getattr(self.config_manager, "get_report_template", lambda: "ATRI")()
        resolver = getattr(self.report_generator.html_templates, "resolve_template_theme", None)
        if callable(resolver):
            return str(resolver(configured_theme))
        return str(configured_theme or "ATRI")

    async def _dispatch_image(
        self,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None,
        template_theme: str | None = None,
        *,
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        trace_id = TraceContext.get()
        trace_ctx = TraceContext.current()
        # 1. 检查渲染函数
        if not self._html_render_func:
            logger.warning(f"[{trace_id}] 未设置 HTML 渲染函数，回退到文本模式。")
            return await self._dispatch_text(
                group_id,
                analysis_result,
                platform_id,
                bot=bot,
                subscription=subscription,
            )

        # 2. 生成图片
        image_url = None
        html_content = None
        try:
            # 定义头像获取回调，请求小尺寸头像以优化性能
            async def avatar_url_getter(user_id: str):
                if not platform_id:
                    return None
                adapter = self.message_sender.bot_manager.get_adapter(platform_id)
                if adapter and hasattr(adapter, "get_user_avatar_url"):
                    return await adapter.get_user_avatar_url(user_id, size=40)
                return None

            template_theme = template_theme or self._resolve_template_theme()

            if trace_ctx:
                with trace_ctx.span(
                    "RENDER_REPORT",
                    {"format": "image", "template": template_theme},
                ):
                    (
                        image_url,
                        html_content,
                    ) = await self.report_generator.generate_image_report(
                        analysis_result,
                        group_id,
                        self._html_render_func,
                        avatar_url_getter=avatar_url_getter,
                        avatar_cache_namespace=platform_id,
                        allow_alphanumeric_user_ids=self._is_qq_official(platform_id),
                        template_theme=template_theme,
                    )
            else:
                (
                    image_url,
                    html_content,
                ) = await self.report_generator.generate_image_report(
                    analysis_result,
                    group_id,
                    self._html_render_func,
                    avatar_url_getter=avatar_url_getter,
                    avatar_cache_namespace=platform_id,
                    allow_alphanumeric_user_ids=self._is_qq_official(platform_id),
                    template_theme=template_theme,
                )
        except Exception as e:
            logger.error(f"[{trace_id}] Failed to generate image report: {e}")
            # image_url and html_content remain None

        # 4. 发送图片
        sent = False
        dest_filename: str | None = None
        if image_url:
            try:
                reports_dir = self.report_generator.data_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = (
                    f"report_{group_id}_{ts_str}_{trace_id}.jpg" if trace_id else f"report_{group_id}_{ts_str}.jpg"
                )
                dest = reports_dir / filename
                dest_filename = dest.name
                if os.path.exists(image_url):
                    import shutil

                    shutil.copy2(image_url, dest)
                elif image_url.startswith("base64://"):
                    data = base64.b64decode(image_url[9:])
                    dest.write_bytes(data)

                # 关联到 TraceContext 并在数据库中更新元数据
                if trace_ctx:
                    rfiles = trace_ctx.metadata.setdefault("report_files", [])
                    if not any(rf.get("filename") == dest.name for rf in rfiles):
                        rfiles.append(
                            {
                                "filename": dest.name,
                                "path": str(dest.resolve()),
                                "format": "image",
                                "size_bytes": dest.stat().st_size if dest.exists() else 0,
                                "created_at": time.time(),
                            }
                        )
                    from ..utils.trace_context import _global_trace_store

                    if _global_trace_store is not None:
                        try:
                            _global_trace_store.save_trace(trace_ctx.to_dict())
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"[{trace_id}] 保存历史报告副本失败: {e}")

            caption = TraceContext.make_report_caption() if self.config_manager.get_show_report_caption() else ""
            try:
                sent = await self._send_image(
                    image_url,
                    caption,
                    bot=bot,
                    subscription=subscription,
                )
            except Exception as e:
                logger.error(f"[{trace_id}] 图片报告发送异常: {e}", exc_info=True)

        if trace_ctx:
            for s in reversed(trace_ctx._spans):
                if s.get("stage_name") == "DISPATCH_REPORT":
                    s.setdefault("payload", {}).update(
                        {
                            "image_sent": bool(sent),
                            "report_file": dest_filename,
                        }
                    )
                    break

        if sent:
            return True

        # 6. 最终回退：如果图片发送失败（包括生成失败或发送接口报错），直接尝试发送文本报告
        logger.warning(f"[{trace_id}] Image dispatch failed, falling back to text report.")
        return await self._dispatch_text(
            group_id,
            analysis_result,
            platform_id,
            bot=bot,
            subscription=subscription,
        )

    async def _dispatch_html(
        self,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None,
        template_theme: str | None = None,
        *,
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        trace_id = TraceContext.get()
        trace_ctx = TraceContext.current()

        html_path = None
        try:

            async def avatar_url_getter(user_id: str):
                if not platform_id:
                    return None
                adapter = self.message_sender.bot_manager.get_adapter(platform_id)
                if adapter and hasattr(adapter, "get_user_avatar_url"):
                    return await adapter.get_user_avatar_url(user_id, size=40)
                return None

            template_theme = template_theme or self._resolve_template_theme()

            if trace_ctx:
                with trace_ctx.span(
                    "RENDER_REPORT",
                    {"format": "html", "template": template_theme},
                ):
                    (
                        html_path,
                        json_path,
                    ) = await self.report_generator.generate_html_report(
                        analysis_result,
                        group_id,
                        avatar_url_getter=avatar_url_getter,
                        avatar_cache_namespace=platform_id,
                        allow_alphanumeric_user_ids=self._is_qq_official(platform_id),
                        template_theme=template_theme,
                        trace_id=trace_id,
                    )
            else:
                html_path, json_path = await self.report_generator.generate_html_report(
                    analysis_result,
                    group_id,
                    avatar_url_getter=avatar_url_getter,
                    avatar_cache_namespace=platform_id,
                    allow_alphanumeric_user_ids=self._is_qq_official(platform_id),
                    template_theme=template_theme,
                    trace_id=trace_id,
                )
        except Exception as e:
            logger.error(f"[{trace_id}] Failed to generate HTML report: {e}")

        html_filename: str | None = None
        if html_path:
            try:
                html_file = Path(html_path)
                html_filename = html_file.name
                if trace_ctx:
                    rfiles = trace_ctx.metadata.setdefault("report_files", [])
                    if not any(rf.get("filename") == html_file.name for rf in rfiles):
                        rfiles.append(
                            {
                                "filename": html_file.name,
                                "path": str(html_file.resolve()),
                                "format": "html",
                                "size_bytes": html_file.stat().st_size if html_file.exists() else 0,
                                "created_at": time.time(),
                            }
                        )
                    from ..utils.trace_context import _global_trace_store

                    if _global_trace_store is not None:
                        try:
                            _global_trace_store.save_trace(trace_ctx.to_dict())
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"[{trace_id}] 关联 HTML 报告元数据失败: {e}")

            is_only_url = self.config_manager.get_html_only_url()
            base_url = self.config_manager.get_html_base_url()

            if is_only_url:
                if base_url and base_url.strip():
                    # 获取配置的目录
                    html_output_dir = self.config_manager.get_html_output_dir()

                    # 若用户配置为空，使用默认目录
                    if not html_output_dir:
                        html_output_dir = str(self.report_generator.data_dir / "self_hosted_html_reports")

                    # 计算相对路径并转换为URL
                    rel_path = os.path.relpath(html_path, html_output_dir)
                    url_path = rel_path.replace(os.sep, "/")
                    encoded_url_path = quote(url_path.lstrip("/"), safe="/")
                    report_url = f"{base_url.rstrip('/')}/{encoded_url_path}"

                    sent = await self._send_text(
                        f"📊 今日群聊分析报告已生成：\n{report_url}",
                        bot=bot,
                        subscription=subscription,
                    )

                    if sent:
                        return True
                else:
                    logger.warning(
                        f"[{trace_id}] 群 {group_id} 开启了仅发送外链，但未配置 "
                        "html_base_url，已进行降级，回退至发送 HTML 文件。"
                    )

            caption = (
                self.report_generator.build_html_caption(html_path)
                if self.config_manager.get_show_report_caption()
                else ""
            )

            sent = await self._send_file(
                html_path,
                caption,
                bot=bot,
                subscription=subscription,
            )
            if trace_ctx:
                for s in reversed(trace_ctx._spans):
                    if s.get("stage_name") == "DISPATCH_REPORT":
                        s.setdefault("payload", {}).update(
                            {
                                "html_sent": bool(sent),
                                "html_file": html_filename,
                            }
                        )
                        break
            if sent:
                return True

        logger.warning(f"[{trace_id}] HTML dispatch failed, falling back to text report.")
        return await self._dispatch_text(
            group_id,
            analysis_result,
            platform_id,
            bot=bot,
            subscription=subscription,
        )

    async def _dispatch_text(
        self,
        group_id: str,
        analysis_result: dict[str, Any],
        platform_id: str | None,
        *,
        bot: object | None = None,
        subscription: object | None = None,
    ) -> bool:
        """分发文本报告"""
        logger.info(f"[分发器] 正在向群组 {group_id} 分发文本报告")
        is_qq_official = self._is_qq_official(platform_id)
        if is_qq_official:
            (
                text_report,
                _,
            ) = await self.report_generator.generate_qq_official_markdown_report(
                analysis_result, self._html_render_func
            )
        else:
            text_report = self.report_generator.generate_text_report(analysis_result)
        logger.info(f"[分发器] 正在发送文本报告。群: {group_id}")
        try:
            return await self._send_text(
                text_report,
                bot=bot,
                subscription=subscription,
            )
        except Exception as e:
            logger.error(f"[分发器] 发送文本报告最终失败。群: {group_id}, 错误: {e}")
            return False
