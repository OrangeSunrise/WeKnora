# WeKnora Lite 原生 Windows 部署说明

> 适用范围：在 Windows 10 及以上系统上，不使用 Docker 与 WSL2，以原生方式构建并运行
> WeKnora Lite 单二进制服务，完成知识库问答的最小可用部署。
>
> 目标读者：需在本机复现该部署的团队成员。
>
> 基线版本：WeKnora v0.8.0，仓库 `https://github.com/OrangeSunrise/WeKnora.git`，
> 上游 `https://github.com/Tencent/WeKnora.git`。

---

## 一、部署形态说明

WeKnora 官方提供两种部署形态。标准形态依赖 PostgreSQL、Redis、docreader 等五个服务，
通过 Docker Compose 编排；Lite 形态将上述依赖全部内置于单个可执行文件，使用 SQLite
承担关系存储与向量检索，使用进程内队列替代 Redis，使用本地文件系统承担对象存储。

本部署采用 Lite 形态并在原生 Windows 上构建运行，不使用 Docker，也不使用 WSL2。
相应的能力取舍如下：

| 项目 | 标准形态 | 本部署 |
|---|---|---|
| 关系存储 | PostgreSQL | SQLite |
| 向量检索 | ParadeDB | sqlite-vec 的 `vec0` 虚拟表 |
| 全文检索 | PostgreSQL 全文索引 | SQLite FTS5 bigram 分词 |
| 任务队列 | Redis + asynq | 进程内队列 |
| 文档解析 | docreader 服务，支持 PDF 等格式 | 内置 Simple 解析器，不支持 PDF |
| 重排序 | 可接入 rerank 服务 | 本部署不启用 |

其中文档解析能力的差异对后续工作构成实际约束，详见第九章已知限制。

## 二、前置条件

1. 操作系统为 Windows 10 专业版及以上，可用内存 16GB 及以上。
2. 已安装 scoop 包管理器，用于以用户级权限安装工具链，避免管理员权限依赖。
3. 已安装 Ollama 并可正常运行，用于提供本地大语言模型与嵌入模型。
4. 已安装 Node.js 22，用于构建前端静态资源。
5. 具备 Git 环境。文档中的命令在 Git Bash 中执行。

## 三、获取仓库

执行全深度克隆，不使用浅克隆，以保证后续可与上游同步：

```bash
git clone https://github.com/OrangeSunrise/WeKnora.git D:/D_Code/WeKnora
cd /d/D_Code/WeKnora
git remote add upstream https://github.com/Tencent/WeKnora.git
git fetch upstream
```

克隆完成后核对基线，`git rev-list --count HEAD` 应远大于 1，且 `.git/shallow`
文件不存在。

## 四、安装构建工具链

通过 scoop 安装 Go 与 mingw-w64 编译器：

```bash
scoop install go
scoop install mingw
```

安装完成后执行 `gcc --version` 确认版本。本部署实测通过的版本为 gcc 16.1.0，
线程模型为 posix-seh。由于 Lite 形态需要通过 cgo 编译 SQLite 相关的 C 代码，
mingw-w64 是必需组件，不可省略。

## 五、准备构建依赖

原生 Windows 构建存在三处阻塞，均须在编译前处理完毕。

### 5.1 提供 sqlite3.h 头文件

sqlite-vec 模块以 `-DSQLITE_CORE` 方式编译，要求系统 include 路径中存在
`sqlite3.h`，而该模块自身仅携带 `sqlite-vec.c` 与 `sqlite-vec.h`。解决方式为从
`mattn/go-sqlite3` 的 amalgamation 中取出头文件，暂存至 `.build/include`：

```bash
mkdir -p .build/include
GOSQLITE=$(go env GOMODCACHE)/github.com/mattn/go-sqlite3@*/
cp $GOSQLITE/sqlite3-binding.h .build/include/sqlite3.h
cp $GOSQLITE/sqlite3-binding.h .build/include/
cp $GOSQLITE/sqlite3ext.h .build/include/
```

头文件版本必须与实际链接的 SQLite 版本精确一致，本部署对应 SQLite 3.46.1。

### 5.2 以动态方式链接 DuckDB

