# 第三方来源与许可

本仓库是 Windows QQ 机器人栈的集成发行源码，包含不同来源的组件。保留每个组件原有版权与许可声明；根目录声明不能替代子目录自身的许可。

| 组件 | 来源 | 许可 / 说明 |
| --- | --- | --- |
| MaiBotOneKey 启动器源码 | https://github.com/DrSmoothl/MaiBotOneKey ，基于 `67ba90cbf58320cb8a4ce6599f6267955ce52742` | `bot/MaiBotOneKey/LICENSE`，GPL-3.0 |
| MaiBot 1.2.5 与本地修改 | https://github.com/MaiM-with-u/MaiBot ，基于 `1f16661b665c8f7150a2e4b545f4f24fbff34638` | `bot/MaiBotOneKey/modules/MaiBot/LICENSE`，GPL-3.0；子模块单独许可继续适用 |
| MaiBot Dashboard | MaiBot 源码内的 `dashboard/` | `dashboard/LICENSE`，AGPL-3.0 |
| A_memorix | MaiBot 源码内的 `src/A_memorix/` | 保留 `LICENSE`（AGPL-3.0）和 `LICENSE-MAIBOT-GPL.md`（针对 MaiBot 项目上下文的额外 GPL 许可）；分发、修改与抽取使用时遵守对应条款 |
| 模型客户端子模块 | MaiBot 源码内的 `src/llm_models/` | 以该子目录 `LICENSE` 为准 |
| 本地插件 | `plugins/*/_manifest.json` | manifest 声明 GPL-v3.0-or-later；保留其 manifest、README 与已有版权声明 |
| Python / JavaScript 依赖 | 各组件 requirements.txt、pyproject.toml、package.json 与锁文件 | 通过包管理器单独安装；各依赖保留自身许可，本发行版不打包其二进制 |

本仓库未分发 QQ、SnowLuma、Python 便携运行时、第三方模型权重、个人语音/角色图片、个人聊天数据、登录态或 API 凭据。它们需由使用者自行获取并根据各自条款使用。源码中保留上游作者与来源链接；第三方名称用于说明兼容关系。

2026-10-25 的发行快照增加了源码脱敏、中性示例配置和可移植初始化/启动说明；生产账号、群号与管理员默认值没有随包分发。
