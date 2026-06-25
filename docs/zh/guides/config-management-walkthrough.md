# 配置管理手动体验指南

ContextSeek 的配置管理提供**版本化、可溯源、可回退**的配置托管，并支持把 agentseek 的配置纳入并投影。本文用一条完整的手动体验路径带你走一遍：从首次接入、修改、溯源、回退，到 agentseek 摄入和 dashboard 操作。

## 前置概念

- **托管库**：版本化配置的权威源，固定路径 `${CONTEXTSEEK_HOME:-.contextseek}/config/`，不依赖存储后端。
- **三层配置**：
  - `native` —— ContextSeek 自有配置（你主动设的）。
  - `projected` —— 从 agentseek 投影而来的配置（agentseek 是上游，只读投影，不反写）。
  - `effective` —— 合并后的生效配置（`projected` 作基线，`native` 显式设值的 key 覆盖）。物化器把这一层写成 `.env` 和 `config.json`。
- **append-only 历史**：每次改动新建一个版本，历史永不删除。回退也是新建一个等于旧版本 payload 的新版本。
- **物化（apply）**：把 `effective` 写成现有加载器已经会读的 `.env`（喂 `ContextSeekSettings`）和 `config.json`（喂 `load_runtime_config`）。

## 目录布局

```
.contextseek/config/
├── current.json          # 当前生效配置（权威源）
├── history/
│   └── v000001.json      # 每个版本一个完整快照 + 溯源元数据
├── manifest.jsonl        # append-only 版本索引（hash 链）
└── sources/              # 外部源快照（如 agentseek）
```

## 0. 准备

本文示例用一个隔离的 `CONTEXTSEEK_HOME`，避免污染你本机已有配置：

```bash
export CONTEXTSEEK_HOME=/tmp/ctx-demo
cd /tmp/ctx-demo            # .env / config.json 会物化到当前目录
```

所有命令形如 `contextseek config <子命令>`。若直接用源码运行，替换为 `uv run contextseek config ...` 或 `python -m contextseek.cli.main config ...`。

## 1. 首次接入：迁移现有配置

如果已有 `.env` / `config.json`，先迁移进托管库，生成 `v000001`（`origin=migration`）：

```bash
contextseek config import --from-env .env --from-runtime config.json --apply
```

- `import` 把 `.env` 里能反演成 settings 字段的 key 写进 `native`，无法反演的 key 放进 `native._extra_env`（物化时原样写回，**不丢任何 key**）。
- `--apply` 同时物化一次。
- 库已非空时 `import` 是 no-op（返回 "nothing to import"）。

> 没有现成配置也能直接开始——下一步 `set` 会自动创建第一个版本。

## 2. 修改配置（每次改动都是一个版本）

`set` 用点分路径修改 `native` 单项，默认产生新版本并物化：

```bash
contextseek config set llm.model gpt-4o --reason "切换到 gpt-4o"
contextseek config set llm.provider openai --reason "启用 openai"
contextseek config set retrieval.default_k 20 --reason "扩大召回"
```

常用路径（节.字段）：

| 路径 | 对应 env |
|---|---|
| `storage.backend` | `STORAGE_BACKEND`（memory/file/sqlite/seekdb/oceanbase） |
| `llm.provider` / `llm.model` / `llm.base_url` | `LLM_PROVIDER` / `LLM_MODEL` / `LLM_BASE_URL` |
| `llm.kwargs.api_key` | `LLM_KWARGS` 里的 `api_key`（JSON） |
| `embedding.provider` / `embedding.model` | `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` |
| `retrieval.default_k` | `RETRIEVAL_DEFAULT_K` |
| `ob.host` / `ob.port` / `ob.db_name` | `OB_HOST` / `OB_PORT` / `OB_DB_NAME` |

只想暂存到版本库、**先不物化**到 `.env`（比如攒一批再一起生效）：

```bash
contextseek config set llm.model gpt-4o --no-apply
# ... 攒够后统一物化
contextseek config apply
```

物化前会做 **dry-run 校验**：用 `ContextSeekSettings` / `RuntimeConfig` 实际构造一遍 + 校验 storage backend 白名单。校验失败则**不写任何文件**，保留上一次生效配置：

```bash
contextseek config set storage.backend not-a-real-backend
# → 物化时报错：unsupported storage backend: not-a-real-backend
# → .env / config.json 保持不变
```

## 3. 查看与溯源

```bash
# 当前生效配置
contextseek config show

# 指定版本 / 指定层
contextseek config show --version v000002
contextseek config show --layer native        # 或 projected / effective

# 版本链（最新在上）
contextseek config history
contextseek config history -n 5

# 两个版本的差异
contextseek config diff v000001 v000003

# 某个 key 最后一次是谁、在哪个版本改的
contextseek config blame llm.model
```

`blame` 返回该 key 最近一次变更的 `version_id` / `origin` / `author` / `reason` / `source_ref` / `value`，直接定位到那一次提交。

## 4. 回退与 redo

回退是 **append-only**：以指定版本的 payload 新建一个版本，历史不丢：

```bash
contextseek config history
# v000003  ...  manual  cli  切换到 gpt-4o
# v000002  ...  manual  cli  启用 openai
# v000001  ...  migration system migrate existing config

contextseek config rollback v000001 --reason "回到初始迁移状态"
# → 产生 v000004 (origin=rollback)，并物化
```

刚回退了想撤销？`redo` 把最近一次 rollback 撤回（同样会物化）：