DuckDB 的预编译静态库要求 emulated-TLS 版本的 libstdc++，与 mingw-w64 16.1.0 的
native TLS ABI 不匹配，直接编译会出现 `__emutls_v._ZSt11__once_call` 未定义的
链接错误。由于 DuckDB 在代码中被无条件导入，无法通过裁剪依赖规避，须改用动态链接。

下载 DuckDB v1.5.2 的 Windows 版本，将文件置于 `.build/duckdb`，并将导入库
复制为 mingw 可识别的命名：

```bash
mkdir -p .build/duckdb
# 将官方发布包中的 duckdb.dll、duckdb.h、duckdb.hpp、duckdb.lib 放入该目录
cp .build/duckdb/duckdb.lib .build/duckdb/libduckdb.dll.a
```

编译时通过 `-tags duckdb_use_lib` 启用动态链接模式。

### 5.3 静态链接 C++ 运行时

gojieba 分词库在 `internal/types` 包的 init 阶段会触发
`Exception 0xc0000005` 访问违例，原因是系统 PATH 中存在版本不匹配的
`libstdc++-6.dll`。解决方式为在链接时静态引入 C++ 与 GCC 运行时：

```
-static-libstdc++ -static-libgcc
```

不可使用完整的 `-static` 参数，否则 DuckDB 的导入库将失效。

## 六、编译后端

在仓库根目录执行：

```bash
export CGO_ENABLED=1
export CGO_CFLAGS="-I$(pwd)/.build/include"
export CGO_LDFLAGS="-L$(pwd)/.build/duckdb -lduckdb -static-libstdc++ -static-libgcc"

go build \
  -tags "sqlite_fts5 duckdb_use_lib" \
  -ldflags "-s -w -X github.com/Tencent/WeKnora/internal/handler.Edition=lite" \
  -o WeKnora-lite.exe ./cmd/server
```

各参数的作用说明如下：

- `sqlite_fts5` 启用 SQLite 的 FTS5 全文检索扩展，Lite 形态的关键词检索依赖该扩展。
- `duckdb_use_lib` 使 duckdb-go-bindings 走动态链接，配合第 5.2 节的导入库。
- `-X ...handler.Edition=lite` 将版本标识置为 lite。该标识不可省略，
  若保持默认值 standard，`internal/router/static.go` 的 `serveFrontendStatic`
  不会挂载，前端请求会落入 API 路由并返回 401；同时 `/auth/auto-setup`
  免密初始化接口也不会生效。
- `-s -w` 去除符号表与调试信息，产物体积约 217MB。

编译成功后，`WeKnora-lite.exe` 将生成于仓库根目录。

## 七、构建前端

前端须使用 Node 22 单独构建，产物拷入 `web/` 目录由后端静态托管。

需要注意的是，在 Windows 上通过 `fnm exec --using=22 npm ci` 调用会报
"Can't spawn program" 错误，原因是 npm 在 Windows 上是 `.cmd` 形式的包装脚本，
无法由 fnm 直接派生。因此须直接使用 `node.exe` 调用绝对路径的 `npm-cli.js`：

```bash
NODE22="$HOME/.fnm/node-versions/v22.x.x/installation"
cd frontend
"$NODE22/node.exe" "$NODE22/node_modules/npm/bin/npm-cli.js" ci
"$NODE22/node.exe" "$NODE22/node_modules/npm/bin/npm-cli.js" run build
cd ..
cp -r frontend/dist/* web/
```

其中 `v22.x.x` 需替换为实际安装的版本号。

## 八、配置环境变量

由 `.env.lite.example` 复制出 `.env.lite`：

```bash
cp .env.lite.example .env.lite
```

该文件已被 `.gitignore` 第 2 行的 `.*` 规则排除，可执行
`git check-ignore -v .env.lite` 验证不会被提交。

### 8.1 替换密钥默认值

上游示例文件中的以下两项为不安全默认值，首次启动前必须替换：

| 变量 | 上游默认值 | 要求 |
|---|---|---|
| `JWT_SECRET` | `weknora-jwt-secret` | 替换为随机字符串 |
| `SYSTEM_AES_KEY` | `weknora-system-aes-key-32bytes!!` | 替换为 32 字节随机字符串 |

