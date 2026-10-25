# MaiBot 源码与插件

这里包含 MaiBot 1.2.5 的当前修改版源码与自定义插件，保留上游许可；不包含 Python 便携运行时、QQ、SnowLuma、个人聊天数据库、角色图片或登录凭据。

## 初始化与启动

在仓库根目录按根 README 安装 Python 3.12+ 与依赖，运行 `python tools/setup.py --with-bot` 生成配置。安装 MaiBot 依赖的目标文件为 `bot/MaiBotOneKey/modules/MaiBot/requirements.txt`。配置文件必须使用 UTF-8。

初始化会把 `config/bot_config.example.toml`、`config/model_config.example.toml` 复制为同目录的 `bot_config.toml`、`model_config.toml`，并复制 SnowLuma 适配器的 `config.example.toml` 为 `config.toml`；已有配置不会被覆盖。首次安装请从终端查看日志，完成必需配置后再启用自动启动。

直接启动核心：切换到 `bot/MaiBotOneKey/modules/MaiBot`，运行 `python bot.py`。关闭该终端会停止它。根启动器仅在显式指定 `--with-bot` 时启动核心。这里的旧 OneKey `main.py/start.py` 仅作为上游源码保留，不作为本发行版推荐启动入口。

## 模型配置

1. 修改 `config/model_config.toml`：`api_providers[0]` 的 `base_url`、`api_key` 替换为你自己的 OpenAI 兼容服务，`models[0].model_identifier` 替换为服务商实际支持的模型名称。`example.com` 与 `YOUR_MODEL_NAME` 都是占位符。保持 `api_provider` 与服务商 `name` 一致。
2. `model_task_config.replyer.model_list` 选择输出回复模型；`planner` 选择决策模型；`utils` 等辅助任务可先复用 `chat-model`。这里引用的是 `models[].name`，不是服务商的模型标识。
3. 图片理解需要单独添加支持视觉的模型，设 `visual=true` 并分配给 `vlm`。长期记忆默认关闭；启用前配置 `embedding` 模型与维度，再启用 `bot_config.toml` 中的 A_memorix。更换已有记忆库的 embedding 模型需要重新嵌入，不能直接复用不同模型的向量。
4. 本模板计费字段为 0，不代表服务免费；按服务商账单为准。不要把填写后的配置、API Key 或 OAuth 凭据提交到 Git。

## QQ 接入与插件

自行安装并运行 QQ 和 SnowLuma，只连接你自己授权的机器人账号。SnowLuma 的正向 WebSocket 监听 `127.0.0.1:3001`；适配器配置在 `plugins/snowluma-adapter/config.toml`，访问令牌应与 SnowLuma 设置一致。`[chat]` 默认使用空白白名单，主动填入允许接收消息的群号和私聊账号后才会接收对应聊天。不要启用“自动注入所有 QQ 进程”，避免接入私人号。

插件源码：

- `snowluma-adapter`：OneBot/SnowLuma 消息桥接。
- `web-search`：聊天检索网页；使用前检查网络与插件配置。
- `fun-games`：运势、塔罗、抽签、骰子、抽猪等娱乐功能，部分玩法依赖外部服务。
- `random-quirky`：可选随机短句功能；本包不含个人怪话库，需自行提供内容。
- `tts-voice`：可选语音输出；语音服务、API Key、模型与参考音频需自行配置，不包含个人声音样本。
- `guozi-pig-game`：外部群游戏的可选命令桥接，默认关闭；需显式填写本地环境变量 `QQBOT_GAME_GROUP_ID` 和 `QQBOT_GAME_BOT_ID`。

其他插件首次由宿主按插件 schema 生成本地配置。个人角色提示词、身份图库与历史关系记忆没有随包分发；示例角色为中性“小麦”。好感度插件默认管理员列表为空，需在自己生成的插件配置中填入管理员 QQ 后再使用管理命令。自动生成的本地数据库与日志只保存在使用者本机。

## 来源

MaiBot 上游：<https://github.com/MaiM-with-u/MaiBot>，基础提交 `1f16661b665c8f7150a2e4b545f4f24fbff34638`。OneKey 上游：<https://github.com/DrSmoothl/MaiBotOneKey>，基础提交 `67ba90cbf58320cb8a4ce6599f6267955ce52742`。这是脱敏后的独立源码快照，包含本地修改与必要新增文件，不保留生产仓库历史。上游原说明见 `modules/MaiBot/UPSTREAM_README.md`，具体许可见根 `THIRD_PARTY_NOTICES.md` 及各级 LICENSE。