```bash
contextseek config redo --reason "撤销刚才的回退"
```

`redo` 只在「最近一个版本是 rollback」时生效，否则提示 "nothing to redo"。

## 5. 完整性校验与漂移检测

```bash
# 校验 hash 链 + parent 链 + current.json 一致性（篡改可发现）
contextseek config verify
# → OK

# 当前版本号、物化文件是否被人手改过（漂移）、agentseek 源是否过期
contextseek config status
```

如果有人手改了物化后的 `.env`，`status` 会报 `drift.env=true`，提示你 `config apply` 重物化或用 `config set` 正式纳入版本库。

## 6. 接受 agentseek 配置（纳入 + 投影）

agentseek 仍是上游自主配置，ContextSeek 只读 + 投影 + 溯源，**不反写**。

把 agentseek 的配置文件（`.env` 风格 `KEY=value`）摄入并投影：

```bash
contextseek config ingest agentseek --path /path/to/agentseek.env --apply
```

发生的事：
- 读取 agentseek 配置，按映射表投影成 `projected` 层（如 `AGENTSEEK_API_KEY`→`llm.kwargs.api_key`、`AGENTSEEK_MODEL`→`llm.model`）。
- 产生一个 `origin=agentseek-projection` 版本，`source_ref` 记录源 hash。
- **幂等**：同一源（同 hash）再次摄入不产生新版本。
- `--apply` 物化合并后的 `effective`。

不指定 `--path` 时从进程环境变量 `AGENTSEEK_*` / `AGENTSEEK_CTX_*` 摄入：

```bash
contextseek config ingest agentseek --apply
```

投影后，`show --layer projected` 能看到 agentseek 投影过来的值，`show --layer effective` 看到合并结果。若 `native` 显式设了同 key，`native` 优先（`blame` / `status` 会标出 `override_source`）。

## 7. Dashboard 体验

启动 dashboard（HTTP 服务同时提供配置管理端点）后，打开 **Settings 面板**：

- **编辑区**：照常改 LLM / Embedding / Storage 等字段，保存即通过版本化 API 提交，每次编辑成为一个版本（`author=dashboard`）。
- **版本历史区**（编辑区下方）：
  - 版本链列表（版本号 / 时间 / origin / author / reason）。
  - 当前版本徽章；**drift** 徽章（`.env` 被手改时变红）。
  - 每行可展开看版本元数据；非当前版本有「回退」按钮。
  - 顶部「摄入 agentseek」按钮触发投影。
- **override 徽章**：每个配置项旁标注来源（`native` / `projected:agentseek`），冲突项一目了然。

API 层（供前端或脚本调用）：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/config` | 当前生效配置 + 版本/override/drift/agentseek 元数据（懒迁移） |
| PUT | `/config` | 编辑（重路由走 ConfigManager，返回 `version_id`） |
| POST | `/config/test` | 测试连接（不变） |
| GET | `/config/history` | 版本链 |
| GET | `/config/version/{id}?layer=` | 某版本某层 |
| GET | `/config/diff?a=&b=` | 两版本 diff |
| GET | `/config/blame?key=` | 某 key 溯源 |
| POST | `/config/rollback` | 回退 + 物化 |
| POST | `/config/redo` | 撤销回退 + 物化 |
| GET | `/config/status` | 版本/漂移/过期/verify |
| GET | `/config/verify` | 完整性校验 |
| POST | `/config/ingest/agentseek` | 摄入投影 |

> `GET /config` / `PUT /config` 在托管库为空时会**懒迁移**（自动 `import` 现有 `.env`/`config.json` 为 v1），所以 dashboard 首次打开即纳入版本化，无需手动 `import`。

## 8. 一条完整的体验串

```bash
export CONTEXTSEEK_HOME=/tmp/ctx-demo && cd /tmp/ctx-demo

# 迁移（或直接 set 跳过）
contextseek config import --from-env .env --apply

# 改两笔
contextseek config set llm.model gpt-4o --reason "用 gpt-4o"
contextseek config set retrieval.default_k 30 --reason "扩召回"

# 看历史、看谁改的
contextseek config history
contextseek config blame retrieval.default_k

# 回退到迁移版本，再 redo 撤回
contextseek config rollback v000001 --reason "回到初始"
contextseek config redo --reason "撤销回退"

# 摄入 agentseek（假设有该文件）
contextseek config ingest agentseek --path agentseek.env --apply
contextseek config show --layer projected     # 看 agentseek 投影

# 校验 + 状态
contextseek config verify
contextseek config status
```

## 9. 已知限制（后续优化项）

- **`build_adapter`（daemon 侧 RuntimeConfig）只支持 memory/file/oceanbase**；`dry_run_validate` 的 backend 白名单则接受 sqlite/seekdb（SDK/`ContextSeekSettings` 侧支持）。daemon 路径用 sqlite/seekdb 时物化可通过、但 `build_adapter` 后续会报错——这是预存的架构不一致，配置管理只是暴露了它。
- **CLI `config import` 不带 `--from-env`/`--from-runtime` 时跳过该路径**（生成空 v1）。帮助文本里的 "default: resolved .env" 是计划措辞；要导入请显式传路径，或依赖 dashboard 的懒迁移。
- **dashboard 版本历史的「diff」按钮**目前展示版本元数据预览，尚未渲染字段级 diff（`getConfigDiff` API 已就绪，UI 待接入）。
- **dashboard 部分标签**（如 drift 徽章）为硬编码英文，未走 i18n。
