# OCR 与 PDF 文本层（可选路径，R25）

R25 在既有 Mock OCR 之上增加可插拔的真实识别，并让 PDF 优先使用文本层：

- 默认 `OCR_PROVIDER=mock` 不变：模型识别、故障码候选、Embedding 与 OCR 全部确定性，演示与测试不依赖网络。
- `OCR_PROVIDER=paddle` / `rapid` / `tesseract` 时图片走真实引擎；依赖缺失、模型加载失败或图片损坏时**不伪造文本**。
- 上传 PDF 先用 PyMuPDF 提取文本层，有文本层直接当 OCR 文本用，不调用 OCR；扫描件才走 OCR。
- 任何回退都会写追踪事件，**不允许静默降级**。

## 1. 四种 Provider

| `OCR_PROVIDER` | 实现类 | 依赖 | 适用 |
| --- | --- | --- | --- |
| `mock`（默认） | `core.ai.mock.MockOCR` | 无 | 演示、测试、离线环境；输出确定性 |
| `paddle` | `core.ai.ocr_paddle.PaddleOCRProvider` | `paddleocr`、`paddlepaddle`、`numpy` | 中文/多语种图片，识别精度较高 |
| `rapid` | Rapid provider（PP-OCR ONNX） | `rapidocr_onnxruntime`、`numpy` | PaddleOCR PP-OCR 模型的 ONNX 实现，无需 `paddlepaddle`；**Python 3.13 推荐路径** |
| `tesseract` | `core.ai.ocr_tesseract.TesseractProvider` | `pytesseract` + 系统 `tesseract` 二进制 | 已装 Tesseract 的环境，无需下载模型 |

`rapid` 与 `paddle` 使用同一套 PP-OCR 模型与同一套后处理口径（文本 + 置信度 + 框坐标），差别只在推理运行时：
`paddle` 依赖官方 `paddlepaddle`（对 Python 3.13 可能没有 wheel），`rapid` 走 ONNX Runtime，纯 pip 安装即可。

`MockOCR` 行为保持不变（确定性文本、`blurry` 样本置信度 0.4），因此默认路径与改造前一致。

## 2. 选择规则与回退

`core/ai/factory.py::get_ocr()` 按 `settings.ocr_provider` 选择实现，并用 `lru_cache` 复用单个实例：

| `OCR_PROVIDER` | `available()` | 实际实现 | 追踪事件 |
| --- | --- | --- | --- |
| `mock` | — | `MockOCR` | — |
| `paddle` | `True` | `PaddleOCRProvider` | — |
| `paddle` | `False`，或构造失败 | `MockOCR` | `ocr_provider_fallback`（`requested="paddle"`，带 `reason`） |
| `rapid` | `True` | Rapid provider | — |
| `rapid` | `False`，或构造失败 | `MockOCR` | `ocr_provider_fallback`（`requested="rapid"`，带 `reason`） |
| `tesseract` | `True` | `TesseractProvider` | — |
| `tesseract` | `False`，或构造失败 | `MockOCR` | `ocr_provider_fallback`（`requested="tesseract"`，带 `reason`） |
| 其他取值 | — | `MockOCR` | — |

`available()` 的判定口径：

| Provider | 判定 |
| --- | --- |
| Paddle | `importlib.util.find_spec("paddleocr")` 命中且可导入 |
| Rapid | `importlib.util.find_spec("rapidocr_onnxruntime")` 命中且可导入 |
| Tesseract | `pytesseract` 可导入且 `pytesseract.get_tesseract_version()` 成功（即系统二进制可用） |

`check_ocr.py` 不指定 `--provider` 时的选择顺序为 `paddle` → `rapid` → `tesseract` → `mock`：
取第一个 `available()` 为真的 provider，全都不可用时落到 `mock`（并打印不可用原因）。
`get_ocr()` 只按 `settings.ocr_provider` 选择单个实现，不做这种链式探测——服务内的实际实现以 `.env` 为准。

追踪事件由 `core/observability` 的 `Tracer` 写入 `TRACE_DIR`（默认 `data/traces/`）下的 `*.jsonl`，
不阻塞业务主流程。排查「切换后仍是 Mock 结果」时，先按 `event=ocr_provider_fallback` 过滤追踪看 `reason`。

## 3. 识别语义

三种真实 provider 都返回同一个 `OCRResult`：

```python
@dataclass
class OCRBlock:
    text: str
    confidence: float
    bbox: list[float] | None

@dataclass
class OCRResult:
    text: str
    confidence: float
    blocks: list[OCRBlock]
```

