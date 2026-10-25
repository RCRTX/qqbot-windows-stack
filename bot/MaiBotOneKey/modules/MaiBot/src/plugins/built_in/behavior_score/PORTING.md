# behavior_score 移植到麦麦 1.2.5 —— 接线手册（已验证）

> 2026-09-24 起。**当前状态：基础设施 + 三个挂载点 + `AFTER_SEND` 记账链路已验证；
> `ON_MESSAGE` 的记账与 `before_request` 的注入还没接。**

## 文件分工

- `logic.py` —— 从旧插件**原样搬过来**的 2257 行纯逻辑（常量、`classify`、`favor_delta`、
  `ScoreStore`、`FavorStore`、`ReflectionStore`、`handle_*` 辅助函数）。
  只改了 3 处：import 块（`src.plugin_system` → 标准库 logging + `MaiMessages = Any`）、
  两处 `emoji_api`（改成注入式的 `emoji_provider`）。
  ROOT 推导**不用改** —— 新旧文件同层级，往上四层都是麦麦根目录（实测解析正确）。
- `plugin.py` —— 新版 SDK 接线：`MessageAdapter` 把 1.2.5 的 payload 适配成旧属性名，
  `get_config()` / `send_text()` / `send_image()` 提供旧代码要的接口，然后调 `logic`。

## 已实测跑通的链路

```
AFTER_SEND  → SCORE.note_bot_said()  → data/behavior_score.json 里 streams[sid].last_bot_text ✅
```

实测日志（2026-09-24 21:57，用 `panel/tools/probe_legacy_message.py` 灌的假消息）：

```
ON_MESSAGE sid=9c8ddf26 user=999000002 mentioned=False text='[迁移自检] 示例助手在吗，说句话'
BEFORE_REQUEST sid=9c8ddf26 有入站缓存=True reply_to=probe-1790258242
AFTER_SEND 记下麦麦发言 sid=9c8ddf26 text='[迁移自检] 示例助手在吗，说句话 又来了，我在呢'
```

## 1.2.5 的 payload 形状（实测抓的，不是猜的）

`chat.receive.after_process`：

```json
{"message_id","timestamp","platform":"qq",
 "message_info":{"user_info":{"user_id","user_nickname","user_cardname"},
                 "group_info":{"group_id","group_name"},"additional_config":{}},
 "raw_message":[{"type":"text","data":"..."}],
 "is_mentioned","is_at","is_emoji","is_picture","is_command","is_notify",
 "session_id","processed_plain_text"}
```

⚠️ `raw_message` 是**段数组**（0.11 里是字符串），所以 `MessageAdapter` 分开存：
`message_segments`=数组、`raw_message`=拼好的文本。

`maisaka.replyer.before_request` 的 kwargs：
`hook_name, session_id, request_type, task_name, model_name, extra_prompt, attempt,
retry_count, max_retries, reply_message_id, reply_reason, selected_expression_ids, reply_tool_args`

⚠️ **它不给入站正文**（只有 `session_id` 和 `reply_message_id`），所以
`on_message` 里把最近一条入站消息按 `session_id` 缓存（`_latest_inbound`）供它使用。

## ⚠️ 自检时的注意事项（踩过三次，都是**写坏了线上真实数据**）

**① `behavior_score.json` 的 `score` 是全局一个数，不是按聊天流。** 用假消息灌
「闭嘴」做自检时，扣的是**线上真实的表现分**（2026-09-24 从 100 被打到 44）。
自检完必须还原：`logs/mai125/cleanup_test_residue.py` 那套做法（改前备份、
只删测试会话的 streams/events、把 `score` 写回测试前的值、删掉测试用户的好感度）。
`favorability.json` 里那个假用户（`999000002`）也要一起删。

**② 探针第一步必须调 `isolate_stores()`**（`panel/tools/_behavior_score_harness.py` 提供）。
`logic.SCORE` / `logic.FAVOR` 在模块导入时就指向真实数据文件，探针里随便一次
`note_bot_said()` / `bump()` / `admin_reset()` 都会**落盘到线上**。踩过两次：
好感度探针曾把线上 `behavior_score.json` 覆盖成测试数据（它后来加了隔离），
而 **CG 探针一直没隔离 `SCORE`**（每跑一次就往真实文件塞测试流和事件），2026-09-24 才发现。

