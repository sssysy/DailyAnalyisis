from __future__ import annotations

from typing import Dict

from gsuid_core.data_store import get_res_path
from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsDivider,
    GsIntConfig,
    GsStrConfig,
    GsBoolConfig,
    GsFloatConfig,
    GsListStrConfig,
    GsRepeatGroupConfig,
)

from ..utils.constants import PLUGIN_NAME

DATA_DIR = get_res_path(PLUGIN_NAME)
CONFIG_PATH = DATA_DIR / "config_v2.json"
LEGACY_CONFIG_PATH = DATA_DIR / "config.json"
LEGACY_GSCORE_CONFIG_PATH = DATA_DIR / "gscore_config.json"


def _repeat_field(title: str, desc: str, path: tuple[str, ...]) -> GsRepeatGroupConfig:
    if path[-1] == "comic_characters":
        template: Dict[str, GSC] = {
            "name": GsStrConfig("角色名", "漫画角色名称", ""),
            "prompt": GsStrConfig("角色提示词", "角色外观与性格提示词", ""),
        }
    else:
        template = {
            "protocol": GsStrConfig("协议", "图片接口协议", "openai"),
            "api_url": GsStrConfig("接口地址", "图片接口 Base URL", ""),
            "api_key": GsStrConfig("API Key", "图片接口密钥", "", secret=True),
            "model": GsStrConfig("模型", "图片模型名称", ""),
            "priority": GsIntConfig("优先级", "数值越小越优先", 10),
        }
    return GsRepeatGroupConfig(title=title, desc=desc, data=[], template=template)