替换顺序至关重要。`SYSTEM_AES_KEY` 用于加密存储模型凭据，若先以默认密钥启动并录入
过模型配置，之后再更换密钥将导致已加密数据无法解密，只能清空数据库重新部署。因此
须在首次启动之前完成替换。

`SYSTEM_AES_KEY` 一旦丢失，所有已加密凭据均不可恢复。该密钥须备份至团队约定的密钥
保管位置，并在交付记录中登记保管位置，不得登记密钥本身。

### 8.2 补充 SSRF 白名单

`.env.lite.example` 自带 `OLLAMA_BASE_URL=http://127.0.0.1:11434`，但未将该地址
加入 SSRF 白名单。若不补充，模型初始化会因回环地址被拦截而报
"hostname 127.0.0.1 is restricted"。该项属上游配置缺口，须在 `.env.lite` 中补充：

```
SSRF_WHITELIST_EXTRA=127.0.0.1
```

### 8.3 确认 Lite 相关配置项

确认以下各项与 Lite 形态一致：

```
DB_DRIVER=sqlite
DB_PATH=./data/weknora.db
RETRIEVE_DRIVER=sqlite
STREAM_MANAGER_TYPE=memory
STORAGE_TYPE=local
```

仓库中另有一份 `.env` 文件，其内容对应标准形态，`DB_DRIVER` 为 postgres、
`STREAM_MANAGER_TYPE` 为 redis。该文件不适用于本部署，须确保未被误加载。

## 九、启动服务

`cmd/server` 入口不会自动加载 dotenv 文件，须先将 `.env.lite` 导入当前 shell
环境变量，再启动可执行文件：

```bash
cd /d/D_Code/WeKnora
set -a && . ./.env.lite && set +a
./WeKnora-lite.exe
```

命令行窗口需保留，若关闭窗口则服务停止。

启动完成后通过健康检查接口确认：

```bash
curl -s http://127.0.0.1:8080/health
```

返回 `{"status":"ok"}` 即表示启动成功。此时后端注册的 gin 路由为 429 条，
SQLite、sqlite-vec 与 FTS5 bigram 检索均已就绪。

服务默认监听 `0.0.0.0:8080`，监听地址在 `config/config.yaml` 第 3 至 4 行配置。
若仅需本机访问，建议改为 `127.0.0.1` 以缩小暴露面。

## 十、接入本地模型

### 10.1 拉取模型

```bash
ollama pull qwen2.5:7b-instruct
ollama pull bge-m3
```

嵌入模型必须为 1024 维。`bge-m3` 输出 1024 维向量，与向量表
`vec_embeddings_1024` 的维度约定一致，距离度量为余弦距离。维度一旦与向量表不匹配，
需重建索引并重新导入全部文档，因此须在录入任何文档之前确认。

生成模型选用 `qwen2.5:7b-instruct`，不使用 `qwen3:4b`。原因在于 qwen3:4b 不遵守
提示词中"直接输出总结正文"的要求，会将推理过程写入文档摘要正文，该摘要经索引后
参与检索，进而干扰问答生成结果。相关分析见第十一章。

### 10.2 创建模型记录

不要使用 `/initialization/initialize` 接口创建模型。该接口创建出的模型记录
`tenant_id` 为 0，而 `modelRepository.GetByID` 按
`(tenant_id = ? OR is_builtin = true)` 过滤，导致模型对当前租户不可见，表现为
`GET /models` 返回空列表、`GET /models/{id}` 返回 404。根本原因是
`initialization.go` 的 `toModel()` 与 `modelService.CreateModel` 均未设置
TenantID 字段。

应改用以下两步：

1. 通过 `POST /api/v1/models` 创建模型。该 handler 从请求上下文取 TenantID，
   记录归属正确。
2. 通过 `PUT /initialization/config/{kbId}` 将模型绑定至知识库。

### 10.3 请求编码注意事项

在 Windows 的 Git Bash 中，命令行参数中的中文会按 ANSI 代码页传入 argv，
导致 curl 发出的内容不是合法 UTF-8。该问题会造成两类故障：中文文件名上传被
`internal/utils/security.go` 的 `ValidateInput` 拒为"文件名包含非法字符"；
以及内联中文的 JSON 请求体写入数据库后成为乱码且不可逆。

