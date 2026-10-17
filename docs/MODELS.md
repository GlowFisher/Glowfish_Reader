# 模型清单与获取说明（MODELS）

本文档说明 Glowfish Reader（史料阅读器）依赖的全部推理模型：每个模型的**名称、用途、来源、获取方式**，以及安装时的**自动检测 / 下载 / 校验**流程。

> 关键原则：**模型与代码分离**。`.onnx` 等大体积模型文件被 Git 排除（`.gitignore`），
> 仅通过 `ocr/models.lock.json` 记录每个文件的路径、大小与 SHA256 哈希。
> 克隆仓库后，运行引导脚本即可自动拉取或构建所需模型。

---

## 一、模型总览

| 模型 | 用途 | 来源 | 获取方式 | 体积 |
|------|------|------|----------|------|
| **PP-OCRv6 det**（检测） | 定位版面中的文字区域（文本框） | PaddlePaddle 官方 ONNX | 直接下载 | ~62 MB |
| **PP-OCRv6 rec**（识别） | 识别文本框内的文字（繁体竖排） | PaddlePaddle 官方 ONNX | 直接下载 | ~77 MB |
| **punct**（古文断句） | 自动插入现代标点（断句） | HuggingFace 开源 PyTorch | 本地导出+量化 | ~103 MB |
| **mlm**（语义纠错） | 形近字上下文重打分（掩码语言模型） | HuggingFace 开源 PyTorch | 本地导出+量化 | ~107 MB |

上述四个模型全部为**开源模型**（PaddlePaddle / HuggingFace 社区发布），**非自训练**。
项目自有的原创资产是围绕这些模型之上的**古文后处理规则**，已在 Git 中随代码管理，体积极小：

- `domain_fixes.txt`（域词典）、`confusion.txt` / `confusion_suggest.txt`（形近字混淆组）
- `bigrams.txt`（词锚）、`surnames.txt`（姓氏表）

---

## 二、模型详情

### 1. PP-OCRv6 检测模型（det）

- **文件**：`ppocrv6_onnx/det/inference.onnx` + `inference.json` + `inference.yml`
- **用途**：古籍扫描页的文字区域检测，输出文本框坐标，供竖排右起栏序还原。
- **来源**：百度飞桨 PaddlePaddle 官方第六代 OCR 检测模型（`PP-OCRv6_medium_det`），
  官方已提供 ONNX 格式。
- **获取**：
  - HuggingFace：`https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_onnx`
  - 国内镜像：`https://hf-mirror.com/PaddlePaddle/PP-OCRv6_medium_det_onnx`
  - ModelScope 集合：`https://www.modelscope.cn/collections/PaddlePaddle/PP-OCRv6`
- **许可证**：Apache-2.0（PaddlePaddle 官方模型）。

### 2. PP-OCRv6 识别模型（rec）

- **文件**：`ppocrv6_onnx/rec/inference.onnx` + `inference.json` + `inference.yml`
- **用途**：对检测到的文本框做文字识别，支持古籍繁体与竖排。
- **来源**：PaddlePaddle 官方 `PP-OCRv6_medium_rec` ONNX。
- **获取**：
  - HuggingFace：`https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_onnx`
  - 国内镜像：`https://hf-mirror.com/PaddlePaddle/PP-OCRv6_medium_rec_onnx`
- **许可证**：Apache-2.0。

### 3. 古文断句模型（punct）

- **文件**：`punct/model_int8.onnx` + `meta.json` + `vocab.txt`
- **用途**：对无标点的古文做自动断句（BERT 逐字 token 分类，输出每个字之后应插入的标点）。
- **来源**：HuggingFace 社区开源模型
  `raynardj/classical-chinese-punctuation-guwen-biaodian`（基于古文 BERT 的标点分类模型）。
- **获取**：**无法直接下载 `.onnx`**，需由 PyTorch 权重本地导出并 int8 量化：

  ```powershell
  # 需一个带 torch + transformers 的环境（见「三、安装与使用」）
  python host/glowfish_reader/proofread/setup_punct_model.py
  ```

  该脚本会：下载权重 → 导出 `model.onnx` → int8 动态量化得到 `model_int8.onnx`（~388MB → ~103MB）。

### 4. 语义纠错模型（mlm）

- **文件**：`mlm/model_int8.onnx` + `meta.json` + `vocab.txt`
- **用途**：形近字上下文重打分。对 OCR 识别结果中被判定为可疑的字，用掩码语言模型
  （MLM）结合上下文预测最可能的字，用于古文的语义级纠错。
- **来源**：HuggingFace 开源模型 `ethanyt/guwenbert-base`（古文预训练 BERT）。
- **获取**：**无法直接下载 `.onnx`**，需本地导出并量化：

  ```powershell
  # 需一个带 torch + transformers 的环境
  # 默认模型 ethanyt/guwenbert-base，可用 MLM_MODEL_ID 换模型
  python host/glowfish_reader/proofread/setup_mlm_model.py          # 导出 fp32 ONNX
  python host/glowfish_reader/proofread/setup_mlm_model.py --quantize-only  # int8 量化
  ```

  两段式原因：导出阶段用带 `torch` 的环境，量化阶段用带 `onnxruntime` 的应用 `.venv`。
  mlm 采用 **per-channel** int8 量化（MLM 头是 768×23292 大投影，per-tensor 会毁掉掩码预测）。

