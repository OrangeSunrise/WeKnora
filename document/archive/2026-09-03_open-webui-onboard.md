# Open WebUI 项目上手与部署记录

## 任务目标

帮助新成员（lfloat）上手 open-webui 项目，理解项目架构和功能，并成功在本地部署启动应用。

## 项目概况

**Open WebUI** 是一个自托管的 AI 平台，功能丰富且可扩展，支持 Ollama 和 OpenAI 兼容的 API。

### 技术栈

- **前端**: SvelteKit (Svelte 5) + TypeScript + TailwindCSS
- **后端**: Python FastAPI + uvicorn ASGI 服务器
- **数据库**: SQLite（默认，嵌入式）+ ChromaDB（向量数据库，嵌入式）
- **AI 集成**: Ollama（本地）、OpenAI API、sentence-transformers（RAG）
- **包管理**: uv（Python）、fnm（Node.js 版本管理）、npm

### 环境要求

- Python 3.11（推荐）
- Node.js 22.23.2（根据 jianhui 最新排查记录）
- Ollama + qwen3:4b 模型
- Windows 11 环境

---

## 执行日志

| 时间       | 阶段         | 本次操作                                       | 状态 |
| ---------- | ------------ | ---------------------------------------------- | ---- |
| 2026-09-03 | 需求分析     | 初始化文档，确认任务目标，切换到 dev-jianhui 分支 | ✅    |
| 2026-09-03 | 环境准备     | 创建 Python 3.11 虚拟环境，安装 Node.js 22.23.2 | ✅    |
| 2026-09-03 | 环境准备     | 验证 Ollama 服务，下载 qwen3:4b 模型           | ✅    |
| 2026-09-03 | 后端部署     | 安装后端依赖（340+ 包），配置 .env 文件        | ✅    |
| 2026-09-03 | 后端部署     | 启动后端服务（端口 8080），验证健康检查        | ✅    |
| 2026-09-03 | 前端部署     | 安装前端依赖（1120 包），启动 Vite 开发服务器  | ✅    |
| 2026-09-03 | 功能验证     | 创建管理员账号，配置 Ollama 连接，测试对话功能 | ✅    |
| 2026-09-03 | 任务收尾     | 更新任务文档，标记所有验收标准为完成           | ✅    |

---

## 部署步骤详解

### Phase 1: 环境准备

#### 1.1 安装 Python 3.11 虚拟环境

使用 uv 工具创建 Python 3.11 虚拟环境（uv 会自动下载 Python 3.11）：

```powershell
cd D:\D_Code\open-webui\backend
uv venv --python 3.11
.\.venv\Scripts\Activate.ps1
python --version  # 验证：Python 3.11.x
```

#### 1.2 安装 Node.js 22.23.2

根据 `jianhui/node22安装排查记录.md` 的验证结果，使用 fnm 安装 Node.js 22.23.2：

```powershell
# 1. 安装 fnm
winget install Schniz.fnm

# 2. 配置 PowerShell Profile（一次性操作）
if (!(Test-Path $PROFILE)) { New-Item -Path $PROFILE -ItemType File -Force }
Add-Content $PROFILE "`nif (Get-Command fnm -ErrorAction SilentlyContinue) {`n    fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression`n}"

# 重新打开 PowerShell

# 3. 安装 Node.js 22（使用淘宝镜像）
$env:FNM_NODE_DIST_MIRROR = "https://npmmirror.com/mirrors/node/"
fnm install 22
fnm default 22
fnm use 22
node -v  # 验证：v22.23.2
```

**关键发现**：项目 package.json 要求 `engines: >=18.13.0 <=22.x.x`，Node.js 21 不符合此要求会导致 npm install 失败（EBADENGINE）。

#### 1.3 验证 Ollama

```powershell
ollama --version
curl http://localhost:11434/api/tags
ollama run qwen3:4b  # 首次运行会下载模型（约 2.3GB）
```

---

### Phase 2: 后端部署

#### 2.1 配置环境变量

```powershell
cd D:\D_Code\open-webui\backend

# 生成 64 位随机密钥并写入 .env
$key = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | ForEach-Object { [char]$_ })
if (Test-Path .env) { 
    Add-Content .env "`nWEBUI_SECRET_KEY=$key" 
} else { 
    Set-Content .env "WEBUI_SECRET_KEY=$key" 
}

# 设置 CORS（每次启动前需要设置）
$env:CORS_ALLOW_ORIGIN = "http://localhost:5173;http://localhost:8080"
```

**重要**: 直接使用 uvicorn 命令启动不会自动加载 .env 文件，需要手动设置 `WEBUI_SECRET_KEY` 环境变量。

#### 2.2 安装依赖并启动

```powershell
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装依赖（使用 Tuna 镜像，约 340 个包）
uv pip install -r requirements.txt

# 启动后端
uvicorn open_webui.main:app --port 8080 --host 0.0.0.0 --ws-per-message-deflate true --reload
```

**启动时序**：
1. 导入阶段（30-60 秒）：加载 torch/transformers/chromadb 等大包
2. 数据库初始化：创建 `backend/data/` 目录和 SQLite 文件 `webui.db`
3. ChromaDB 初始化：嵌入式向量库，本地存储文件
4. 预期警告：`Frontend build directory not found` - 正常，开发模式前端由 Vite 提供
5. 成功标志：`INFO: Uvicorn running on http://0.0.0.0:8080`