CONFIG_DEFAULT: Dict[str, GSC] = {
    "Enabled": GsBoolConfig("启用 DailyAnalyisis", "关闭后停止命令、消息归档、定时分析和增量分析。", True),
    "ExternalWebUIEnabled": GsBoolConfig("启用外部 WebUI", "开启后才会挂载 DailyAnalyisis 独立 WebUI。", False),
    "__divider__basic": GsDivider("基础设置", "", "basic"),
    "BasicGroupListMode": GsStrConfig(
        "群聊权限模式",
        '群聊权限模式\n先决定“哪些群可以用这个插件”。这是第一道门槛：不通过这里，后面的定时/增量都不会触发。whitelist=只允许列表里的群；blacklist=屏蔽列表里的群；none=所有群都可以。示例：whitelist + ["onebot:GroupMessage:123456"] 表示只有这个群能用。',
        "none",
    ),
    "BasicGroupList": GsListStrConfig(
        "群组白/黑名单列表",
        "群组白/黑名单列表\n要填的群列表。可以填完整会话ID（如 onebot:GroupMessage:123456）或只填群号。QQ 官方机器人使用 group_openid，不是群号，务必优先通过 /sid 获取并填写完整 UMO。",
        [],
    ),
    "BasicAnalysisDays": GsIntConfig(
        "默认分析天数",
        "默认分析天数\n默认分析最近几天的消息，增量分析也基于此数据保存分析情况。无历史拉取能力的平台只能分析插件启用后由 GsCore 实时归档的消息。",
        1,
    ),
    "BasicMaxMessages": GsIntConfig(
        "单次分析的获取最大消息条数基准",
        "单次分析的获取最大消息条数基准\n单次分析的获取最大消息条数基准值，如果当天群聊消息过多，已经获取到足够的消息(达到 max_messages)，停止获取，获取到的消息数量是最新一次获取到的超过 max_messages 的消息数量，建议500-2000",
        1000,
    ),
    "BasicMinMessagesThreshold": GsIntConfig("最小消息数阈值", "最小消息数阈值\n进行分析所需的最小消息数量", 200),
    "BasicBotSelfIds": GsListStrConfig(
        "群分析时屏蔽的用户ID列表",
        "群分析时屏蔽的用户ID列表\n填写后可启用自动分析功能。可以填写用于自动分析的机器人 ID（在不同平台上可能是数字或字符串）、多消息平台 ID、不希望出现于群分析中的其他人的 ID 等。",
        [],
    ),
    "BasicFilterBotMessages": GsBoolConfig(
        "分析时是否过滤机器人自己的消息",
        "分析时是否过滤机器人自己的消息\n默认开启，bot 自身的发言不会出现在分析报告中。关闭后 bot 的发言也会被纳入话题分析、金句提取等。",
        True,
    ),
    "BasicEnableUserCard": GsBoolConfig(
        "使用用户群名片", "使用用户群名片\n在分析中优先使用用户的群名片作为昵称显示", True
    ),
    "BasicOutputFormat": GsListStrConfig(
        "输出格式（可多选）",
        "输出格式（可多选）\n选择分析报告的输出方式（可多选）。image=图片、text=纯文本摘要、html=可交互式网页文件。多选仅在定时分析发送时时报告按顺序依次发送，手动触发时只发送第一个选中的格式，例如 image+html 会发送图片并通过外链提供 HTML 报告。QQ 官方图片/HTML 报告优先显示事件昵称，昵称缺失时使用群内稳定匿名名；文本报告由独立 Markdown 模块使用成员艾特展示身份。其他平台保持原有昵称文本格式。",
        ["image"],
        options=["image", "text", "html"],
    ),
    "BasicReportTemplate": GsStrConfig(
        "报告模板",
        "报告模板\n分析报告使用的 HTML 模板名称。默认使用 ATRI；选择 random 后每份报告随机选择一个可用主题。可以使用 `/设置模板` 查看使用指南，使用 `/查看模板` 命令查看模板样式效果。",
        "ATRI",
    ),
    "BasicProfileDisplayMode": GsStrConfig(
        "人格标签展示模式",
        "人格标签展示模式\n只影响群友画像卡片的角色主题展示，不影响实际 MBTI 分析结果。mbti=原始 MBTI，sbti=映射为 SBTI 人格，acgti=映射为 ACGTI 角色。",
        "mbti",
    ),
    "BasicProfileImageOpacity": GsFloatConfig(
        "人格背景图透明度", "人格背景图透明度\n建议 0.08~0.18，仅作为卡片底层装饰，避免遮挡正文。", 0.12
    ),
    "BasicProfileImageSizeMode": GsStrConfig(
        "人格背景图尺寸模式", "人格背景图尺寸模式\n建议默认 contain，减少角色图被裁切过多的问题。", "contain"
    ),
    "BasicProfileMappingConfig": GsStrConfig(
        "人格映射配置(JSON)",
        "人格映射配置(JSON)\n按 MBTI 覆盖当前展示模式的人格名称与图片地址。留空时自动使用插件内置默认映射和 manifest。插件不负责校验图片链接可访问性。",
        '{\n    "mbti": {\n        "INTJ": {\n            "code": "INTJ",\n            "name_zh": "建筑师"\n        },\n        "INTP": {\n            "code": "INTP",\n            "name_zh": "逻辑学家"\n        },\n        "ENTJ": {\n            "code": "ENTJ",\n            "name_zh": "指挥官"\n        },\n        "ENTP": {\n            "code": "ENTP",\n            "name_zh": "辩论家"\n        },\n        "INFJ": {\n            "code": "INFJ",\n            "name_zh": "提倡者"\n        },\n        "INFP": {\n            "code": "INFP",\n            "name_zh": "调停者"\n        },\n        "ENFJ": {\n            "code": "ENFJ",\n            "name_zh": "主人公"\n        },\n        "ENFP": {\n            "code": "ENFP",\n            "name_zh": "竞选者"\n        },\n        "ISTJ": {\n            "code": "ISTJ",\n            "name_zh": "物流师"\n        },\n        "ISFJ": {\n            "code": "ISFJ",\n            "name_zh": "守卫者"\n        },\n        "ESTJ": {\n            "code": "ESTJ",\n            "name_zh": "总经理"\n        },\n        "ESTP": {\n            "code": "ESTP",\n            "name_zh": "企业家"\n        },\n        "ISTP": {\n            "code": "ISTP",\n            "name_zh": "鉴赏家"\n        },\n        "ISFP": {\n            "code": "ISFP",\n            "name_zh": "探险家"\n        },\n        "ESFJ": {\n            "code": "ESFJ",\n            "name_zh": "执政官"\n        },\n        "ESFP": {\n            "code": "ESFP",\n            "name_zh": "表演者"\n        }\n    },\n    "sbti": {\n        "INTJ": {\n            "code": "CTRL",\n            "name_zh": "拿捏者",\n            "asset_code": "CTRL",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/CTRL.png"\n        },\n        "INTP": {\n            "code": "THIN-K",\n            "name_zh": "思考者",\n            "asset_code": "THIN-K",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/THIN-K.png"\n        },\n        "ENTJ": {\n            "code": "BOSS",\n            "name_zh": "领导者",\n            "asset_code": "BOSS",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/BOSS.png"\n        },\n        "ENTP": {\n            "code": "JOKE-R",\n            "name_zh": "小丑",\n            "asset_code": "JOKE-R",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/JOKE-R.jpg"\n        },\n        "INFJ": {\n            "code": "LOVE-R",\n            "name_zh": "多情者",\n            "asset_code": "LOVE-R",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/LOVE-R.png"\n        },\n        "INFP": {\n            "code": "SOLO",\n            "name_zh": "孤儿",\n            "asset_code": "SOLO",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/SOLO.png"\n        },\n        "ENFJ": {\n            "code": "THAN-K",\n            "name_zh": "感恩者",\n            "asset_code": "THAN-K",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/THAN-K.png"\n        },\n        "ENFP": {\n            "code": "GOGO",\n            "name_zh": "行者",\n            "asset_code": "GOGO",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/GOGO.png"\n        },\n        "ISTJ": {\n            "code": "OH-NO",\n            "name_zh": "哦不人",\n            "asset_code": "OH-NO",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/OH-NO.png"\n        },\n        "ISTP": {\n            "code": "POOR",\n            "name_zh": "贫困者",\n            "asset_code": "POOR",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/POOR.png"\n        },\n        "ESTJ": {\n            "code": "SHIT",\n            "name_zh": "愤世者",\n            "asset_code": "SHIT",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/SHIT.png"\n        },\n        "ESTP": {\n            "code": "WOC!",\n            "name_zh": "握草人",\n            "asset_code": "WOC",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/WOC.png"\n        },\n        "ISFJ": {\n            "code": "MUM",\n            "name_zh": "妈妈",\n            "asset_code": "MUM",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/MUM.png"\n        },\n        "ISFP": {\n            "code": "MALO",\n            "name_zh": "吗喽",\n            "asset_code": "MALO",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/MALO.png"\n        },\n        "ESFJ": {\n            "code": "ATM-er",\n            "name_zh": "送钱者",\n            "asset_code": "ATM-er",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/ATM-er.png"\n        },\n        "ESFP": {\n            "code": "SEXY",\n            "name_zh": "尤物",\n            "asset_code": "SEXY",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/sbti/SEXY.png"\n        }\n    },\n    "acgti": {\n        "INTJ": {\n            "code": "MRTS-X",\n            "name_zh": "Mortis",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/MRTS-X.png"\n        },\n        "INTP": {\n            "code": "KNAN",\n            "name_zh": "江户川柯南"\n        },\n        "ENTJ": {\n            "code": "SAKI",\n            "name_zh": "丰川祥子",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/SAKI.png"\n        },\n        "ENTP": {\n            "code": "CHKA",\n            "name_zh": "藤原千花"\n        },\n        "INFJ": {\n            "code": "DLRS",\n            "name_zh": "三角初华",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/DLRS.png"\n        },\n        "INFP": {\n            "code": "BCHI",\n            "name_zh": "后藤一里"\n        },\n        "ENFJ": {\n            "code": "YCYO",\n            "name_zh": "月见八千代",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/YCYO.png"\n        },\n        "ENFP": {\n            "code": "HTMK",\n            "name_zh": "初音未来"\n        },\n        "ISTJ": {\n            "code": "MRTS",\n            "name_zh": "若叶睦",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/MRTS.png"\n        },\n        "ISTP": {\n            "code": "AYRE",\n            "name_zh": "绫波丽"\n        },\n        "ESTJ": {\n            "code": "MIKT",\n            "name_zh": "御坂美琴",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/MIKT.png"\n        },\n        "ESTP": {\n            "code": "ASKA",\n            "name_zh": "明日香"\n        },\n        "ISFJ": {\n            "code": "SOYO",\n            "name_zh": "长崎爽世",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/SOYO.png"\n        },\n        "ISFP": {\n            "code": "LTYI",\n            "name_zh": "洛天依",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/LTYI.png"\n        },\n        "ESFJ": {\n            "code": "ANON",\n            "name_zh": "千早爱音",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/ANON.png"\n        },\n        "ESFP": {\n            "code": "FRNA",\n            "name_zh": "芙宁娜",\n            "image": "https://fastly.jsdelivr.net/gh/SXP-Simon/profile_assets@main/acgti/characters/FRNA.png"\n        }\n    }\n}',
    ),
    "BasicDebugMode": GsBoolConfig(
        "调试模式（建议关闭）",
        "调试模式（建议关闭）\n启用后，会在插件数据目录下的 debug_data 目录中保存每次分析的平台 API 原始历史消息和 Prompt 原文，用于调试和优化提示词。",
        False,
    ),
    "BasicEnableBase64Image": GsBoolConfig(
        "图片传输使用 Base64 编码",
        "图片传输使用 Base64 编码\n启用后图片会被转为 Base64 编码传输。关闭后将直接传递文件路径或 URL 给 OneBot 实现端，适用于 Napcat/LLbot/SnowLuma 等支持本地路径的实现，可降低内存占用。",
        True,
    ),
    "BasicNapcatStreamThresholdMb": GsFloatConfig(
        "NapCat/Snowluma 流式上传阈值（MB）",
        "NapCat/Snowluma 流式上传阈值（MB）\n先按现有图片发送策略发送本地图片；发送失败且文件大小达到阈值时，复用当前 NapCat/Snowluma 连接调用 upload_file_stream 并重试一次。填 0 禁用。Docker / docker compose 环境建议保持默认或按图片大小调大。",
        2.0,
    ),
    "BasicEnableAnalysisReply": GsBoolConfig(
        "发送文本/表情回复",
        "发送文本/表情回复\n开启后，/群分析 将通过发送文本消息提示进度；关闭（默认）则使用表情回应。",
        False,
    ),
    "BasicShowReportCaption": GsBoolConfig(
        '发送报告时附带 "📊 每日群聊分析报告已生成" 前缀',
        '发送报告时附带 "📊 每日群聊分析报告已生成" 前缀\n关闭后，发送图片/HTML 报告时将只发送文件本身，不附带 "📊 每日群聊分析报告已生成" 等文字前缀。',
        True,
    ),
    "__divider__webui": GsDivider("WebUI 安全", "", "webui"),
    "WebUIPassword": GsStrConfig(
        "WebUI 访问密码",
        "WebUI 访问密码\n开启外部 WebUI 后首次进入页面时设置；以后可在这里输入新密码并保存。至少 8 个字符，留空表示保留当前密码。",
        "",
    ),
    "__divider__qq_official": GsDivider("QQ 官方", "", "qq_official"),
    "QQOfficialEnableT2iActivityHistogram": GsBoolConfig(
        "启用 T2I 群聊概览图",
        "启用 T2I 群聊概览图\n在 QQ 官方 Markdown 报告中嵌入透明背景的日期、基础统计与 24 小时直方图。渲染失败时自动回退为完整文字报告。",
        True,
    ),
    "__divider__t2i_rendering": GsDivider("图片渲染", "", "t2i_rendering"),
    "T2IR1Type": GsStrConfig(
        "第一轮：图片格式", "第一轮：图片格式\n建议：PNG 格式无损但体积较大；JPEG 格式体积较小。", "png"
    ),
    "T2IR1Quality": GsIntConfig(
        "第一轮：图片质量 (若为 JPEG)",
        "第一轮：图片质量 (若为 JPEG)\n仅对 JPEG 格式生效。建议 80-100。",
        100,
        max_value=100,
    ),
    "T2IR1DeviceScale": GsStrConfig(
        "第一轮：分辨率等级",
        "第一轮：分辨率等级\n影响图片清晰度。normal=1.0x, high=1.3x, ultra=1.8x。高质量日报建议 ultra。",
        "ultra",
    ),
    "T2IR1Timeout": GsIntConfig(
        "第一轮：渲染超时 (ms)",
        "第一轮：渲染超时 (ms)\n单次渲染的最长等待时间。复杂页面建议调大。",
        50000,
        max_value=180000,
    ),
    "T2IViewportWidth": GsIntConfig(
        "报告渲染视口兜底宽度 (px)",
        "报告渲染视口兜底宽度 (px)\n仅在模板未提供可识别的数字 width 时传给 GsCore HTML 渲染器。内置主题建议保持 1440；自定义模板可用 meta viewport 的数字 width 指定自身宽度。",
        1080,
        max_value=1440,
    ),
    "T2IViewportHeight": GsIntConfig(
        "报告渲染视口兜底高度 (px)",
        "报告渲染视口兜底高度 (px)\n仅在模板未提供可识别的数字 height 时传给 GsCore HTML 渲染器。图片报告始终使用 full_page，不会按此高度截断整张报告。",
        900,
        max_value=1440,
    ),
    "T2IR2Type": GsStrConfig(
        "第二轮 (回退)：图片格式", "第二轮 (回退)：图片格式\n回退策略建议使用 jpeg 以减少渲染压力。", "jpeg"
    ),
    "T2IR2Quality": GsIntConfig(
        "第二轮 (回退)：图片质量 (若为 JPEG)",
        "第二轮 (回退)：图片质量 (若为 JPEG)\n仅对 JPEG 格式生效。可以设置较低值以确保生成成功。",
        80,
        max_value=100,
    ),
    "T2IR2DeviceScale": GsStrConfig(
        "第二轮 (回退)：分辨率等级",
        "第二轮 (回退)：分辨率等级\n回退建议使用 high/normal 以降低复杂页面的内存消耗和超时概率。",
        "high",
    ),
    "T2IR2Timeout": GsIntConfig(
        "第二轮 (回退)：渲染超时 (ms)",
        "第二轮 (回退)：渲染超时 (ms)\n回退尝试通常针对复杂页面，建议设置更长的超时时间（如 100000ms+）。",
        100000,
        max_value=180000,
    ),
    "T2IFontSource": GsStrConfig(
        "t2i 渲染环境切换",
        "t2i 渲染环境切换\n字体和静态资源的访问环境，内地（Mainland）、海外（Overseas），切换环境会自动应用下方对应的镜像站地址、语言标识(简体中文/繁体中文)及字体优先级。（实测 Overseas 也可以正常渲染简体中文，没有特殊的情况都建议使用 Overseas，Mainland 配置下建议检查镜像站可用性，或者配置可靠的站点）",
        "Overseas",
    ),
    "T2IMainlandGoogleFonts": GsStrConfig(
        "[内地] Google Fonts 镜像",
        "[内地] Google Fonts 镜像\n内地环境下推荐使用 loli.net 或其他可访问镜像。",
        "https://fonts.loli.net",
    ),
    "T2IMainlandGstatic": GsStrConfig(
        "[内地] Gstatic 镜像",
        "[内地] Gstatic 镜像\n内地环境下推荐使用 loli.net 或其他可访问镜像。",
        "https://gstatic.loli.net",
    ),
    "T2IOverseasGoogleFonts": GsStrConfig(
        "[海外] Google Fonts 官方",
        "[海外] Google Fonts 官方\n海外环境通常直接使用官方地址即可。",
        "https://fonts.googleapis.com",
    ),
    "T2IOverseasGstatic": GsStrConfig(
        "[海外] Gstatic 官方", "[海外] Gstatic 官方\n海外环境通常直接使用官方地址即可。", "https://fonts.gstatic.com"
    ),
    "__divider__auto_analysis": GsDivider("定时分析", "", "auto_analysis"),
    "AutoAnalysisTime": GsListStrConfig(
        "自动分析时间列表",
        '自动分析时间列表\n每天几点自动出报告，格式是 HH:MM。可填多个时间，例如 ["09:00", "21:30"]。',
        ["23:00"],
    ),
    "AutoAnalysisScheduledGroupListMode": GsStrConfig(
        "定时分析名单模式",
        "定时分析名单模式\n定时任务要作用到哪些群。inherit=直接继承基础群权限，不需要重复填写；whitelist=只跑下面列表里的群；blacklist=除了下面列表，其他都跑。定时名单始终不会绕过基础群权限。",
        "whitelist",
    ),
    "AutoAnalysisScheduledGroupList": GsListStrConfig(
        "定时分析群列表",
        '定时分析群列表\n仅在 whitelist 或 blacklist 模式下使用。示例1：mode=whitelist + ["onebot:GroupMessage:123456"] => 只跑这个群。示例2：mode=blacklist + ["onebot:GroupMessage:123456"] => 这个群不跑，其他群跑。inherit 模式会忽略此列表并复用基础名单。whitelist + 空列表 = 不会开启定时任务。',
        [],
    ),
    "__divider__llm": GsDivider("LLM 设置", "", "llm"),
    "LLMApiKey": GsStrConfig(
        "插件专用 API Key",
        "插件专用 API Key\n仅保存在本插件配置中，并通过 Authorization 请求头发送；不会读取 GsCore 全局 AI Key。",
        "",
    ),
    "LLMApiUrl": GsStrConfig(
        "插件专用 API 端点 URL",
        "插件专用 API 端点 URL\n填写 OpenAI 兼容接口的根地址，例如 https://chisa.akiyo.fun/v1；插件会自动请求 /chat/completions。",
        "https://chisa.akiyo.fun/v1",
    ),
    "LLMModel": GsStrConfig(
        "插件专用模型名称",
        "插件专用模型名称\n所有话题、称号、金句、质量分析和漫画分镜请求都使用此模型。",
        "gpt-4o-mini",
    ),
    "LLMTemperature": GsFloatConfig(
        "默认 temperature", "默认 temperature\n插件请求的默认采样温度；结构化输出重试会按插件内置策略临时降低。", 0.7
    ),
    "LLMMaxTokens": GsIntConfig(
        "单次请求最大输出 Token", "单次请求最大输出 Token\n发送给兼容接口的 max_tokens 上限。", 8192, max_value=32768
    ),
    "LLMTimeout": GsIntConfig(
        "API 请求超时（秒）", "API 请求超时（秒）\n插件独立 HTTP 请求的总超时时间。", 120, max_value=600
    ),
    "LLMRetries": GsIntConfig(
        "LLM 请求重试次数", "LLM 请求重试次数\n当请求超时或失败时自动重试的次数，建议设置为1~3之间。", 2
    ),
    "LLMBackoff": GsIntConfig(
        "LLM 请求重试退避基值（秒）",
        "LLM 请求重试退避基值（秒）\n重试之间的基准等待时间（秒）。实际等待时间会随尝试次数指数增长，并加入少量随机抖动；当专用 Provider 失败后，会继续按队列尝试默认 Provider。",
        2,
    ),
    "LLMEnableStreamingLlmCall": GsBoolConfig(
        "启用流式 LLM 调用",
        "启用流式 LLM 调用\n默认关闭，使用非流式调用方式。开启后，插件将使用本插件 API 端点的 stream=true 接口并聚合结果。",
        False,
    ),
    "__divider__analysis_features": GsDivider("分析功能", "", "analysis_features"),
    "AnalysisTopicAnalysisEnabled": GsBoolConfig("启用话题分析", "启用话题分析\n是否使用LLM进行智能话题分析", True),
    "AnalysisUserTitleAnalysisEnabled": GsBoolConfig(
        "启用用户称号分析", "启用用户称号分析\n是否使用LLM进行用户称号分析", True
    ),
    "AnalysisGoldenQuoteAnalysisEnabled": GsBoolConfig("启用金句分析", "启用金句分析\n是否使用LLM进行金句分析", True),
    "AnalysisChatQualityAnalysisEnabled": GsBoolConfig(
        "启用聊天质量锐评", "启用聊天质量锐评\n是否使用LLM进行聊天质量锐评（维度化分析）", True
    ),
    "AnalysisMaxTopics": GsIntConfig(
        "最大话题数量",
        "最大话题数量\n分析报告中显示的最大话题数量，依赖于 LLM 输出的格式化信息质量，模型越好结果越好，可能出现数量不匹配。",
        5,
    ),
    "AnalysisMaxUserTitles": GsIntConfig(
        "最大用户称号数量",
        "最大用户称号数量\n分析报告中显示的最大用户称号数量，依赖于 LLM 输出的格式化信息质量，模型越好结果越好，可能出现数量不匹配。",
        8,
    ),
    "AnalysisMaxGoldenQuotes": GsIntConfig(
        "最大金句数量",
        "最大金句数量\n分析报告中显示的最大金句数量，依赖于 LLM 输出的格式化信息质量，模型越好结果越好，可能出现数量不匹配。",
        5,
    ),
    "AnalysisKeepOriginalPersona": GsBoolConfig(
        "继承会话人设风格",
        "继承会话人设风格\n【优先级2】开启后将自动尝试识别当前群聊会话（或对话）的人格设定。若该群已设置人设，则分析报告会尽量模拟该人设的口吻进行回复。注意：此开关在“强制使用插件指定人格”关闭时才会生效。",
        False,
    ),
    "AnalysisUsePluginSpecificPersona": GsBoolConfig(
        "强制使用插件指定人格",
        "强制使用插件指定人格\n【优先级1：核心开关】若开启，将完全忽略当前群聊的人格设定，统一强制使用下方选择的“插件指定人格 ID”进行分析。适用于希望全群分析保持某种统一固定风格（如特定的“记录员”人设）的情况。",
        False,
    ),
    "AnalysisPluginSpecificPersonaId": GsStrConfig(
        "插件指定人格 ID",
        "插件指定人格 ID\n当“强制使用插件指定人格”开启时，在此处选择系统中已定义的人设。该人格会同时作用于画图提示词生成模型。若此处未选择，则仍会尝试识别全局默认人格。",
        "",
    ),
    "__divider__daily_comic": GsDivider("每日漫画", "", "daily_comic"),
    "ComicEnableDailyComic": GsBoolConfig(
        "启用漫画功能",
        "启用漫画功能\n漫画总开关。关闭时，/群漫画 和所有自动联动漫画都会停止。开启后可继续通过下方“分析后自动生成漫画”单独控制自动联动。",
        False,
    ),
    "ComicEnableAutoDailyComic": GsBoolConfig(
        "分析后自动生成漫画",
        "分析后自动生成漫画\n控制手动群分析、定时分析和增量最终报告完成后是否自动生成漫画。关闭后仍可手动使用 /群漫画，且不会重复执行话题分析链路。",
        True,
    ),
    "ComicGroupListMode": GsStrConfig(
        "漫画群名单模式",
        "漫画群名单模式\n只控制漫画生成，不影响报告名单。inherit=继承基础群权限，适合漫画和分析使用同一批群且无需重复填写；blacklist=除列表外都允许生成漫画，适合只开放漫画不开放分析；whitelist=只允许列表里的群生成漫画。白名单为空时不会为任何群生成漫画。",
        "inherit",
    ),
    "ComicGroupList": GsListStrConfig(
        "漫画群白/黑名单列表",
        "漫画群白/黑名单列表\n用于漫画生成的群列表。可以填完整会话ID（如 onebot:GroupMessage:123456）或只填群号。自动漫画和 /群漫画 手动命令都会检查这里。",
        [],
    ),
    "ComicRandomDailyComicCharacter": GsBoolConfig(
        "每天随机切换漫画角色",
        "每天随机切换漫画角色\n开启后每天首次生成漫画时，会从下方已启用的角色方案随机选择一个，并按运行环境时区在当天持续使用；重启不会改变当天选择。关闭时固定使用第一个已启用方案。",
        False,
    ),
    "ComicCharacters": _repeat_field(
        "漫画角色方案",
        "漫画角色方案\n每个方案可绑定漫画专用人格、参考图和场景分析提示词。方案条目可展开编辑；请使用不同的方案名称，方便识别当天随机选中的角色。未配置方案时仍可正常文生图。",
        ("daily_comic", "comic_characters"),
    ),
    "ComicDrawingReferenceImage": GsStrConfig(
        "旧版漫画参考图（兼容迁移）", "旧版漫画参考图（兼容迁移）\n旧版配置仅用于自动迁移，不再在面板中显示。", "[]"
    ),
    "ComicDrawingBackend": GsStrConfig(
        "绘图后端",
        "绘图后端\nGsCore 版本统一使用本插件内置绘图客户端，并按绘图供应商配置表调用图片生成 API。",
        "builtin",
    ),
    "ComicDrawingExternalFallback": GsBoolConfig(
        "外部后端失败时回退内置后端",
        "外部后端失败时回退内置后端\n旧版配置仅用于兼容迁移，GsCore 版本始终使用内置绘图客户端。",
        True,
    ),
    "ComicDrawingProviderOverrides": _repeat_field(
        "绘图供应商配置表",
        "绘图供应商配置表\n可添加多个绘图供应商。按 priority 从高到低尝试，同优先级按表中顺序尝试；所有候选失败后才判定漫画生成失败。至少添加一个包含 API Key 的启用条目。",
        ("daily_comic", "drawing_provider_overrides"),
    ),
    "ComicDrawingProxy": GsStrConfig(
        "全局生图代理地址",
        "全局生图代理地址\n填写即代理漫画生图 API 及其返回图片下载，留空不使用。支持 http://host:port、https://host:port、socks5://host:port；供应商配置表中的代理优先于此设置。",
        "",
    ),
    "ComicDrawingOutputExceptionRetries": GsIntConfig(
        "输出异常重试次数",
        "输出异常重试次数\n当触发屏蔽词/审核等异常时的自动重试次数。次数耗尽后会交给LLM进行改写救场。",
        3,
    ),
    "ComicDrawingOutputExceptionRetryKeywords": GsListStrConfig(
        "输出异常触发关键词",
        "输出异常触发关键词\n当绘图错误信息包含任一关键词时，将其视为内容生成或安全审核异常，并使用同一接口配置重试；重试耗尽后可由 LLM 改写 Prompt。留空则不执行此类内容重试和 Prompt 改写。",
        [],
    ),
    "ComicDrawingRetryDelay": GsIntConfig(
        "画图重试等待时间 (秒)",
        "画图重试等待时间 (秒)\n遇到异常或网络报错时，等待多长时间后重试。针对容易超载的接口建议调高，如 5 或 10。",
        2,
    ),
    "ComicDrawingNetworkRetries": GsIntConfig(
        "网络错误重试次数", "网络错误重试次数\n请求超时、限流或服务端错误时的重试次数；内容审核重试次数请单独配置。", 2
    ),
    "ComicDrawingDownloadProxy": GsStrConfig(
        "图片下载代理",
        "图片下载代理\n下载绘图 API 返回的图片 URL 时使用的代理，格式为 http://host:port 或 socks5://host:port。留空则不使用代理。",
        "",
    ),
    "__divider__incremental": GsDivider("增量分析", "", "incremental"),
    "IncrementalGroupListMode": GsStrConfig(
        "增量分析名单模式",
        "增量分析名单模式\n哪些群用“增量分析”。inherit=直接继承定时分析的最终名单；whitelist=只有列表里的群用增量；blacklist=除了列表外都用增量。没命中的群会走普通模式。增量名单不负责绕过基础或定时名单，只负责选模式。",
        "whitelist",
    ),
    "IncrementalGroupList": GsListStrConfig(
        "增量分析群列表",
        '增量分析群列表\n仅在 whitelist 或 blacklist 模式下使用。示例1：mode=whitelist + ["onebot:GroupMessage:123456"] => 只有这个群增量。示例2：mode=blacklist + ["onebot:GroupMessage:123456"] => 这个群不用增量，其他群用增量。inherit 模式会忽略此列表并复用定时分析名单。whitelist + 空列表 = 不启用增量。',
        [],
    ),
    "IncrementalReportImmediately": GsBoolConfig(
        "增量分析立即报告（调试用）",
        "增量分析立即报告（调试用）\n【调试功能】启用后，每次增量分析完成后都会立即生成并发送一份最终报告。仅建议在调试时开启，生产环境请保持关闭，否则会频繁打扰群友。",
        False,
    ),
    "IncrementalMinMessages": GsIntConfig(
        "增量分析每批消息数",
        "增量分析每批消息数\n目标群每累计到此消息数就触发一个固定规模的增量分析批次；不足时持续等待，待处理消息达到多个批次时会连续处理。建议根据模型上下文和群活跃度设置。",
        300,
    ),
    "IncrementalTopicsPerBatch": GsIntConfig(
        "单次增量提取话题数",
        "单次增量提取话题数\n每次增量分析最多提取的话题数量。最终报告会汇总所有批次的话题。建议1-4。",
        2,
    ),
    "IncrementalQuotesPerBatch": GsIntConfig(
        "单次增量提取金句数",
        "单次增量提取金句数\n每次增量分析最多提取的金句数量。最终报告会汇总所有批次的金句。建议1-2。",
        2,
    ),
    "IncrementalFallbackEnabled": GsBoolConfig(
        "增量失败自动回退全量分析",
        "增量失败自动回退全量分析\n建议开启。开启后，如果增量分析失败，会自动改用普通分析，避免当天没报告。",
        True,
    ),
    "__divider__html": GsDivider("HTML 输出", "", "html"),
    "HTMLBaseUrl": GsStrConfig(
        "外鏈 Base URL",
        "外鏈 Base URL\n用于生成外链的 Base URL（可留空）。如果设置了此项，发送报告时会在消息中提供超连結 (${BASE_URL}/${FILENAME})。留空则不提供外链。",
        "",
    ),
    "HTMLOutputDir": GsStrConfig(
        "报告储存目录",
        "报告储存目录\nHTML 报告文件的保存目录，用于存储生成的 HTML 文件和原始 JSON 数据。留空则自动使用 GsCore 的 data/DailyAnalyisis/self_hosted_html_reports 目录。",
        "",
    ),
    "HTMLOnlyUrl": GsBoolConfig(
        "仅发送外链",
        "仅发送外链\n勾选后，若配置了外链 Base URL，则发送 HTML 报告时将只发送外链链接，不再发送HTML文件，若未勾选，将保持发送HTML文件。",
        False,
    ),
    "HTMLFilenameFormat": GsStrConfig(
        "HTML文件名格式",
        "HTML文件名格式\nHTML文件名格式，支持变量：${group_id}(群号)、${date}(日期)、${trace_id}(链路追踪ID)、${ulid}(时间排序ID)，支持子目录/层级。",
        "群聊分析报告_${group_id}_${date}_${ulid}.html",
    ),
    "__divider__qq_group_upload": GsDivider("报告文件上传", "", "qq_group_upload"),
    "UploadEnableGroupFileUpload": GsBoolConfig(
        "额外发送报告文件",
        "额外发送报告文件\n开启后，图片报告会以普通文件形式再发送一次（MessageSegment.file），不依赖任何平台特化上传 API。",
        False,
    ),
    "UploadGroupFileFolder": GsStrConfig(
        "群文件上传目录名（已停用）",
        "群文件上传目录名（已停用）\n群文件夹上传已停用，此配置仅为保留旧值，不再影响发送行为。",
        "",
    ),
    "UploadEnableGroupAlbumUpload": GsBoolConfig(
        "启用群相册上传（已停用）",
        "启用群相册上传（已停用）\n群相册特化上传已停用，报告统一改为普通文件发送或直接发图。",
        False,
    ),
    "UploadGroupAlbumName": GsStrConfig(
        "目标群相册名称（已停用）", "目标群相册名称（已停用）\n群相册上传已停用，此配置仅为保留旧值。", ""
    ),
    "UploadGroupAlbumStrictMode": GsBoolConfig(
        "群相册上传严格模式（已停用）", "群相册上传严格模式（已停用）\n群相册上传已停用，此配置不再生效。", True
    ),
    "UploadEnableComicAlbumUpload": GsBoolConfig(
        "启用漫画相册上传（已停用）",
        "启用漫画相册上传（已停用）\n漫画相册特化上传已停用，漫画仍会正常发送到群聊。",
        False,
    ),
    "UploadComicAlbumName": GsStrConfig(
        "漫画相册名称（已停用）", "漫画相册名称（已停用）\n群相册上传已停用，此配置仅为保留旧值。", ""
    ),
    "__divider__prompts": GsDivider("提示词", "", "prompts"),
    "PromptTopicAnalysisPromptsTopicPrompt": GsStrConfig(
        "默认话题分析提示词",
        "默认话题分析提示词",
        '请分析接下来提供的群聊记录，提取出 1 到 **${max_topics}** 个主要话题。**如果聊天记录较多，请务必仔细分析，尽可能多地提取出不同层面的话题，争取达到 ${max_topics} 个上限**。\n\n## 对于每个话题，请提供：\n\n1. **话题名称**（突出主题内容，尽量简明扼要，控制在 10 字以内）\n2. **主要参与者的用户ID**（最多 5 人，按参与度排序）\n3. **话题详细描述**（包含关键信息和结论）\n\n## 注意事项：\n\n- 在生成描述内容时，请务必从你当前人格设定的视角和口吻出发。\n- 对于比较有价值的点，稍微用一两句话详细讲讲，让读者能了解讨论的深度\n- 对于其中的部分信息，你需要特意提到主题施加的主体是谁，即明确指出"谁做了什么"\n- **用户引用**：在话题详情描述中，如果提到了具体用户，请使用 `[用户ID]` 的格式来指代（例如 `[123456]`）。不要只写昵称。我们会自动渲染头像。\n- 对于每一条总结，尽量讲清楚前因后果，不要只列出结论\n- 如果某个话题有明确的结论或共识，请在描述中体现\n- 忽略无意义的闲聊、灌水、单纯的表情回复等\n- 优先选择讨论深度较深、参与人数较多的话题\n- 如果消息太少或没有明确话题，可以返回空数组 []\n\n群聊记录格式: [HH:MM] [用户ID]: 消息内容\n\n群聊记录：\n${messages_text}\n\n---\n\n## 重要：必须返回标准 JSON 格式\n\n严格遵守以下规则：\n\n1. 只使用英文双引号 `"` ，不要使用中文引号 `“` `”`\n2. 字符串内容中的引号必须转义为 `\\"`\n3. 多个对象之间用逗号分隔\n4. 数组元素之间用逗号分隔\n5. 不要在 JSON 外添加任何文字说明\n6. 描述内容避免使用特殊符号，用普通文字表达\n\n### 返回格式示例：\n\n```json\n[\n  {{\n    "topic": "话题名称",\n    "contributors": ["123456789", "987654321"],\n    "detail": "话题的详细描述，包含讨论内容、关键信息和结论。注意：在描述中提及用户时，使用 [用户ID] 格式，例如 [123456789]。"\n  }},\n  {{\n    "topic": "另一个话题",\n    "contributors": ["111222333", "444555666"],\n    "detail": "另一个话题的详细描述..."\n  }}\n]\n```\n\n**注意**：返回的内容必须是纯 JSON，不要包含 markdown 代码块标记或其他格式。',
    ),
    "PromptUserTitleAnalysisPromptsUserTitlePrompt": GsStrConfig(
        "默认用户称号分析提示词",
        "默认用户称号分析提示词",
        '请为以下群友分配合适的称号和 MBTI 类型。\n\n## 规则：\n\n- 每个人只能有一个称号\n- 每个称号只能给一个人\n\n## 可选称号：\n\n- **龙王**: 发言频繁但内容轻松的人\n- **技术专家**: 经常讨论技术话题的人\n- **夜猫子**: 经常在深夜发言的人\n- **表情包军火库**: 经常发表情的人\n- **沉默终结者**: 经常开启话题的人\n- **评论家**: 平均发言长度很长的人\n- **阳角**: 在群里很有影响力的人\n- **互动达人**: 经常回复别人的人\n- *...（你可以自行进行拓展添加）*\n\n## 用户数据：\n\n${users_text}\n\n---\n\n### 返回格式示例：\n\n```json\n[\n  {{\n    "name": "用户名",\n    "user_id": "123456789",\n    "title": "称号",\n    "mbti": "MBTI类型",\n    "reason": "获得此称号的原因"\n  }}\n]\n```\n\n**注意**：请以纯 JSON 格式返回，不要包含 markdown 代码块标记。',
    ),
    "PromptGoldenQuoteAnalysisPromptsGoldenQuoteV2Prompt": GsStrConfig(
        "默认金句分析提示词",
        "默认金句分析提示词",
        '请从以下群聊记录中挑选出 **${max_golden_quotes}** 句最具冲击力、最令人惊叹的「金句」。\n\n## 金句标准：\n\n- **核心标准**：**逆天的神人发言**，即具备颠覆常识的脑洞、逻辑跳脱的表达或强烈反差感的原创内容\n- **典型特征**：包含某些争议话题元素、夸张类比、反常规结论、一本正经的「胡说八道」或突破语境的清奇思路，并且具备一定的冲击力，让人印象深刻\n\n## 对于每个金句，请提供：\n\n1. **原文内容**（完整保留发言细节）\n2. **发言人用户ID**（必须严格使用消息记录中提供的 [用户ID]）\n3. **选择理由**（具体说明其「逆天」之处，如逻辑颠覆点/脑洞角度/反差感/争议话题元素）\n\n## 严格约束：\n\n- 优先筛选 **逆天指数最高** 的内容：\n  - 发情、性压抑话题 > 争议话题 > 元素级 > 颠覆认知级 > 逻辑跳脱级 > 趣味调侃级\n  - 剔除单纯玩梗或网络热词堆砌的普通发言\n- **用户引用**：在选择理由（reason）中，如果提到了具体用户，请使用 `[用户ID]` 的格式来指代（例如 `[123456]`）。不要只写昵称。我们会自动渲染头像。\n- **身份对齐**：返回的 `sender` 字段必须是 `[用户ID]` 格式（例如 `[123456]`）。我们会根据 ID 自动还原昵称和头像。\n\n## 群聊记录格式: [HH:MM] [用户ID]: 消息内容\n\n## 群聊记录：\n\n${messages_text}\n\n---\n\n### 返回格式示例：\n\n```json\n[\n  {{\n    "content": "金句原文",\n    "sender": "[123456789]",\n    "reason": "这句话太逆天了，尤其是对 [987654321] 的逻辑降维打击。"\n  }}\n]\n```\n\n**注意**：返回的内容必须是纯 JSON，不要包含 markdown 代码块标记或其他格式。',
    ),
    "PromptQualityAnalysisPromptsQualityV2Prompt": GsStrConfig(
        "默认聊天质量分析提示词",
        "默认聊天质量分析提示词",
        '请分析以下群聊记录，输出一份"聊天质量锐评"。\n\n## 任务目标：\n1. **维度划分**：将聊天内容划分为 3-6 个【高层级、抽象、泛化】的维度（例如：就业焦虑、生涯规划、技术方案研究、情感树洞、无意义水群等）。\n2. **严禁在维度名称（name）中出现任何具体的群聊人物名、项目名、具体的报错内容或细碎的事件点。标题必须保持高度抽象且字数简练（2-6个字）。**\n3. 为每个维度计算一个大致的百分比占位（总和小于等于 100%）。\n4. **点评内容**：为每个维度写一句符合你当前人格设定的犀利、幽默或温情的点评。具体的吐槽内容、具体的细节事件描述请放在这里。\n5. **全群表现**：给出一句总结性的评价，作为总结标题对应的“金句”。\n6. **主题设定**：设定一个本次报告的主题标题和副标题。\n\n## 点评风格指南：\n- 语言要接地气，多用互联网黑话。吐槽要精准，避重就轻。\n- **只有维度名称（name）需要抽象，点评（comment）和总结（summary）可以非常具体和生动。**\n\n## 返回格式要求：\n必须以纯 JSON 格式返回，不得包含任何 Markdown 格式。\n\n```json\n{{\n  "title": "今日群聊主题",\n  "subtitle": "副标题",\n  "dimensions": [\n    {{\n      "name": "抽象维度名",\n      "percentage": 比例,\n      "comment": "与该维度相关的锐评，请务必保持你的人设口吻"\n    }}\n  ],\n  "summary": "一句总结性的金句"\n}}\n```\n\n群聊记录：\n${messages_text}',
    ),
    "PromptQualityAnalysisPromptsQualitySummaryPrompt": GsStrConfig(
        "增量汇总聊天质量分析提示词",
        "增量汇总聊天质量分析提示词",
        '你现在有一份今天全天分散时间段的多个“增量批次点评笔记”。\n你的任务是将这些分散的笔记汇总成一份最终的“全天聊天质量终极锐评”。\n\n## 任务目标：\n1. **全局抽象维度**：根据各批次的维度表现，平衡权重，提取出 3-6 个覆盖全天的【核心、上层抽象】课题维度（如：职场/行业风向、技术架构演进、社畜心理博弈等）。\n2. **严禁在维度名称（name）中出现具体的批次细节。标题必须代表全天的某种趋势。**\n3. **百分比融合**：根据全天笔记的频率和强度，给出一个代表全天整体分布的比例（总和不超过100%）。\n4. **终极点评**：为每个汇总维度写出一句符合你当前人设且升华后的全天总结性点评。可以融合具体批次中的有趣槽点。\n5. **终极总结**：拟定全天的大型主题标题、副标题，并给出一句霸气的全天表现总结。\n\n## 风格要求：\n- 只有维度名称（name）需要高度概括抽象。\n- 点评（comment）和总结（summary）请尽量生动、具体，要把一整天的梗串联起来。\n\n## 返回格式要求：\n必须以纯 JSON 格式返回，不得包含任何 Markdown 格式。\n\n```json\n{{\n  "title": "今日群聊主题",\n  "subtitle": "副标题",\n  "dimensions": [\n    {{\n      "name": "抽象大类标题",\n      "percentage": 比例,\n      "comment": "全天的锐评总结，请务必保持你的人设口吻"\n    }}\n  ],\n  "summary": "全天总结金句"\n}}\n```\n\n增量汇总数据：\n${reviews_text}',
    ),
    "PromptComicAnalysisPromptsComicStoryboardPrompt": GsStrConfig(
        "默认漫画场景分析提示词",
        "默认漫画场景分析提示词\n让大模型根据核心话题生成丰富生动的多格连环漫画画图提示词",
        '你是一个资深的漫画分镜师与 AI 绘画提示词专家。\n请根据以下给出的【群聊每日核心话题列表】，站在你【当前的人格角色设定】（详见系统注入的身份）的视角与语气，将其改编并设计为一个精彩的多格连环漫画（Comic Strip）全景视觉画图提示词 (Prompt)。\n\n【核心视觉、台词与双层排版规则】：\n1. 【全话题必须覆盖（共 ${topic_count} 个分格）】：给出的待创作核心话题列表中共有 ${topic_count} 个话题，你必须为每一个话题分别设计一个分格 Panel（即 Panel 1 到 Panel ${topic_count}），绝对不许随意裁减、挑选或遗漏任何一个话题！\n2. 【人设口语化台词改编】：绝对严禁将报告分析总结原文直接放进对话框！必须以【你当前的人格语气/性格/口吻】（例如傲娇、萌系或专属说话风格），将每个话题的事件提炼改编为一句角色在漫画中的生动台词或吐槽，【每条台词控制在 15 个汉字以内】（例如：“呜呜！家里云又断网了啦！”、“萝卜子才没有降智！那都是Gemini的错！”）。\n3. 【精美双层文字排版（气泡 + 可爱旁白字幕条）】：\n   - 【角色的气泡】：在描述英文 Prompt 时，指定样式为“adorable kawaii anime speech bubble, soft rounded cloud-like shape, cute pointer tail pointing to the speaker”。\n   - 【分格底部的事件旁白条】：将每个话题概括为生动精炼的短标题（控制在 30 字以内，严禁带有“【事件】”字样），在 Prompt 中指定样式为“cute pastel-colored kawaii caption strip at the bottom of the panel with soft rounded corners”，严禁死板白框！\n4. 【中文文本显式渲染】：画面整体构图与场景描述使用英文，但气泡与底部旁白条内渲染的中文必须显式指定（指令格式：containing a speech bubble with exact Chinese text "人设吐槽台词" 以及 and a cute caption strip at bottom with exact Chinese text "精炼话题短标题"），绝对禁止将中文翻译成英文！\n5. 【话题内容直传与文字渲染约束】：在生成传给生图 LLM 的英文提示词 (scene) 时，对于每一个分格，除了描述具体的视觉画面外，你必须将该话题的【完整详情（翻译为英文）】作为 Background Context 附加在该分格的提示词中，帮助生图模型理解剧情。但同时，必须极其强烈地警告生图模型：“绝对禁止将长篇上下文写在画面上，仅允许渲染短标题字幕条和气泡台词！”（示例：Background Context: [Details]. STRICT RULE: DO NOT render the background context text! ONLY render the exact Chinese text in the bubble and caption strip!）。\n6. 【核心角色强制全覆盖】：在提示词中必须明确要求并描述，每一个分格 (Panel) 都必须无一例外地出现你当前的人格设定（即参考图中的核心角色，例如 1girl, [特定外貌特征] 等），保持整篇连环画的主角绝对连贯！\n\n【待创作的群聊核心话题列表】：\n${chat_content}\n\n请输出包含 "scene" 字段的 JSON 对象。\n',
    ),
    "__divider__performance": GsDivider("并发与限流", "", "performance"),
    "PerformanceMaxConcurrentGroups": GsIntConfig(
        "最大活跃任务数（任务总闸）",
        "最大活跃任务数（任务总闸）\n限制同时有多少个群聊分析任务正在进行。主要用于【保护服务器内存和 IO】，防止瞬间读取过多群聊记录导致程序崩溃（OOM）。",
        2,
    ),
    "PerformanceMaxConcurrentLlm": GsIntConfig(
        "最大 LLM 请求并发数（API 闸口）",
        "最大 LLM 请求并发数（API 闸口）\n限制同时发起的 AI 分析请求数量。主要用于【遵守 API 频率限制（RPM）】，避免因为请求过快导致 API 被封号或报错。",
        4,
    ),
    "PerformanceMaxConcurrentT2i": GsIntConfig(
        "最大 T2I渲染并发数", "最大 T2I渲染并发数\n限制同时开启的 T2I 渲染进程数。", 1
    ),
    "PerformanceStaggerSeconds": GsIntConfig(
        "多群分析交错间隔（秒）",
        "多群分析交错间隔（秒）\n当同时启动多个群组的定时分析任务时，每个任务之间的延迟间隔（秒），建议根据实际的 LLM 服务速度填写，过短可能导致请求堆积，过长则分析效率降低。",
        30,
    ),
}