- 低于 `ocr_min_confidence` 的块丢弃；无块时 `confidence = 0.0`。
- `text = "\n".join(blocks.text)`，`confidence = mean(blocks.confidence)`。
- Paddle：延迟导入 `paddleocr` 与 `numpy`，用 `PaddleOCR(lang=settings.ocr_lang, use_angle_cls=True, show_log=False)`
  解析结果；engine 通过 `lru_cache` 复用，不额外引入模块级全局缓存。
- Rapid：延迟导入 `rapidocr_onnxruntime` 与 `numpy`，engine 单例复用，按 PP-OCR 同样的「文本 + 置信度 + 框」
  口径解析，阈值过滤与拼接规则同上。
- Tesseract：`pytesseract.image_to_data` 解析 `text` / `conf`，同样按阈值过滤。

错误语义：

| 场景 | Paddle | Rapid | Tesseract |
| --- | --- | --- | --- |
| 依赖未安装 / 模型初始化失败 | `ProviderError("OCR_UNAVAILABLE", ...)` | `ProviderError("OCR_UNAVAILABLE", ...)` | `ProviderError("OCR_UNAVAILABLE", ...)` |
| 系统二进制缺失 | — | — | `ProviderError("OCR_UNAVAILABLE", ...)` |
| 识别过程失败（图片损坏等） | `ProviderError` | `ProviderError` | `ProviderError("OCR_FAILED", ...)` |

`core/multimodal/extract.py` 捕获这些错误后只标记 `needs_human=True`，**不生成任何伪造文本**。

## 4. PDF 文本层优先

`core/multimodal/pdf.py`：

```python
@dataclass
class PDFText:
    text: str
    pages: list[str]
    has_text_layer: bool

def extract_pdf_text(data: bytes) -> PDFText: ...
def pdf_page_markers(pages: list[str]) -> str: ...
```

| 规则 | 说明 |
| --- | --- |
| 提取 | 用 `fitz`（PyMuPDF）逐页 `get_text()`；`pages` 与页数一致 |
| 文本层判定 | `has_text_layer = len(text.strip()) >= 20` |
| 页码标记 | `pdf_page_markers` 每页前插入 `<!-- page: N -->` 后拼接，供切片与引用定位 |
| 加密 / 损坏 | `ProviderError("PDF_INVALID", ...)` |

`extract_fields` 的判定顺序：

| 上传类型 | `ocr_pdf_text_layer` | 行为 |
| --- | --- | --- |
| `application/pdf` | `True`（默认） | 先 `extract_pdf_text`；`has_text_layer=True` 时用带页码标记的文本，**不调用 OCR**；`False` 时回退 OCR |
| `application/pdf` | `False` | PDF 一律走 OCR |
| 图片 | — | 走 `get_ocr()` |
| 文本类 | — | 直接解码 |

`ExtractedFields` 结构不变；PDF 文本层可用时即使 OCR provider 抛错也能正常提取字段。

## 5. 依赖安装

```bash
# 基础路径（默认 mock，不需要任何 OCR 可选依赖）
pip install -r requirements.txt

# Paddle（官方运行时）
pip install paddlepaddle paddleocr

# Rapid（PP-OCR 的 ONNX 实现，Python 3.13 推荐走这条）
pip install rapidocr_onnxruntime

# Tesseract：Python 包 + 系统二进制
pip install pytesseract
# Windows：安装 Tesseract-OCR 安装包，勾选加入 PATH（或手动把安装目录加入 PATH）
# macOS：brew install tesseract tesseract-lang
# Debian/Ubuntu：apt-get install tesseract-ocr tesseract-ocr-chi-sim
```

`requirements.txt` 中 `paddleocr` / `paddlepaddle` / `rapidocr_onnxruntime` / `pytesseract` 以**注释形式**追加，
默认安装不引入；是否可用不影响默认路径与全量测试（`AI_PROVIDER=mock`）。

## 6. 样例图与检查脚本

```bash
# 生成样例图（白底黑字，字号 ≥28，幂等覆盖）
python scripts/make_ocr_sample.py

# 一键检查：provider、可用性、耗时、置信度与识别文本
python scripts/check_ocr.py --provider mock
python scripts/check_ocr.py --provider rapid --image data/ocr_samples/sample.png
python scripts/check_ocr.py --provider tesseract --json
```

