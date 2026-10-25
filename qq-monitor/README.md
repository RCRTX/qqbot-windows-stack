# QQ 群监控

通过兼容 OneBot v11 的正向 WebSocket 收消息，使用 HTTP API 查询历史或发送告警，保存聊天消息并提供检索、导出、规则匹配与可选 AI 审核。

仓库根安装脚本将 `config/config.win.example.json` 复制为 `config/config.win.json`，并将 `examples/monitor/*.json` 复制到 `config/`；已有配置保留。填写 `napcat.ws_url`、`http_url`、`token` 与 `monitor_groups` 后启动。

直接运行时，在本目录执行：

```powershell
..\.venv\Scripts\python.exe src/main.py -c config/config.win.json --web-port 8080
```

默认关闭 AI 审核、二次复核、陪聊、复读、戳一戳、关键词发言、长期记忆/提醒和日记；告警收件人与群名单为空；不自动删除聊天记录。规则文件初始为空，每行一条。启用 AI 时再填写 OpenAI 兼容 API、模型与密钥。

`napcat` 是兼容配置段名，可接入兼容的 OneBot 适配器。默认 HTTP/WS 为本机 3000/3001，监控网页仅本机 8080。`storage` 相对路径以本目录为基准，不要求特定盘符。

自动 QQ 钩子看守默认关闭，适配器由部署者自行运行。日记、长期记忆等附加模块只有配置并开启后才运行。音频、图片、RVC 扩展需要额外工具和模型；仓库不包含私人素材和历史数据库。
