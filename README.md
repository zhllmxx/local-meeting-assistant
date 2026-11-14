# Local Meeting Assistant / 本地会议助理

一个以低成本语音转写为基础的 macOS 中文近实时问答工作台：采集会议系统音频，本地分段后交给豆包 ASR 转写，再由文本 LLM 同时提供 API 快答和 Pydantic AI Agent 资料查证答案。

## 功能

- **语音与回答分开计费**：音频交给专用 ASR，问题和资料交给文本 LLM；分别控制识别时长、文本上下文与 Agent 调用量，以降低持续会议辅助的使用成本。
- **双路并行**：API 和 Agent 各自排队、流式显示，慢 Agent 不阻塞后续 API 问题，新问题不取消已有回答。
- **查阅当前文件**：Agent 可搜索与读取允许的项目资料、源码和 PDF，显示工具进度与文件依据。
- **Go 面试规则**：通用基础题按 Go 语义回答，算法题给 Go 实现、复杂度与边界条件；具体项目问题先核实材料。
- **扬声器单人模式**：系统音频中只有对方发言时，800ms 静音形成一个 query；通用采集支持麦克风和人工编排。
- **可检查的音频链路**：实时电平、ASR 预览、原声播放、独立首字与完成耗时。
- **本地会话管理**：问答倒序展示、可编辑、可清空；完成结果可在服务重启后恢复。

音频采集和会话存储在本机。音频会发送给豆包 ASR，问题及相关资料会发送给配置的 LLM 服务。当前方案使用云端推理，详见 [PRIVACY.md](PRIVACY.md)。

## 语音识别与成本

本项目采用“系统音频 → 本地分段 → 豆包 ASR → 文本 LLM”的路线。检测到发言后，在 800ms 静音时提交完整片段；已录下的音频快速上传，无需按原始播放速度重传。语音识别和文本回答可以分别选择服务与预算，适合希望以较低成本获得近实时问答的场景。