`scripts/make_ocr_sample.py` 用 Pillow 生成 `data/ocr_samples/sample.png`，内容含
`型号 AuroraHome AC-Pro 1200` 与 `故障码 E106`，重复执行覆盖同一文件。

`scripts/check_ocr.py` 参数：`[--provider mock|paddle|rapid|tesseract]`、`[--image data/ocr_samples/sample.png]`、`[--json]`。
不指定 `--provider` 时按 `paddle` → `rapid` → `tesseract` → `mock` 顺序取第一个可用的 provider；
图片不存在时先按 `make_ocr_sample` 的逻辑生成。

| 输出形态 | 内容 |
| --- | --- |
| 文本模式 | `provider=<name> available=<bool> elapsed_ms=<n> confidence=<f>` 与识别文本前 200 字符 |
| `--json` | `{provider, available, elapsed_ms, confidence, text}` |
| 退出码 | provider 不可用或识别失败为 `1`，并打印 `OCR_UNAVAILABLE` 原因；正常为 `0` |

`elapsed_ms` / `confidence` 的实际值随机器与样本浮动，本节不给出固定基准。

## 7. 测试

`tests/test_ocr_providers.py` 覆盖：

| 场景 | 断言 |
| --- | --- |
| `OCR_PROVIDER=mock` | factory 返回 `MockOCR` |
| `paddle` / `tesseract` 且 `available()` 被 patch 为 `False` | 回退 `MockOCR`，产生 `ocr_provider_fallback` 追踪 |
| `PaddleOCRProvider.recognize` 未安装 | 抛 `ProviderError("OCR_UNAVAILABLE")` |
| `TesseractProvider` 不可用 | 同样的 `OCR_UNAVAILABLE` 语义 |
| Paddle 可用（依赖就绪时） | 用 `sample.png` 真实识别，文本包含 `AC-Pro 1200` 或 `E106`；否则 skip |
| 含文字 PDF | `extract_pdf_text` 的 `has_text_layer=True`、页数与关键词正确 |
| 空白 PDF | `has_text_layer=False` |
| PDF 文本层可用 + OCR 抛错（monkeypatch） | `extract_fields` 仍能提取字段 |
| `MockOCR` | 行为不变（确定性、`blurry` 为 0.4） |

`rapid` 与 `paddle` 共用同一 factory 回退路径与 `ProviderError` 语义，现有用例以 `paddle` / `tesseract`
覆盖选择、回退与不可用错误；依赖就绪时可另用 `check_ocr.py --provider rapid` 做手工验证。

```bash
python -m pytest tests/test_ocr_providers.py -q
```

依赖未安装时真实识别用例自动 skip，全量回归仍以 `pytest -q` 为准。

## 8. 已知限制

1. **Python 3.13 与 Paddle 兼容性**：`paddlepaddle` 的 wheel 对新版本 Python 支持滞后，3.13 下常无法安装；
   项目约定的运行时是 Python 3.12。3.13 环境推荐改用 `OCR_PROVIDER=rapid`（ONNX 实现，纯 pip 可装）；
   两者都不可用时 `available()=False`，只能得到 Mock 结果（并已追踪回退），闭环不受影响。
2. **Tesseract 二进制与语言包**：`pytesseract` 只是包装，必须另装系统 `tesseract` 且 PATH 可找到；
   中文识别还需 `chi_sim` 语言包，缺任一即 `OCR_UNAVAILABLE`。
3. **首帧开销**：Paddle / Rapid 首次调用会加载（必要时下载）模型，耗时明显高于后续调用；engine 由 `lru_cache` 常驻，
   内存占用随模型规模上升。`check_ocr.py` 的 `elapsed_ms` 因此不适合直接横向比较首次与再次调用。
4. **扫描件质量**：倾斜、模糊、低分辨率会显著拉低置信度，低于 `OCR_MIN_CONFIDENCE` 的块被丢弃，
   极端情况得到空文本并转人工。真实识别精度取决于引擎与图片质量，Mock 结果不能用于评估 OCR 精度。
5. **文本层判定阈值**：去空白后不足 20 字符的 PDF 仍判为无文本层并走 OCR，短页/封面页可能落入 OCR 路径；
   纯图片型 PDF 没有文本层，必然走 OCR。
6. **页码标记**：`<!-- page: N -->` 是拼接进文本的 HTML 注释，会出现在切片与引用上下文中，用于定位页码，
   不是可见内容。
7. **不做版面还原**：只输出行块文本与置信度，不保留表格结构、阅读顺序纠正或坐标可视化。