因此所有包含中文的请求须采用以下两种方式之一：使用 Python 的 requests 库以
显式 UTF-8 编码发送；或先将 JSON 写入文件，再通过 `curl -d @文件名` 发送。

## 十一、登录与知识库创建

### 11.1 登录方式

Lite 形态提供 `/auth/auto-setup` 接口，用于免密初始化。该接口在
`internal/handler/auth.go` 中实现，仅当版本标识为 lite 时生效。首次访问前端时，
`frontend/src/router/index.ts` 会自动调用该接口完成登录，因此浏览器直接打开
`http://127.0.0.1:8080` 即可进入系统，无需注册与输入密码。

默认账号为 `admin@weknora.local`。该接口生成的随机密码不会返回给调用方，
因此无法通过邮箱与密码方式登录，只能使用自动登录。

### 11.2 创建知识库与导入文档

创建知识库时须绑定第 10.2 节创建的嵌入模型与生成模型。分块参数采用
块大小 512、重叠 64。

导入文档后，通过以下字段确认处理结果：

| 字段 | 期望值 | 含义 |
|---|---|---|
| `parse_status` | `completed` | 解析与分块完成 |
| `summary_status` | `completed` | 文档摘要生成完成 |
| `enable_status` | `enabled` | 该文档参与检索 |

批量导入时，`summary_status` 可能短暂出现 `failed`。这属于可重试的中间状态，
`knowledge_process.go` 的 `handleRetryableSummaryFailure` 会重新排队，
后续将自行转为 `completed`，无需人工干预。

`CONCURRENCY_POOL_SIZE` 默认为 3，即三个摘要任务并发请求 Ollama。在单机运行 7B
模型的条件下，该并发度会引发请求超时并触发重试，导致导入耗时延长。若批量导入规模
较大，可将该值调低以减少重试开销。调整该值需重启服务，而服务启动时
`internal/container/reset_pending_tasks.go` 会将处于等待状态的任务标记为失败，
因此不可在导入过程中重启。

### 11.3 端到端验证

就已导入文档提问，确认回答满足以下各项：

1. 回答内容取自检索到的文档，未出现无关内容。
2. 回答中出现行内引用标记，格式为
   `<kb doc="文档名" chunk_id="分块标识" kb_id="知识库标识" />`。
3. 服务端事件流中包含 `references` 数组，其中列出被引用的分块及其相关度分值。
4. 点击引用标记可展开引用浮层，并显示对应分块原文。
5. 提出知识库中无答案的问题时，系统明确说明无法回答，而非编造内容。

事件流按 `response_type` 区分类型，包括 `agent_query`、`tool_call`、`tool_result`、
`references`、`thinking`、`answer`、`complete`。客户端须按类型分别处理，
不可将全部事件的 `content` 直接拼接，否则会把推理过程混入答案正文。

## 十二、已知限制

### 12.1 不支持 PDF 解析

Lite 形态使用内置的 Simple 解析器，`internal/.../builtin_converter.go` 中的
`simpleFormats` 不包含 pdf 格式。因此 PDF 文档无法直接导入。若需处理 PDF 手册，
须另行确认 docreader 服务能否在本部署形态下单独启用。

### 12.2 摘要分块参与检索且不可关闭

文档导入后，除正文分块外还会生成一个类型为 summary 的分块并写入向量索引，
该行为在 `knowledge_process.go` 中无条件执行，配置层没有开关。该分块参与检索，
但不会出现在 `GET /chunks/{knowledgeID}` 的返回结果中，因为该接口仅列出文本分块。

由此产生两点影响。其一，检索结果的首位可能是摘要分块而非正文分块，
在与仅基于正文分块的检索基线对比时，指标不具可比性，须在评测环节取更大的 K 值
并仅在正文分块上计算指标。其二，摘要质量直接影响问答质量，若摘要模型将推理过程
写入摘要正文，该内容会经检索进入问答上下文并干扰生成结果。