**③ 自检完清理测试流**：`logs/mai125/cleanup_probe_streams.py`
（删 `probe-cg-stream` / `9c8ddf26…` 这种假聊天流，免得面板上多出两个"群"）。

查有没有被写坏：跑测试前后各算一次 md5
（`md5sum data/behavior_score.json data/favorability.json`），两个值必须一样。

## 几个必须知道的坑

1. **`logic` 不能用 `import logic` 加载**：宿主用 importlib 按文件加载 `plugin.py`，
   插件目录不在 `sys.path` 上 → `No module named 'logic'`。用 `importlib.util.spec_from_file_location`
   按 `__file__` 同级路径加载（`plugin.py` 里的 `_load_logic()`）。也不是包导入，`from . import` 同样不行。
2. **`logic.logger` 要在 `on_load` 里换成 `self.ctx.logger`**，否则日志不进麦麦日志流。
3. **`i18n` 是 manifest 必需字段**；**必须实现 `on_config_update()`**；
   **配置模型里必须有 `plugin` 节**（宿主拿模型和 config.toml 合并后校验，模型里没有就报"缺少 [plugin] 配置节"）。
4. `manifest.id` 要形如 `local.behavior-score`（必须带 `.` 或 `-`）；目录名 `behavior_score` 不用一致。
5. 别照抄 `plugins/hello_world_plugin`（用 `@EventHandler(ON_MESSAGE)`，过期示范）。

## 为什么不能直接把旧插件拷过来

旧插件（在 `modules/MaiBot-0.11-backup/src/plugins/built_in/behavior_score/`）靠三个事件钩子，
而 1.2.5 把那条事件总线**摘掉了**：

- `src/chat/events_manager.py` 文件已不存在
- `src/chat/message_receive/bot.py` 里 `ON_MESSAGE` 的 emit **被注释掉**
- `src/chat/message_receive/uni_message_sender.py` 里 `POST_SEND` / `AFTER_SEND` 的 emit **被注释掉**
- 只剩 `ON_START` / `ON_STOP` 还在 emit

所以旧插件的 3 个 `EventHandler` 装上去也是死的（能加载、永远收不到）。**必须改成命名 Hook。**

## 挂载点对照（三个都实测命中过）

| 旧（0.11 事件） | 新（1.2.5 命名 Hook） | 能力 | 用途 |
|---|---|---|---|
| `EventType.ON_MESSAGE` | `chat.receive.after_process` | `allow_abort=True`，可改写 | 记账（好感度/表现分） |
| `EventType.POST_LLM` | `maisaka.replyer.before_request` → 返回 `extra_prompt` | 可改写、**不能 abort** | 注入语气/规则 |
| `EventType.AFTER_SEND` | `send_service.after_send` | 只读（`sent` 等） | 记"麦麦刚说了什么"，用于归因 |
| `BaseCommand` | `@Command(pattern=...)` | — | 「好感度」「表现分」管理命令（旧插件这两个还能用） |

实测日志（2026-09-24 21:47，用 `panel/tools/probe_legacy_message.py` 灌的假消息）：

```
HOOK chat.receive.after_process 命中第 1 次 user=999000002 group=999000001 text='[迁移自检] …'
HOOK maisaka.replyer.before_request 命中第 1 次
HOOK send_service.after_send 命中第 1 次 sent=True text='…在呢在呢，刚刷完一波视频。'
```

**已知唯一的能力缺口**：`before_request` 不能中止这次回复，所以旧插件里
「好感度太低 → 不走正常回复、只回一句『你是坏人』」那种**接管**，得挪到
`chat.receive.after_process` 里自己做（那里 `allow_abort=True`，可以自己 `ctx.send.text` 再 abort）。

## 踩过的三个 manifest/config 坑（都在这一个插件上踩的）

1. **`i18n` 是 manifest 必需字段**，缺了直接 `manifest 校验失败`：
   ```json
   "i18n": {"default_locale": "zh-CN", "supported_locales": ["zh-CN"]}
   ```