当前默认接口是 `bigmodel_async`，资源 ID 为 `volc.seedasr.sauc.duration`。按[豆包官方文档](https://www.volcengine.com/docs/6561/1354869)，它属于双向流式语音识别的小时版；请求中的 `enable_nonstream=true` 是识别选项，不表示使用了录音文件识别产品，也不表示本地离线推理。

费用需要合并计算 ASR 提交的音频时长、API 和 Agent 两路的文本 token，以及 Agent 查证产生的额外模型轮次。当前转写预览会重复识别部分音频，因此提交时长可能超过实际发言时长。与 Gemini Live 等实时多模态服务的具体价差，应按同等会议时长、功能和当期套餐核算；这里不承诺固定节省比例。

## 支持范围

当前验证环境为 **macOS 26+、Apple Silicon、Python 3.11、Node.js 20+**。需要 Xcode/Command Line Tools 提供 Swift 和 macOS SDK。扬声器单人模式由 ScreenCaptureKit 原生输出 ASR 所需的 PCM，不需要 FFmpeg；普通设备采集、麦克风混音和 CoreAudio Tap 兼容路线仍可使用 FFmpeg。系统音频路线不需要 BlackHole，不修改系统默认扬声器，也不调用会议软件接口。

这是早期版本，尚未验证 Windows/Linux、Intel Mac 或更低版本 macOS。ScreenCaptureKit 采集期间的系统提示图标由 macOS 管理。

## 快速开始

在项目目录中安装运行依赖：

```sh
brew install python@3.11 node
python3.11 -m venv .venv-app
.venv-app/bin/python -m pip install -r requirements.txt
npm ci
npm run build:web
cp config.example.json config.local.json
chmod 600 config.local.json
mkdir -p secrets materials
```

编辑 **config.local.json**（Git 已忽略）：

- `MEETING_CONTEXT_ROOT`：资料根目录，默认 `materials`；可以指向本机其他目录。
- `MEETING_SOURCE_DIRS`：Agent 允许递归读取的子目录，默认 `docs`、`projects`。
- `MEETING_EXTRA_FILES`：额外允许的文件，相对于资料根目录。
- `MEETING_KNOWLEDGE_SOURCES`：API 快答使用的资料，例如 `[["简历", "resume.pdf"], ["面经", "interview.md"]]`。未设置时读取资料根目录的 Markdown、文本及 PDF。
- `HUOSHAN_CONFIG`：LLM 配置文件，默认 `secrets/huoshan.json`。
- `DOUBAO_ASR_KEY_FILE`：豆包 ASR key 文件，默认 `secrets/doubao_asr.key`。

将 ASR key 写入指定文件。在 LLM 配置文件中填写自己的服务地址和 key：

```json
{
  "url": "https://ark.cn-beijing.volces.com/api/v3",
  "key": "REPLACE_WITH_YOUR_LLM_API_KEY"
}
```

两路默认使用 `doubao-seed-2-1-pro-260915`，显式关闭 thinking。请先确认你的账户有该模型权限；可通过 `HUOSHAN_MODEL` 修改模型或推理接入点 ID。ASR 的 URL 和资源 ID 可通过 `DOUBAO_ASR_URL`、`DOUBAO_ASR_RESOURCE_ID` 配置。

所有配置均可用同名环境变量覆盖。相对文件路径基于项目目录；资料目录/额外文件必须位于资料根目录下。数组型环境变量使用 JSON 数组。若使用普通设备、麦克风混音或 CoreAudio Tap 兼容路线，再安装 `ffmpeg`；扬声器单人模式不需要它。

先以前台方式启动：

```sh
.venv-app/bin/python app.py --host 127.0.0.1 --port 8766
```

打开 <http://127.0.0.1:8766>，按 macOS 提示授予所需音频/屏幕录制权限，选择设备后点“开始采集”。Swift 音频辅助程序在首次使用时编译。`examples/reference.md` 是可用于试运行的虚构资料。

安装为当前用户的常驻服务：

```sh
./start.sh
# 停止
./stop.sh
```

安装器会生成本机专用 launchd plist，无需修改源码里的路径。服务保留 `ProcessType=Interactive` 与 `LegacyTimers=true`，避免后台节流影响音频。服务默认只监听本机地址，没有远程访问认证。

## 两路回答与文件范围

API 路线携带系统规则、相关资料片段、会议上下文和本路线历史。Agent 路线通过 Pydantic AI 的 `list_files`、`search_files`、`read_file` 实时查证；通用 Go 题直接回答。两边独立展示答案、错误和耗时。

Agent 只读配置范围内的文件，不执行命令或写源码。默认排除凭证、符号链接、依赖/模型目录、生成代码和超大文件；每次读取、模型轮次与工具调用次数都有上限。ripgrep 不可用时退回有界文本搜索。不同项目需分别核实，不能将实现混用。关键词检索不保证找到所有跨文件调用关系，引用仍需人工判断。

两路都使用同一 LLM，Agent 不会自动审核 API 答案。800ms 静音也可能切开同一句话；当前没有自动问题合并或说话人识别。其他应用的声音可能进入全局系统音频。

## 数据和隐私

- `config.local.json`、`secrets/`：个人配置与凭证。
- `materials/`：简历、面经、源码及其他参考资料。
- `var/runs/`：音频、转写、问答与会话信息。
- `var/*.log`：采集与 ASR 诊断日志。
- `output/`：测试结果、导出与截图。

以上路径全部被 Git 忽略。切出的音频默认保留，方便在页面试听。`RETAIN_UTTERANCE_AUDIO="0"` 可删除已处理的分段音频；原始会话录音仍单独保留。清空问答会隔离两路旧历史和迟到结果，但不会删除所有原声文件。

不要把个人资料放到公开的 `examples/`，不要用 `git add -f` 加入私有文件。准备提交时运行 `python3 scripts/check_public.py`，它检查 Git 索引中的实际内容。[隐私说明](PRIVACY.md)列出了数据流和发布检查边界。

## 开发与验证

```sh
PYDANTIC_AI_NO_BANNER=1 .venv-app/bin/python -m unittest discover -s tests -v
npm run build:web
python3 scripts/check_public.py
```

测试覆盖音频分段、独立队列、流式传输、thinking 参数、失败隔离、历史清空与恢复，以及文件访问边界。算法生成质量与端到端延迟需要单独进行真实模型评测，单元测试不代表生产 SLA。

## 许可证与依赖

项目代码采用 [MIT](LICENSE)。前端及 Python 依赖分别通过 npm/pip 安装，保留其各自许可证；Apple 系统框架和 FFmpeg 是外部运行依赖，不随源码分发。模型服务的使用遵循其服务条款，API 调用费用由使用者承担。
