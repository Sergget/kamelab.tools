# OCR 节点（ocr_server）说明

独立部署的 OCR 服务（Flask + PaddleOCR，CPU 模式），被主服务（doc-convert）经 HTTP 调用，用于**图片**与**扫描型 PDF** 的文字识别。节点不可达时主服务会自动降级（见 [doc-convert 文档](doc-convert.md)）。

## 角色定位

```
┌─────────────────────┐   /convert（multipart file）  ┌──────────────────────┐
│  主服务（FastAPI）    │ ─────────────────────────────▶ │  OCR 节点（Flask）    │
│  backend/ :8000      │ ◀───────────────────────────── │  ocr_server/ :8001   │
│  图片/扫描 PDF 识别    │   JSON（content + 行级 bbox）   │  PaddleOCR（CPU）     │
└─────────────────────┘                                └──────────────────────┘
```

- 节点**探活**：`GET /health`（主服务 `/api/tools/doc-convert/health` 的 `ocr_status` 字段展示）；
- 节点**能力自描述**：`GET /supported_formats`（格式、页数/大小上限、`include_lines` 行级输出）；
- 节点**离线**：主服务自动降级本地 OCR（若主服务装了 paddleocr），否则图片/扫描件转换失败（文本型 PDF 不受影响）。

## 依赖与版本约束（重点）

依赖清单见 `ocr_server/requirements_win11.txt`（Windows 实测）与 `ocr_server/requirements.txt`（双端通用骨架）。以下版本约束是**踩坑总结**，务必遵守：

| 包 | 版本 | 原因 / 说明 |
| --- | --- | --- |
| Python | **3.11**（实测 3.11.9） | `paddlepaddle==2.6.2` 对应 Python 3.11 |
| paddlepaddle | **==2.6.2**（CPU 版） | GPU 版 wheel 只含 sm_61（Pascal）及以上 kernel，Maxwell（GTX 960，CC 5.2）不可用 → 永久 CPU 模式（`use_gpu=False`） |
| paddleocr | **==2.7.0.3** | 与 paddlepaddle 2.6.2 配套 |
| numpy | **<2.0.0** | ⚠ PaddlePaddle 2.6.2 编译时链接 numpy 1.x ABI，装 numpy 2.x 会导致**静默返回全零/错误结果** |
| opencv-python / opencv-contrib-python | **<=4.6.0.66** | paddleocr 2.7.0.3 的版本约束；⚠ **严禁安装 opencv-python-headless**，其 5.x 命名空间包会覆盖 `cv2` 模块导致 PaddleOCR 初始化失败（`INTER_NEAREST` 等常量缺失） |
| PyMuPDF | **>=1.25.0**（实测 1.25.3） | paddleocr 内部声明要求 `<1.21.0`（1.20.x 需源码编译），但 OCR 服务器只用 PyMuPDF 渲染 PDF、不经过 paddleocr 内部 API，高版本预编译 wheel 实测可用 |
| flask / flask-cors / psutil | 最新即可 | Web 框架与健康检查 |

**推荐安装顺序**（`requirements_win11.txt` 头部注释同款）：

```bash
python -m venv ocr_server\.venv
ocr_server\.venv\Scripts\python -m pip install paddleocr==2.7.0.3 --no-deps
# 再安装其余依赖（flask、psutil、numpy<2、opencv 4.6、Pillow、PyMuPDF 等）
ocr_server\.venv\Scripts\python -m pip install -r ocr_server\requirements_win11.txt
```

> 意外安装了 `opencv-python-headless` 的补救：
> `pip uninstall opencv-python-headless -y`，然后 `pip install opencv-python==4.6.0.66 opencv-contrib-python==4.6.0.66`。

### 模型

PaddleOCR 使用 **PP-OCRv4 mobile 系列、中文（lang="ch"）**，关闭方向分类（`use_angle_cls=False`，省内存），**首次请求时延迟加载**（可能下载模型文件，耗时较长），加载后常驻复用。

## 部署（Windows，作为系统服务）

1. **前置**：Python 3.11、[NSSM](https://nssm.cc/)（加入 PATH）；
2. **建 venv 并装依赖**（见上）；
3. **注册服务**（脚本 `deploy/deploy_windows.ps1`）：

```powershell
# 默认 install：注册并启动服务（默认端口 8001，服务名 LabToolsOCRService）
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1
# 常用操作
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action status
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action restart
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action schedule   # 开机自启计划任务（SYSTEM 账户）
powershell -ExecutionPolicy Bypass -File .\deploy_windows.ps1 -Action uninstall
```

> `ocr_server.py` 启动时会**强制校验**必须使用 `ocr_server\.venv\Scripts\python.exe` 运行（`ensure_project_venv`），用其它解释器直接退出。

4. **接入主节点**：编辑 `deploy/lab-tools.service` 中的 `LAB_TOOLS_OCR_NODE_URL=http://<本机IP>:8001`，然后：

```bash
sudo bash ./deploy_ubuntu.sh service
```

## 端点

| 端点 | 说明 |
| --- | --- |
| `GET /health` | 健康检查：节点身份、CPU/内存、任务计数、`gpu_available / gpu_usable / ocr_mode` |
| `GET /health/gpu` | GPU 详情（nvidia-smi 展示；Maxwell 架构提示不可用） |
| `GET /supported_formats` | 能力自描述（格式、上限、`structured_lines` 行级输出） |
| `POST /convert` | OCR 转换：`multipart/form-data`，字段 `file`；查询参数 `include_lines`（默认 true，返回行级 bbox+置信度，供主服务版面重建） |

业务参数（环境变量，默认值）：`OCR_MAX_FILE_MB=100`、`OCR_MAX_PDF_PAGES=200`、`OCR_TIMEOUT_SEC=300`、`OCR_PDF_DPI=200`、`NODE_NAME=win11`、`NODE_ROLE=heavy`、`PORT=8001`。

## 常见问题

- **首次请求很慢 / 卡住**：首次请求触发模型下载与加载，属正常；之后请求复用单例。
- **识别结果全零 / 乱码**：检查是否装了 `numpy>=2.0`，需降到 `<2.0.0`。
- **PaddleOCR 初始化失败（常量缺失）**：卸载 `opencv-python-headless`，重装 `opencv-python==4.6.0.66`。
- **GPU 加速不可用**：Maxwell（GTX 960）架构不被 paddlepaddle 2.6.2 wheel 支持；升级到 Pascal+（如 GTX 1060）后可换 `paddlepaddle-gpu==2.6.2` 并把 `use_gpu` 改为 True，同时安装对应 CUDA Toolkit（详见 `ocr_server.py` 顶部注释）。
- **Windows 服务（Session 0）崩溃**：CPU 版 paddlepaddle 不加载 CUDA DLL，Session 0 完全安全；若曾用 GPU 版需先卸载 CUDA Toolkit。
