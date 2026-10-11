# Team PRD Builder

以繁體中文撰寫或重構產品需求文件的 Codex 技能。它協助團隊釐清範圍、保留產品決策、建立功能與驗收追溯，並產生 DOCX、可編輯 draw.io 圖源及規格參考測試。

本套件的領域情境與測試資料均為合成範例。範例規則不代表任何專案的正式需求。產生文件、結構檢查或合成測試通過，不等於產品已實作或驗收通過。

## 套件內容

```text
team-prd-builder/
  SKILL.md            技能入口
  agents/             Codex 介面資訊
  references/         寫作、訪談、圖解及資料契約
  assets/             起稿模板、功能工作表與合成範例
  scripts/            產生器、檢查器及工具測試
```

使用技能時，讓 Codex 讀取 `team-prd-builder/SKILL.md`；若已安裝技能，可用 `$team-prd-builder` 呼叫。安裝及發布由使用者另行決定。

## Python 工具

使用 Python 3.10 或更新版本。需要 `python-docx`、`Pillow` 及環境可讀取的中文字型；套件不附字型檔。優先使用既有文件處理環境。若需建立獨立環境，可在儲存庫根目錄執行：

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Windows 請使用該平台的虛擬環境啟用方式。

以下命令也在儲存庫根目錄執行：

```sh
# 驗證合成範例結構
python3 -B team-prd-builder/scripts/validate_prd.py team-prd-builder/assets/example.prd.json

# 執行產生器與檢查器測試
python3 -B team-prd-builder/scripts/test_prd.py

# 產生合成範例及示範測試結果
python3 -B team-prd-builder/scripts/build_prd.py team-prd-builder/assets/example.prd.json --output deliverable --example-tests
```

未核准規則在正式規格測試模式下會保留阻擋；合成範例模式的通過結果只用於教學。圖解可用 `--font-file` 指定中文字型，DOCX 可用 `--docx-font` 指定字型名稱。DOCX 版面仍需在可用的渲染環境逐頁確認。

## 公開套件與專案資料

客戶輸入、內部規則、確認紀錄與實際產出應保存在獨立的授權工作區。公開套件只保留通用工具、空白工作表及合成範例。`.gitignore` 排除常見輸入、產出、憑證檔與 Python 快取；提交前仍需檢查實際檔案內容。