#### 2.3 验证后端

```powershell
# 健康检查
curl http://localhost:8080/health  # 应返回 {"status":true}

# Swagger 文档
start http://localhost:8080/docs
```

---

### Phase 3: 前端部署

```powershell
# 新开一个 PowerShell 窗口
cd D:\D_Code\open-webui

# 确认 Node.js 版本
node -v  # 应该是 v22.23.2

# 配置 npm 镜像（窗口级）
$env:npm_config_registry = "https://registry.npmmirror.com"

# 安装依赖
npm install  # 约 1120 个包

# 启动前端开发服务器
npm run dev
```

**验证前端**：浏览器打开 http://localhost:5173

---

### Phase 4: 首次配置

1. **访问应用**：打开 http://localhost:5173
2. **创建管理员账号**：首次访问会显示注册界面
3. **配置 Ollama 连接**：
   - 登录后进入设置
   - Ollama URL: `http://localhost:11434`
   - 选择 qwen3:4b 模型
4. **测试对话**：与 AI 模型进行测试对话，验证功能正常

---

## 关键问题与解决方案

### 问题 1：Node.js 版本冲突

**现象**：使用 Node.js 21 时，npm install 报错 EBADENGINE

**原因**：package.json 要求 `engines: >=18.13.0 <=22.x.x`，Node 21 不在此范围内。@sveltejs/vite-plugin-svelte@4.0.4 要求 `^18.0.0 || ^20.0.0 || >=22`。

**解决方案**：根据 jianhui 的 `node22安装排查记录.md`，升级到 Node.js 22.23.2（已验证可用）

### 问题 2：后端使用系统 Python 而非虚拟环境

**现象**：uvicorn 启动后提示 `ModuleNotFoundError: No module named 'aiohttp'`

**原因**：uvicorn 的子进程使用了系统 Python 3.13 而非虚拟环境的 Python 3.11

**解决方案**：确保虚拟环境已激活，验证 `which python` 和 `which uvicorn` 都指向 `.venv/Scripts/`

### 问题 3：WEBUI_SECRET_KEY 未加载

**现象**：后端启动报错 "WEBUI_SECRET_KEY is not set"

**原因**：直接运行 uvicorn 命令不会自动加载 .env 文件

**解决方案**：手动读取 .env 文件并设置环境变量：

```powershell
$envContent = Get-Content .env
foreach ($line in $envContent) {
    if ($line -match '^WEBUI_SECRET_KEY=(.+)$') {
        $env:WEBUI_SECRET_KEY = $matches[1]
        break
    }
}
```

### 问题 4：fnm 命令找不到

**现象**：PowerShell 中执行 `fnm` 显示无法识别

**原因**：fnm 安装后需要完全重启 PowerShell（不是关标签页）才能生效

**解决方案**：完全退出 PowerShell 或 VS Code，重新打开

---

## 验收结果

所有验收标准均已完成 ✅

### Phase 1: 环境准备
- ✅ Python 3.11 虚拟环境创建成功
- ✅ Node.js 切换到 v22.23.2
- ✅ Ollama 服务验证通过，qwen3:4b 可用

### Phase 2: 后端部署
- ✅ 后端依赖安装完成（340+ 包）
- ✅ backend/.env 文件创建并配置密钥
- ✅ 后端成功启动（Uvicorn running on 8080）
- ✅ 后端健康检查通过（/health 返回正常）
- ✅ Swagger 文档可访问（/docs）

### Phase 3: 前端部署
- ✅ 前端依赖安装完成（1120 包）
- ✅ 前端开发服务器启动成功（Vite running on 5173）
- ✅ 能在浏览器访问 localhost:5173

### Phase 4: 功能验证
- ✅ 看到 Open WebUI 注册/登录界面
- ✅ 成功创建管理员账号
- ✅ 成功登录系统
- ✅ Ollama 连接配置成功
- ✅ 能够与 qwen3:4b 模型正常对话

---

## 任务总结

**完成时间**：2026-09-03

**任务状态**：✅ 全部完成

**主要成果**：
1. 成功在本地环境部署 Open WebUI 应用
2. 前后端服务均正常运行
3. AI 对话功能验证通过
4. 记录了完整的部署流程和问题解决方案

**关键学习点**：
1. **Node.js 版本管理**：使用 fnm 管理多版本 Node.js，避免与系统版本冲突
2. **Python 虚拟环境**：使用 uv 工具创建隔离的 Python 环境，确保依赖版本正确
3. **环境变量配置**：理解 .env 文件加载机制，必要时手动设置环境变量
4. **后端启动特性**：首次启动需要 30-60 秒导入大型库，不下载 AI 模型
5. **文档价值**：jianhui 的排查记录提供了关键的版本信息和避坑指南

**下一步建议**：
1. 熟悉 Open WebUI 界面和功能
2. 探索 RAG（知识库）功能
3. 尝试不同的 AI 模型和参数配置
4. 阅读源码理解项目架构

---

**文档版本**：v1.0  
**最后更新**：2026-09-03
