# 配置说明

执行 `python tools/setup.py` 后，编辑生成的生效配置。生成器不会覆盖已有文件；模板更新后需自行对比合并。JSON 不支持注释，列表里的 QQ 号/群号类型按模板填写。

| 配置 | 填什么 |
|---|---|
| `qq-monitor/config/config.win.json` | OneBot 地址/token、机器人号、监控群、告警接收人、存储路径、规则与 AI 审核开关。 |
| `qq-monitor/rules/keywords.txt` | 需要匹配的关键词规则。空文件表示尚未设置。 |
| `qq-monitor/rules/banned_words.txt` | 禁词规则。请按自己群的规则添加。 |
| `examples/monitor/` | 日记、记忆、关键词回复等可选功能的空白示例；复制/生成至监控 config 后配置。 |
| `bot/MaiBotOneKey/modules/MaiBot/config/` | MaiBot 机器人与模型配置，参阅 bot 子目录说明。 |
| MaiBot `plugins/*/config.toml` | 插件专属连接参数/白名单/API。不要直接套用别人的账号配置。 |

## OneBot

本仓库使用正向 WebSocket：监控/MaiBot 主动连接 SnowLuma 的 WS 服务。常用地址为 `ws://127.0.0.1:3001`，HTTP 动作接口为 `http://127.0.0.1:3000`。在 SnowLuma 与各客户端填相同 token，确认服务绑定在回环地址。QQ 客户端重新启动后需检查桥接是否恢复。

## 存储

发布版不附带数据库、聊天记录或人物记忆。默认在发布目录内创建本地数据。修改数据路径时先停对应服务，完整备份后再迁移。自动清理聊天记录默认关闭；日常停止/升级不会要求删除数据库。

## 模型

AI 审核和 MaiBot 聊天分别配置。若使用 OpenAI 兼容接口，填写自己的 `base_url`、`api_key` 和实际存在的模型名。识图需模型支持图像；记忆需可用 embedding。首次使用先测试单项连接再开启功能，不要求某一家付费提供商。

本仓库不含模型账号登录态、订阅转接服务或作者使用的第三方网关。若切换已有记忆库的 embedding 模型，先备份并按上游说明重建向量，不能假设不同模型的向量可以混用。

## 端口

| 端口 | 功能 |
|---|---|
| 3000 | 外部 OneBot HTTP |
| 3001 | 外部 OneBot 正向 WebSocket |
| 5099 | SnowLuma WebUI（由外部程序决定） |
| 8080 | 监控面板 |
| 8090 | 统一控制台 |
| 8000 / 8001 | 可选 MaiBot 核心 / WebUI，以实际配置为准 |

同时运行多个实例时需要分别修改全部关联配置和启动器端口；默认启动器不自动寻找新端口。