2. **必须实现 `on_config_update(self, scope, config_data, version)`**，否则
   `插件 X 必须实现 on_config_update()`，注册失败。
3. **配置模型里必须有 `plugin` 节**。宿主是拿「配置模型」和 `config.toml` 合并后再校验的；
   模型里没有 `plugin` 字段 → 合并结果没有 `[plugin]` → 报
   「插件配置文件缺少 [plugin] 配置节」，**配置文件里写了也没用**。照抄
   `src/plugins/built_in/plugin_management/plugin.py` 的 `PluginSectionConfig`。
4. `manifest.id` 必须形如 `^[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)+$`（要带 `.` 或 `-`），
   所以叫 `local.behavior-score`（目录名仍是 `behavior_score`，两边不用一致）。
5. `host_application.max_version` 写太小会「未激活/不兼容」；跨 major.minor 直接报错。
   这里写 `1.99.99` / SDK `2.99.99`。

## 数据文件：路径和字段名一个都不能改

面板直接读这两个文件（`panel/app.py` 的「表现分」「好感度」页）：

- `data/behavior_score.json` → `{score, updated_at, streams{...}, events[...]}`
  - event：`{time, ts, delta, score, reason, stream, bot_said, they_said}`
- `data/favorability.json` → `{updated_at, users{uid:{name, score, last_ts, hits, last_reason, ...}}}`

⚠️ **不要**改用 SDK 推荐的 `ctx.data_dir`（那是 `data/plugins/<id>/`），否则面板页签直接废。
插件跑在独立子进程里，cwd 是麦麦根目录，直接按相对路径 `data/xxx.json` 读写即可
（沿用旧插件的原子写 + mtime 外部改动重读）。

## 进度：搬完了什么 / 还差什么

**已完成（都有实测证据）**

- ✅ `logic.py`：2257 行纯逻辑原样搬过来（`ScoreStore` / `FavorStore` / `ReflectionStore` /
  `classify` / `favor_delta` / `SentStickerStore` / 全部 `handle_*` 辅助函数 / CG 与 NapCat 直发工具）
- ✅ 新版 SDK 接线：`MessageAdapter` + `get_config()` / `send_text()` / `send_image()` / `llm_generate()`
- ✅ 三个挂载点实测命中；`AFTER_SEND` 记账、`ON_MESSAGE` 加减分、被扣分后的复盘**全部端到端跑通**
- ✅ **回复闸门**（旧 `ReplyGuardHandler` 的前半段）搬到 `on_message`：实测「我的好感度是多少」
  → 直接回「你在我这儿 100」并 **abort** 掉正常回复（不会说两遍）
- ✅ **提示词注入**（同一处理器的后半段）搬到 `before_request`：实测日志
  `注入提示词 360 字（2 段）`；宿主源码确认它被消费 ——
  `maisaka_generator_base.py:1110` 把 `before_request_kwargs["extra_prompt"]`
  交给 `_build_reply_requirements()` → `_build_request_messages(reply_requirements=...)`，
  即真的进了模型请求（注入内容不会打进日志，别去日志里找标记）
- ✅ 插件配置键与旧 `config.toml` 完全对齐，旧值原样搬
- ✅ **两个管理命令**（`@Command`）：实测管理员发「好感度 zzz」→ 回
  `用法：好感度 [@某人] [重置|设为的数字|+N|-N]`；非管理员发「表现分 zzz」→ 不吭声，
  消息继续走正常聊天（和旧版一致）
- ✅ **表情包能力注入**：`logic.emoji_provider = _EmojiProvider(ctx)`
  （SDK 返回 `{"emojis":[{"base64",…}]}`，旧代码按 `item[0]` 取，所以适配器转成了元组列表）
- ✅ **表情包发送**（库模式）**已实测**：@它说「表情包」→ 真发出一张库里的图
  （探针收到 `{"type":"image","data":"R0lGOD…"}`）。
  链路：先试 NapCat 直发（QQ 没登录时会 401）→ **退回麦麦出站**，降级正常，
  日志 `[表情包] 给 X 发了 1 张库里的（今日 3/30）`