`knowledge_bases.summary_model_id` 字段不能通过置空来关闭摘要生成。
`session_knowledge_qa.go` 的模型选择优先级中，第四顺位为第一个知识库的
`SummaryModelID`。当会话自身未指定模型时，问答生成模型正是由该字段解析得出，
置空将导致问答无可用模型。

### 12.3 答案中的图片引用

`config/prompt_templates/system_prompt.yaml` 中 `default_kb` 模板原本要求最终答案
必须包含至少一张来自检索内容的图片。该要求适用于文档经视觉模型解析、分块自带图片
地址的场景。当知识库为纯文本且不启用视觉模型时，检索内容中不存在任何图片，
该要求与同一模板中"不得编造"的约束冲突，模型会构造不存在的图片地址，
前端渲染后表现为图片加载失败。

本部署已将该要求调整为条件性，即仅当检索内容包含图片时才输出图片，
并显式禁止构造图片地址。提示词模板由 `internal/config/config.go` 在服务启动时从
`config/prompt_templates` 目录读取，并非编译期嵌入，因此修改模板后重启服务即生效，
无需重新编译。

### 12.4 数据库中的无效模型记录

若曾调用 `/initialization/initialize` 创建模型，数据库中会残留 `tenant_id` 为 0 的
模型记录。这些记录通过 API 不可见也不可用，不影响运行，可暂不处理。

## 十三、故障排查

| 现象 | 原因 | 处理方式 |
|---|---|---|
| 编译报 `sqlite3.h: No such file` | sqlite-vec 以 `-DSQLITE_CORE` 编译，需系统 include 路径提供该头文件 | 按第 5.1 节准备头文件并设置 `CGO_CFLAGS` |
| 链接报 `__emutls_v._ZSt11__once_call` 未定义 | DuckDB 预编译静态库与 mingw 的 TLS ABI 不匹配 | 按第 5.2 节改用动态链接 |
| 启动即报 `Exception 0xc0000005` | PATH 中存在版本不匹配的 `libstdc++-6.dll`，gojieba 在 init 阶段崩溃 | 按第 5.3 节静态链接 C++ 运行时 |
| 前端页面请求返回 401 | 未设置 `EDITION=lite` 的 ldflag，静态资源未挂载 | 按第六章补充 ldflag 后重新编译 |
| 前端构建报 `Can't spawn program` | npm 在 Windows 上为 `.cmd` 包装脚本，fnm 无法直接派生 | 按第七章直接调用 `node.exe` 与 `npm-cli.js` |
| 模型初始化报 `hostname 127.0.0.1 is restricted` | SSRF 校验拦截回环地址 | 按第 8.2 节补充 `SSRF_WHITELIST_EXTRA` |
| `GET /models` 返回空、`GET /models/{id}` 返回 404 | 模型记录 `tenant_id` 为 0，对租户不可见 | 按第 10.2 节改用 `POST /api/v1/models` 创建 |
| 上传中文文件名报"文件名包含非法字符" | Git Bash 按 ANSI 代码页传递 argv | 按第 10.3 节改用 Python requests 上传 |
| 知识库名称显示为乱码 | 同上，内联中文的 JSON 请求体编码错误 | 该数据不可逆，须通过接口重新写入正确值 |
| 答案中出现加载失败的图片 | 提示词模板要求必须包含图片，而纯文本知识库无图片可用 | 按第 12.3 节调整模板并重启服务 |
| 批量导入时 `summary_status` 大量为 `failed` | 摘要任务积压期间的可重试中间状态 | 等待队列消化，无需处理。可参照第 11.2 节调低并发度 |
| 答案中混入模型的推理过程 | 客户端将全部事件的 `content` 直接拼接 | 按第 11.3 节按 `response_type` 分类处理 |

## 十四、待确认事项

以下各项尚未处理，须在正式使用前确认：

1. 服务监听地址是否由 `0.0.0.0:8080` 收窄为 `127.0.0.1:8080`。
2. `SYSTEM_AES_KEY` 的备份是否完成，保管位置是否已在交付记录中登记。
3. 若曾为其他部署方案配置 Docker Desktop 代理或设置 `OLLAMA_HOST` 环境变量，
   须确认是否需要恢复原值。
4. PDF 手册的解析路径尚未确定，见第 12.1 节。