---

## 三、安装与使用

### 模型默认目录

模型统一存放在 **`host/glowfish_reader/proofread/models/`**（运行时约定，代码中
`Path(__file__).resolve().parent / "models"` 指向此处）。可通过环境变量
`GLOWFISH_OCR_MODELS` 覆盖。

### 自动检测 / 下载 / 校验

引导脚本 `bootstrap.ps1` 会依次执行：创建 `.venv` → 安装依赖 → 构建 UI →
**检测并下载模型** → 校验工作区。

其中模型步骤由 `scripts/fetch_models.py` 完成：

```powershell
# 完整流程：检测 + 下载缺失 + 校验
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1

# 或单独运行模型脚本
python scripts\fetch_models.py                 # 检测 + 下载 + 校验
python scripts\fetch_models.py --check-only    # 仅检测，不下载
python scripts\fetch_models.py --force         # 强制重新下载
python scripts\fetch_models.py --root <DIR>    # 指定模型根目录
```

脚本逻辑：

1. **检测**：逐文件检查「是否存在 + 大小 + SHA256」，与 `ocr/models.lock.json` 比对；
2. **下载**：对带 `download` 来源的缺失/损坏文件（PP-OCRv6），按镜像顺序重试
   （默认 `huggingface.co`，失败回退 `hf-mirror.com`；可用 `HF_ENDPOINT` 覆盖）；
3. **校验**：下载完成后重新校验 SHA256 与大小；
4. **构建提示**：对 mlm / punct 这类需本地导出的模型，脚本检测缺失后会打印明确的
   构建指引（不会尝试伪装成可直接下载）。

### 手动构建 mlm / punct（可选，仅模型缺失时）

mlm / punct 模型需 `torch` + `transformers` 环境本地导出，产品 `.venv`（仅 onnxruntime）
不含这些依赖。任选其一：

- **独立 conda 环境**（推荐）：

  ```powershell
  conda create -n gf-modelbuild python=3.12 -y
  conda activate gf-modelbuild
  pip install torch transformers onnx onnxruntime
  python host\glowfish_reader\proofread\setup_punct_model.py
  python host\glowfish_reader\proofread\setup_mlm_model.py
  python host\glowfish_reader\proofread\setup_mlm_model.py --quantize-only
  ```

- **一次性构建依赖**（`requirements-model-build.txt` / `requirements-model-export.txt`
  已提供，供参考，不随产品安装）。

> 说明：若你只使用 PP-OCRv6 的 OCR 能力、不启用「断句 / 语义纠错」后处理，
> mlm / punct 模型并非必需；`fetch_models.py` 会将其列为「需构建」但不阻断其余功能。

### 校验命令

```powershell
# 验证模型完整性（大小 + SHA256）
python scripts\fetch_models.py --check-only
```

---

## 四、模型清单文件（models.lock.json）

`ocr/models.lock.json` 是模型的**权威清单**，`schema_version: 2` 新增了获取信息：

- 带 `download` 字段的文件：可直接从 HuggingFace 镜像下载（PP-OCRv6 det/rec）；
- 带 `build` 字段的文件：需本地导出（mlm / punct），记录导出脚本与来源模型 id。

每个文件都记录 `bytes`（大小）与 `sha256`（哈希），用于下载后的完整性校验，
与 `scripts/fetch_models.py`、`ocr/src/glowfish_ocr/models.py` 的校验逻辑一致。

> 修改模型后（如升级 PP-OCRv6 版本、更换 mlm 底座），需同步更新该清单的
> 大小与哈希，否则校验会失败。

---

## 五、常见问题

**Q：开源仓库里包含模型本体吗？**
A：不包含。`.onnx` 模型体积约 350MB，已通过 `.gitignore` 排除。克隆后运行
`bootstrap.ps1` 或 `fetch_models.py` 即可自动拉取/构建。

**Q：中国网络环境下 HuggingFace 下载慢或失败怎么办？**
A：脚本默认在 `huggingface.co` 失败后回退 `hf-mirror.com` 国内镜像；也可
`$env:HF_ENDPOINT = "https://hf-mirror.com"` 强制走镜像。

**Q：模型是否需要联网才能运行？**
A：仅首次安装需要联网下载/构建。模型就位后，OCR 与后处理完全本地离线推理，
无任何云端依赖。

**Q：我可以替换这些模型吗？**
A：可以。det/rec 替换为其他 PP-OCRv6 档位（tiny/small/medium）需同步更新
`models.lock.json` 的哈希与大小；mlm 可用 `MLM_MODEL_ID` 环境变量更换底座模型后重新导出。