- ✅ 既有探针「表现分判定」已改为直接测 `logic.py`，**真跑通过**
- ✅ **另外两个探针也救回来了**（此前因 0.11 handler API 消失而跳过）：现在驱动**真实插件本体**
  （假 ctx，见 `panel/tools/_behavior_score_harness.py`），三个探针全绿、**零跳过**。
  这样连「1.2.5 payload → 旧属性名」的适配层一起被测到 —— 这个改造立刻抓出了一个真 bug（见下）。

**⚠️ 段（segment）必须包成对象，不能给字典**：旧逻辑一律用 `getattr(seg, "type")`
取段（`logic._reply_image_b64s`、`logic._seg_mentions`），而 1.2.5 的 `raw_message` 是
**字典数组**。直接塞进去 `getattr` 取不到、又不报错 —— 表现是「回复表情包说删掉」
认不出是哪张图、md5 兜底也失效（探针 `recalled=[] deleted=[]`，日志一声不吭）。
修法：`MessageAdapter.message_segments` 用 `_Seg`（带 `.type`/`.data`，嵌套 seglist 递归包）
还原成 0.11 的 `maim_message.Seg` 形状。

**⚠️ SDK 返回值别照文档写，实测才是真的**（栽过两次，都是"不报错但功能静默失效"）：

| 能力 | 文档/宿主层写的 | SDK 实际返回 |
|---|---|---|
| `llm.generate` | `{"success","response","reasoning","model"}` | 同左，正文在 **`response`**（按 `content`/`text` 取会恒空）|
| `emoji.get_random` | 宿主返回 `{"success":True,"emojis":[…]}` | **直接是列表** `[{"base64","description","emotion"}]` |

另外 **能力必须在 manifest 的 `capabilities` 里声明**，否则调用时抛
`RPCError: [E_CAPABILITY_DENIED] 插件 X 未获授权能力: emoji.get_random`（实测踩到）。
准确名字看 `src/plugin_runtime/capabilities/registry.py`（是 `emoji.delete`，不是 `delete_emoji`）。

**⚠️ 命令与闸门的优先级（踩过一次）**：宿主的命令匹配发生在
`chat.receive.after_process` **之后**（`bot.py:786` 调 hook、`:799` 才进命令链），
而闸门的"问好感度就直答"会 abort 掉整条消息 —— 于是「好感度 @某人 50」这类管理命令
会被答成"你在我这儿 N"、命令根本不执行。旧版不会：那时闸门在 POST_LLM 上，命令链先拦下消息。
修法是在闸门里用**原文**（不是 `clean()` 后的文本！`clean()` 会把空白全去掉，
判据永远不命中）先认一遍 `^(?:@<…>\s*)?/?(?:好感度|表现分)\s+\S`，命中就让路。
判据要**带参数**：光说「好感度」是查询，仍归闸门直答。

**abort 的写法（新版）**：handler 返回 `{"action": "abort"}`；
改 kwargs 返回 `{"action": "continue", "modified_kwargs": {...}}`
（`hook_dispatcher.py:587` 判 `execution_result.action == "abort"`，且只在该 hook `allow_abort` 时生效）。

**还没接**（下一步）

- ⬜ 表情包**删除**那条链在真实 QQ 上没验过（探针里是打桩的：要 QQ 真收到图再引用回复说「删掉」）
- ⬜ 里程碑 CG（好感度跨档位触发的 `_send_cg`）的**冷却 + 每日上限 + VLM 自检**那段没单独实测
  （画模式已实测，两者共用 `_fetch_cg_image` / `_cg_prompt` / `send_image_msg`）

## 参考

- 旧实现：`modules/MaiBot-0.11-backup/src/plugins/built_in/behavior_score/plugin.py`（2869 行，
  已提交为 `c0bd8ec8`）
- 能抄的样板：`src/plugins/built_in/plugin_management/plugin.py`（新格式，能正常加载）
- **不能抄**：`plugins/hello_world_plugin/plugin.py` —— 它用 `@EventHandler(ON_MESSAGE)`，
  是过期示范（能加载、收不到消息；它「未激活」还另有原因：`config.toml` 里 `enabled=false`）
