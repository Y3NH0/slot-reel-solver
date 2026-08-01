# Slot Reel RTP Toolkit — 設計文件

- 日期：2026-07-31
- 來源需求：`docs/DS-HomeWork.md`
- 狀態：設計定案，待實作計畫

---

## 1. 目標

建立一組可配置的 slot 數學工具系統，能對「給定盤面尺寸、中獎樣式、賠付表與目標指標，求出符合目標的捲軸配置」這個問題產出**精確**（非統計逼近）且**可獨立驗證**的解。

`docs/DS-HomeWork.md` 的 3×3 五樣式題目是本系統的**驗收例**，不是唯一支援的輸入。

### 驗收條件（來自作業）

| 條件 | 值 |
| --- | --- |
| RTP | 恰為 0.95（= 19/20，Fraction 真等號，非容差） |
| win rate | ≥ 0.55 |
| 盤面 | 3 欄 × 3 列 |
| 中獎樣式 | 5 種（4 個 2×2 區塊 + 1 個全盤） |
| 賠付 | 2×2：`bet × symbol_multiplier`；全盤：`bet × symbol_multiplier × 5` |
| 符號 | `{0: 0.25, 1: 0.55, 2: 1, 3: 3, 4: 5}` |
| 捲軸長度 | 不需等長、無上限 |

---

## 2. 已定案決定

以下皆已確認，實作階段不再重開：

| 項目 | 決定 |
| --- | --- |
| 計獎規則 | **max-only**：同一次 spin 只賠最高的單一 pattern |
| 通用化層級 | **L2**：grid 尺寸、pattern（cell-mask 宣告）、paytable、目標皆可配置 |
| 架構 | 三支 skill + PostToolUse verifier hook + 一個選用的探索 loop |
| skill 位置 | 專案內 `.claude/skills/`（可 commit、隨 repo 移動） |
| 雙實作 | `engine.py`（signature 聚合，快）與 `naive.py`（全窮舉，笨）刻意寫兩份互相驗證 |
| 技術棧 | Python 3 + Pydantic v2 + pytest；設定檔用 JSON |
| 數值邊界 | 邊界收 float，內部一律 `Fraction`（`Fraction(repr(0.55))` 精確得到 `11/20`） |
| 命名 | `win_rate` / `min_win_rate` / `pattern_multiplier`（預設 1） |
| 預設值 | `combine` 可省略，預設 `"max"` |
| 求解參數位置 | `search` 移出 `GameSpec`，改為 CLI flags 與 `SolverOptions` |
| 輸出格式 | 整數計數（`spin_count` / `win_count` / `combo_count` / `total_payout_units` / `payout_unit_denominator`），不用 `*_exact` 字串 |
| `solver` 區塊 | 純 metadata，**非權威**，verifier 必須完全忽略（需有對應測試） |
| Monte Carlo gate | 固定 seed → 確定性 → 可當硬性 gate，門檻 5σ |

### 決定的理由（重要者）

**為何內部必須是精確有理數。** 不是為了顯示精度，而是為了讓「是否命中目標」成為一個可判定的命題而非閾值選擇。把賠付換成 1/20 為單位的整數後，可以推導出 mod 5 同餘不變量（見 §4.2），該不變量能在 O(1) 時間內證明某些候選配置**永遠不可能**修到恰好 0.95。這種結論在浮點世界裡不可見——浮點只會回報「差 0.00042，再調調看」。

**為何 `spec_hash` 被砍掉。** 它想防的「用舊 spec 算的解被套進新 spec」，verifier 本來就會從 spec + reels 重算全部指標，錯配會以「指標不符」浮現，且錯誤訊息更具體。屬 overdesign。

**為何 `pattern_multiplier` 不叫 `pattern_bonus`。** 這個值是**乘上去**的（`bet × symbol_multiplier × pattern_multiplier`）。命名為 bonus 會誘導讀者當成加項，是會生 bug 的命名。

**為何輸出用整數計數而非有理數字串。** 這些分子分母本身就是有意義的領域量：`win_count` 是全 cycle 中會中獎的停止組合數，`spin_count` 是停止組合總數。比率才是衍生品。附帶紅利是產生了兩條零成本的自我一致性檢查（見 §7.1）。

---

## 3. 問題的數學結構

### 3.1 模型

捲軸 $i$ 是長度 $L_i$ 的**環狀** strip $S_i$。一次 spin 中各捲軸獨立均勻停在位置 $r_i \in [0, L_i)$，欄 $i$ 顯示連續 `rows` 格：$(S_i[r_i], S_i[r_i+1], \dots)$（索引 mod $L_i$）。

全 cycle 停止組合總數 $N = \prod_i L_i$。RTP 與 win rate 定義為在這 $N$ 種組合各出現一次下的期望值——即業界所稱的 full cycle 計算。

### 3.2 本題的結構性事實（實作時可據以斷言）

**五個 pattern 全部包含正中央格 (col 1, row 1)。** 推論：同一次 spin 若有多個 pattern 成立，其符號必然相同（不可能混符號中獎）。在 max-only 規則下，多重中獎退化為「同一符號 × 取最大的 pattern_multiplier」。

此性質**不可推廣到 L2 的任意 pattern 集合**（兩個不相交的 pattern 可用不同符號同時中獎），故 engine 不得把它寫成硬假設，只能作為本題 fixture 的斷言。

### 3.3 RTP 與 win rate 的耦合

$\text{RTP} = \text{win\_rate} \times \mathbb{E}[\text{payout} \mid \text{win}]$

在 max-only 下 payout 支撐集為 $\{0.25, 0.55, 1, 3, 5\}$（2×2）與 $\{1.25, 2.75, 5, 15, 25\}$（全盤）。因 $\text{win\_rate} \le 1$，達成 RTP = 0.95 要求平均中獎金額 $\ge 0.95 \times \text{bet}$：win_rate = 0.55 時需 1.727，win_rate = 1 時需 0.95。這排除了「靠大量 0.25 小獎堆出高命中率」的直覺路線，是本題真正的張力所在。

---

## 4. 存在性與可行性（已用憑證證明）

### 4.1 Golden fixtures

以下三組已用三份獨立實作交叉驗證，RTP 為 `Fraction` 真等號 `19/20`：

**A) 長度 11/6/6，N = 396，RTP = 19/20，win_rate = 1**
```
reel0 = [1, 0, 4, 1, 1, 1, 1, 0, 3, 2, 2]
reel1 = [1, 1, 1, 1, 1, 1]
reel2 = [1, 1, 1, 1, 1, 1]
payout 分佈：0.55 × 324 種停法，2.75 × 72 種
驗算：(324 × 11 + 72 × 55) / (20 × 396) = 7524/7920 = 19/20
```

**B) 長度 16/10/6，N = 960，RTP = 19/20，win_rate = 13/20 = 0.65**
```
reel0 = [2, 3, 3, 3, 3, 2, 2, 2, 2, 0, 0, 3, 3, 2, 2, 2]
reel1 = [2, 2, 2, 2, 3, 3, 2, 2, 0, 3]
reel2 = [2, 2, 2, 2, 2, 2]
payout 分佈：0 × 336，1 × 528，3 × 48，5 × 48
```

**C) 長度 12/6/10，N = 720，RTP = 19/20，win_rate = 43/60 ≈ 0.7167**
```
reel0 = [2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1]
reel1 = [2, 2, 2, 2, 3, 2]
reel2 = [4, 3, 2, 2, 1, 3, 2, 2, 2, 2]
payout 分佈：0 × 204，1 × 474，5 × 42
驗算：(474 × 1 + 42 × 5) / 720 = 684/720 = 19/20
```

### 4.2 mod 5 同餘不變量

令賠付以 1/20 為單位表示。2×2 中獎的單位值為 $\{5, 11, 20, 60, 100\}$，全盤為 $\{25, 55, 100, 300, 500\}$。**除了 symbol 1 的 11，全部都是 5 的倍數。**

令 $n_1$ = 最大獎恰為 $0.55 \times \text{bet}$ 的停止組合數。則

$$\Sigma_{\text{units}} \equiv 11 n_1 \equiv n_1 \pmod 5$$

而 RTP = 19/20 要求 $\Sigma_{\text{units}} = 19N$，故

$$\boxed{\;n_1 \equiv 4N \pmod 5\;}$$

這是必要條件，O(1) 可檢查。

**關鍵推論：右邊隨 $N$ 變動。** 只要讓 $5 \mid N$，右邊為 0，$n_1 = 0$ 合法——符號 1 完全不需要參與，障礙直接消失，不必硬湊。Fixture C 的 $N = 720$ 可被 5 整除，其賠付分佈確實沒有任何 0.55，吻合。

Fixture A 的 $N = 396$ 不被 5 整除，$4N \bmod 5 = 4$，而其 $n_1 = 324 \equiv 4 \pmod 5$ ——這是不變量必要性的實證。

**一般化形式（L2）**：令 $D$ = 各 `symbol_multiplier × pattern_multiplier` 分母的 lcm，$U$ = 該候選配置實際出現的賠付單位值集合，$g = \gcd(U)$。必要條件為 $\text{rtp} \times D \times N \equiv 0 \pmod g$。本題的 mod 5 形式是此式在 $U$ 不含 11 時的特例。

### 4.3 fixture A 為何不可刪除

A 是三組中唯一 $n_1 \neq 0$ 者，也是唯一 $\text{win\_rate} = 1$ 者。任何「偷偷假設 $n_1 = 0$」的 solver 退化，只有 A 抓得到——B 與 C 的 $N$ 皆被 5 整除、$n_1 = 0$，會一起放過。此註解須寫進測試檔，避免後人因「看起來與 B/C 重複」而移除。

---

## 5. 架構

### 5.1 檔案佈局

```
slot-reel-rtp/
├─ .claude/
│  ├─ settings.json                    # 註冊 PostToolUse hook
│  └─ skills/
│     ├─ slot-math-model/SKILL.md       # 規則 → GameSpec；結構性分析
│     ├─ reel-strip-solver/SKILL.md     # 編排求解、選策略、讀 gate 報告
│     ├─ slot-config-verifier/SKILL.md  # 獨立驗證 gate、產出 sign-off
│     └─ slot-solution-explorer/SKILL.md # 探索 loop：收集多樣化合法解
├─ src/slotmath/
│  ├─ spec.py        # Pydantic models（唯一的信任邊界）
│  ├─ windows.py     # cyclic window 抽取、signature 化
│  ├─ engine.py      # 精確 RTP/win_rate/volatility（signature 聚合，快）
│  ├─ naive.py       # 獨立參考實作（全窮舉，笨但不會錯）
│  ├─ montecarlo.py  # 第三條路徑：真的轉、真的畫盤面、獨立判定
│  ├─ metrics.py     # 賠付分佈 → 各項指標
│  ├─ diophantine.py # 齊次線性丟番圖建構（Stage 3）
│  ├─ solver.py      # 階段編排：試哪些長度、跑哪些階段、何時放棄
│  ├─ verify.py      # 三層驗證與 gate 契約
│  └─ cli.py         # slotmath spec|solve|verify|report|explore
├─ scripts/hooks/verify_on_write.py     # hook entry，薄薄一層
├─ configs/homework-3x3.json            # 驗收例的 GameSpec
├─ solutions/                           # 產出的 ReelConfig 與報告
│  └─ portfolio.json                    # 探索 loop 的多樣解集合
├─ tests/
└─ pyproject.toml                       # pydantic, pytest
```

### 5.2 職責邊界

| 模組 | 職責 | 不負責 |
| --- | --- | --- |
| `spec.py` | 載入與驗證所有外部輸入 | 任何計算 |
| `windows.py` | 環狀 window 抽取、signature 化 | 賠付語意 |
| `engine.py` | 快速精確指標計算 | 搜尋策略 |
| `naive.py` | 慢速精確指標計算（信任錨點） | 效能、被 solver 內圈呼叫 |
| `montecarlo.py` | 統計交叉檢查，不共用 `windows`/`engine` 抽象 | 精確結論 |
| `metrics.py` | 賠付分佈 → RTP / win_rate / volatility / max_win | 分佈本身怎麼算出來的 |
| `diophantine.py` | Stage 3 的線性丟番圖建構與解回轉 strip | 何時該呼叫它 |
| `solver.py` | 階段編排與放棄條件 | 指標計算、精確修復數學 |
| `verify.py` | gate 判定與報告 | 修復問題 |

`engine.py` 與 `naive.py` 並非重複程式碼，而是設計上的交叉檢查機制：兩者對同一輸入算出不同結果代表**有 bug**，而不是「哪個較準」的問題。這是系統中唯一能偵測「模型本身寫錯」的機制。

---

## 6. 資料契約

### 6.1 GameSpec（輸入，只描述「遊戲是什麼」）

```json
{
  "name": "homework-3x3",
  "grid": { "cols": 3, "rows": 3 },
  "symbols": { "0": 0.25, "1": 0.55, "2": 1, "3": 3, "4": 5 },
  "patterns": [
    { "name": "TL",   "cells": [[0,0],[0,1],[1,0],[1,1]] },
    { "name": "TR",   "cells": [[1,0],[1,1],[2,0],[2,1]] },
    { "name": "BL",   "cells": [[0,1],[0,2],[1,1],[1,2]] },
    { "name": "BR",   "cells": [[1,1],[1,2],[2,1],[2,2]] },
    { "name": "FULL", "cells": "all", "pattern_multiplier": 5 }
  ],
  "targets": { "rtp": 0.95, "min_win_rate": 0.55 }
}
```

- `cells` 為 `[col, row]` 序對，原點左上。`"all"` 是全格語法糖。
- `pattern_multiplier` 預設 1，故 TL/TR/BL/BR 可省略。
- `combine` 可省略，預設 `"max"`；另支援 `"sum"`。兩者的精確語意：
  - `"max"`：該次 spin 的賠付 = 所有成立 pattern 的 `symbol_multiplier × pattern_multiplier` 之**最大值**；無 pattern 成立則為 0。
  - `"sum"`：該次 spin 的賠付 = 所有成立 pattern 的 `symbol_multiplier × pattern_multiplier` 之**總和**。成立的 pattern 各自獨立計入，包含互相重疊者；一個 pattern 最多只計一次（即使它能以多個符號成立也不可能——pattern 成立的定義要求其所有格為同一符號）。
- 數值欄位接受 int / float / 字串有理數（如 `"1/3"`），內部一律轉 `Fraction`。float 經 `Fraction(repr(x))` 轉換，`0.55` 精確得到 `11/20`。

**Pydantic 驗證項目**：pattern cell 座標在 grid 界內；每個 pattern 至少 1 格；`cells` 無重複；`symbols` 非空且鍵可轉為符號 ID；`min_win_rate ∈ [0, 1]`；`rtp > 0`；`combine ∈ {"max", "sum"}`。

**`Rational` 型別**：`Annotated[Fraction, BeforeValidator(coerce), PlainSerializer(...)]`，輸入吃 int/float/str，輸出同時提供 float 與整數分子分母。

### 6.2 SolverOptions（求解參數，不屬於遊戲定義）

以 CLI flags 提供，不進 `GameSpec`：`--seed`、`--min-len`、`--max-len`、`--prefer-length-mod5`、`--target-win-rate`、`--volatility-bias`、`--max-repair-depth`、`--signature-budget`。

分離的具體理由：改一個 seed 不應等於改了遊戲定義。

### 6.3 ReelConfig（輸出，也是 hook 的驗證對象）

```json
{
  "spec": "configs/homework-3x3.json",
  "reels": [
    [2, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1],
    [2, 2, 2, 2, 3, 2],
    [4, 3, 2, 2, 1, 3, 2, 2, 2, 2]
  ],
  "metrics": {
    "spin_count": 720,
    "win_count": 516,
    "win_rate": 0.7166666666666667,

    "total_payout_units": 13680,
    "payout_unit_denominator": 20,
    "rtp": 0.95,

    "volatility": 1.1018923117377064,
    "max_win": 5,
    "payout_distribution": [
      { "payout": 0, "combo_count": 204 },
      { "payout": 1, "combo_count": 474 },
      { "payout": 5, "combo_count": 42 }
    ]
  },
  "solver": {
    "version": "0.1.0",
    "seed": 20260731,
    "command": "slotmath solve configs/homework-3x3.json --seed 20260731"
  }
}
```

- 上例為 fixture C 的真實數值。`win_count = 720 − 204 = 516`；`total_payout_units = 474 × 20 + 42 × 100 = 13680`；`rtp = 13680 / (20 × 720) = 19/20`。
- **artifact 不存放 verdict。** 「RTP 是否恰為目標」不寫進檔案，因為它完全由整數計數導出（`Fraction(total_payout_units, payout_unit_denominator × spin_count) == target`）。verdict 屬於 verifier 的報告，不屬於被驗證的對象——否則會出現「檔案自稱通過」這種語意，而 verifier 本來就必須忽略檔案的自我聲明。
- 同理，`win_rate` / `rtp` / `volatility` / `max_win` 亦皆為衍生值，保留它們的唯一理由是**人類可讀性**；Layer 1 會檢查它們與整數計數一致。整數計數是唯一真實來源。
- `payout_distribution` 只存 `combo_count`；機率 = `combo_count / spin_count`，避免冗餘。
- `solver` 區塊為純 metadata、非權威。verifier 必須完全忽略它——刪除或篡改該區塊後，驗證結果須位元相同。保留 inline 而非拆為旁邊檔案的唯一理由是它不會與解走散。

---

## 7. 引擎設計：signature 聚合

### 7.1 反爆炸問題

全窮舉為 $\prod_i L_i$。本題 12×12×9 = 1296，可忽略。但 L2 通用化後 5 輪 × 長度 50 為 3.1 億組合，Python 不可行。既然要做通用工具，此關無法迴避。

### 7.2 解法

**核心觀察：pattern 匹配可逐欄分解。** pattern $p$ 在欄 $c$ 只佔用某個 row 子集 $R_{p,c}$，而欄 $c$ 的 window 對結果的全部影響，僅止於「$p$ 在欄 $c$ 的那幾格是否全同、全同為哪個符號」。

定義欄 $c$ 的 **signature**：對每個 footprint 含 $c$ 的 pattern $p$，$\text{sig}[p] \in \text{Symbols} \cup \{\bot\}$。window 的行為由其 signature 完全決定。

於是把每個捲軸從「$L_c$ 個位置」壓縮為「相異 signature → 整數計數」的直方圖，在 signature 空間窮舉，權重為計數乘積。複雜度從 $\prod_c L_c$ 降為 $\prod_c |\text{Sig}_c|$。因權重為整數、機率為計數比，此計算**精確而非近似**。

**本題實測**：欄 0 參與 TL / BL / FULL，window $(a,b,c)$ 映射為
```
sig = ( a if a == b else ⊥,          # TL
        b if b == c else ⊥,          # BL
        a if a == b == c else ⊥ )    # FULL
```
相異 signature 數 = 全同 5 + 僅上對 5 + 僅下對 5 + 皆不同 1 = **16**（< $5^3 = 125$）。三欄 $16^3 = 4096$，實際受 $L_c$ 上限壓制更小。

注意這裡容易數錯：「僅上對」的 window 有 20 個（$a=b$、$c \neq b$），但它們的 signature 全都是 $(a, \bot, \bot)$，只隨 $a$ 變化，因此只有 **5** 個相異值。塌縮正是 signature 化的全部意義——把 125 個 window 壓成 16 個等價類。以 window 數代替等價類數會高估搜尋空間一個數量級。

### 7.3 護欄

開跑前先計算 $\prod_c |\text{Sig}_c|$，超過 `--signature-budget`（預設 $5 \times 10^6$）即**明確拒絕並指出是哪幾欄造成爆炸**，而非默默長跑後 OOM。

---

## 8. Solver：四階段

### Stage 0 — 主動挑選長度組合

不只是被動剪枝。依 §4.2 的推論，**優先挑選使 $5 \mid N$ 的 $(L_0, L_1, \dots)$ 組合**，因為此時 $n_1 = 0$ 合法，符號 1 不必參與，搜尋空間顯著友善。對不滿足者仍套用 $n_1 \equiv 4N \pmod 5$ 作 O(1) 剪枝。

一般化時使用 §4.2 末的 $\gcd$ 形式。

### Stage 1 — 構造種子

以 run-length 佈局建 strip（只有連續同符號的 run 才能產生 2×2 區塊）。利用逐欄可分解的乘積公式 $P(\text{pattern } p, \text{symbol } s) = \prod_c \frac{\text{count}_c(p,s)}{L_c}$ **反推**所需的 pair 密度，把 $(\text{win\_rate}, \text{RTP})$ 一次帶到目標附近，而非隨機碰撞。

### Stage 2 — 局部搜尋

突變算子：單格改符號、插入 / 刪除格（改變 $L_c$ 與 $N$）。

目標函數：$|\text{RTP} - \text{target}|$（主項）$+\ \max(0, \text{min\_win\_rate} - \text{win\_rate})$ 罰項 $+$ 選用的波動度塑形項。

**增量重算**：改一格只影響該捲軸 `rows` 個 window，故只需重建該欄的 signature 直方圖，再做一次廉價的乘積。這使每次突變評估近乎免費，是本階段可行的關鍵。

### Stage 3 — 齊次線性丟番圖建構

**取代**樸素的鄰域 BFS / IDA*。

固定 `reel0`、`reel1`，對 `reel2` 的每種 signature $s$ 計算：

- $v_s$ = 該 signature 配上前兩輪所有停法的總賠付（整數，單位 1/20）
- $w_s = v_s - 19 L_0 L_1$ — 該 signature 的「盈虧」

則「RTP 恰為 19/20」等價於

$$\sum_s n_s w_s = 0, \qquad n_s = \texttt{reel2} \text{ 中貼該 signature 的位置數}$$

而 $L_2 = \sum_s n_s$ ——**捲軸長度是方程解出來的，不是猜的**。

**存在性**：有兩條互不相同的路徑，實作必須都認得。

1. **混合符號**：若 $\{w_s\}$ 同時有正有負，取 $w_p > 0$、$w_q < 0$，令 $n_p = |w_q|$、$n_q = w_p$ 即得 0。
2. **零權重**：若某個 $w_z = 0$，把整條最後捲軸放在 signature $z$ 上即可，長度任意。

原先本文件宣稱「正負必同時存在」——**這是錯的**，已由實作推翻。fixture A 與 B 的 16 個 signature 中有 15 個為負、1 個為零，**沒有任何正值**；它們正是走第 2 條路徑：最後捲軸是均勻的（A 為 `[1]*6`、B 為 `[2]*6`），只產生單一 signature，而該 signature 的 $w = 0$。只有 fixture C 是混合符號（1 正 15 負）。

推論：兩條路徑都不存在（所有 $w_s$ 同號且無零）是可能的，此時該組固定捲軸無解，solver 必須換一組而非繼續搜尋。`search_last_reel` 先試均勻捲軸正是在便宜地探測第 2 條路徑。

實測 $w$ 值（某組固定 `reel0`/`reel1`）：
```
(2,2,2)  w = +579
(2,·,·)  w = −721
(0,0,0)  w = −1856
(·,0,·)  w = −1926
(4,4,4)  w = −2021
```

**必須誠實記載的限制**：signature 直方圖**並非任意可實現**。一段長度 $k$ 的 run 會綁定產生 $k-2$ 個三連 signature 加兩個邊界 signature，因此方程的解要轉回真實 strip 時仍需有限搜尋。**這一步不是封閉解**，不得在實作或文件中假裝它是。

判定條件為 `Fraction == Fraction` 的真等號；僅在真等號成立時標記 `rtp_exact: true`。若解無法轉回可實現的 strip，調整長度改變 $N$ 並回 Stage 0。

---

## 9. 驗證機制：三層

每層擋不同種類的錯誤。

### 9.1 Layer 1 — 檔案內部一致性（零計算，只讀）

因輸出採整數計數，光讀檔案即可查出矛盾：

```
spin_count == Π len(reels[i])
Σ combo_count == spin_count
Σ (combo_count × payout × payout_unit_denominator) == total_payout_units
win_count == spin_count − combo_count[payout == 0]
rtp ≈ total_payout_units / (payout_unit_denominator × spin_count)
win_rate ≈ win_count / spin_count
```

抓「手改壞的 / 截斷的 / 拼接錯的 artifact」，成本近乎零，故置於第一關。

### 9.2 Layer 2 — engine / naive 交叉檢查

`naive.recompute()`（全窮舉）與 `engine.recompute()`（signature 聚合）與檔案中的整數計數，三方須 `Fraction` 真等號。

**錯誤訊息必須分辨不合出現在哪一層**，因診斷方向相反：

| 情況 | 意義 |
| --- | --- |
| 兩引擎互不合 | 程式有 bug |
| 兩引擎一致但檔案不符 | artifact 過期或被篡改 |

混報為「驗證失敗」等同沒報。

### 9.3 Layer 3 — Monte Carlo 交叉檢查

**存在理由**：Layer 1 與 2 共同建立在「`spec` → pattern 匹配邏輯的翻譯正確」這個假設上。若此翻譯本身有誤（最典型是 cell 座標 `(col,row)` 被寫成 `(row,col)`），`naive` 與 `engine` 會**一起錯**，交叉檢查完全沉默。

Layer 3 走一條刻意不共用任何抽象的路徑：真的隨機轉、真的取 window、真的把盤面展開為 grid、以另一份直接比對 grid 格子的判定函式計算賠付——不經 signature，也不經 `windows.py` 抽象。

固定 seed 是關鍵設計：它把統計檢定轉為**確定性測試**（今日通過即永遠通過），故可作硬性 gate，門檻 5σ，不必退化為無人查看的 warn。變異數取自真實賠付分佈，不作假設。

預設 $2 \times 10^6$ spins（hook 情境降為 $10^5$）。另提供 `--mc-seed-sweep` 以多 seed 執行的 thorough 模式。

### 9.4 Gate 契約

**Hard fail**：schema 無效／strip 含未宣告符號／Layer 1 任一條不符／`naive ≠ engine`／檔案計數 ≠ 重算結果／RTP ≠ target 真等號／`win_rate < min_win_rate`／Monte Carlo 偏離 > 5σ。

**Warn（不擋）**：$\prod|\text{Sig}|$ 逼近預算上限；波動度或 `max_win` 極端。例如 fixture A 的 `win_rate = 1`（玩家從不落空）規則上合法但商業上可疑，值得提醒而非否決。

**Exit code**：`0` = 全過，`1` = 驗證不通過，`2` = 驗證器自身錯誤。此區分為必要——否則「驗證器 crash」會被誤讀為「解是錯的」。

---

## 10. PostToolUse hook

```json
// .claude/settings.json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": "python3 scripts/hooks/verify_on_write.py" }
        ]
      }
    ]
  }
}
```

`scripts/hooks/verify_on_write.py` 由 stdin 讀 hook payload，取 `tool_input.file_path` 後分流：

| 路徑 | 行為 |
| --- | --- |
| 不在 `solutions/**.json` 或 `configs/**.json` | **exit 0 靜默放行** |
| GameSpec | 僅跑 schema 驗證 |
| ReelConfig | 跑完整 gate，Monte Carlo 降為 $10^5$ spins（維持 hook 在 1 秒內） |

絕大多數編輯走第一條路徑，故該路徑必須極快：純字串判斷，不 import 任何重模組。

失敗時 **exit 2** 並將 gate 報告寫入 stderr。exit 2 的語意是「將 stderr 回饋給 Claude」，於是 agent 當場看見自己剛寫壞了什麼並自我修正，無需人工介入。

### 兩條不可妥協的原則

1. **hook 絕不自己改檔案。** 會自動改檔案的 hook 會與 agent 的編輯打架，產生極難除錯的競態。它只回報。
2. **JSON 解析失敗須給人類可讀訊息**，不得吐 traceback。

---

## 11. 探索 loop

### 11.1 目標

蒐集 $N$ 組**都合法但體感不同**的解，寫入 `solutions/portfolio.json`。

### 11.2 多樣性定義

特徵向量全部由 `metrics` 直接算出，無需額外計算：

```
f = ( win_rate,
      volatility,
      log(1 + max_win),                 # 壓縮尺度，避免大獎天花板主導距離
      entropy(payout_distribution),     # 獎金結構的豐富度
      spin_count )                      # 週期長度 ≈ 機率粒度
```

各維正規化後，判準：新解與**現有每一組**的正規化歐氏距離皆 $\ge D$ 方可收錄。

**正規化必須使用校準階段存下的固定範圍，不可用當下樣本即時重算。** 原設計沒寫清楚這點，實作後被驗出是真缺陷：若拿「現有條目 ∪ 候選」即時做 min-max，當 portfolio 只有 1 筆時，兩點正規化會把任何有差異的維度硬拉伸到 $\{0, 1\}$，於是近似重複的候選看起來距離最大而被收錄——去重在 portfolio 大小 1–2 時完全失效，而那正是每次全新執行的前兩輪。實測：`win_rate` 0.90 對 0.905（其餘維度相同）會被收錄，但同一候選在 portfolio 多一筆遠距條目時就正確被拒。

因此校準階段（§11.3）除了門檻 $D$，還必須存下**各維的 min/max 範圍**，由 `should_admit` 使用；如此收錄與否才與順序無關。校準尚未存在時，不得假裝過濾——直接收錄並在程式碼與文件中言明，因為此時尚無有意義的尺度。

`entropy` 這一維是必要的：僅靠 `win_rate + volatility`，fixture C（只有 0/1/5 三種獎金）會與「有五種獎金但統計量湊巧相同」的解被判為重複，而兩者對玩家是完全不同的遊戲。

### 11.3 參數校準

$D = 0.25$、$K = 3$ 為**待校準初值**。首次執行先跑校準輪：收 10 組不設多樣性限制的解，量測特徵空間實際散佈範圍，再回推 $D$。校準結果寫入 `solutions/portfolio.json` 的 metadata。

### 11.4 每輪流程

1. 讀 `solutions/portfolio.json` 現況
2. **選下一個探索方向**：檢視特徵空間哪塊為空，據此設定 solver 偏壓（`--target-win-rate`、`--prefer-length-mod5`、`--volatility-bias`、新 seed）
3. 執行 solver → 執行 verifier
4. 通過 gate 且滿足多樣性距離 → 收錄；否則丟棄並**記錄已撞過的方向**，避免重複撞牆
5. 收滿 $N$ 組，或**連續 $K$ 輪無新解** → 停止

**agent 在此的價值**：步驟 2。它讀得懂「已經有三組高命中低波動了，該去找高波動的」，純隨機做不到。這是本 loop 唯一正當的存在理由——loop 不用於逼近 RTP（那是確定性計算，屬 solver 內圈）。

停止條件採「連續 $K$ 輪無新解」而非固定輪數，因可行區域大小事先未知。

觸發方式：`/loop` 搭配 `slot-solution-explorer` skill，dynamic pacing（每輪耗時取決於 solver 收斂速度，固定間隔無意義）。

---

## 12. Skill 定義

四支 skill 皆採 `SKILL.md` + `references/` 結構，與參考資料庫 `~/projects/Slot-Casino-Game-Developer-Skills-for-Stake-Engine` 的慣例一致，但**刻意偏離其模擬導向**：該資料庫的 `rtp-optimizer` / `senior-game-math-engineer` 要求 1M–20M spins 與容差帶，對本問題屬過度工程——組合空間小到可精確窮舉。

| skill | 職責 | 輸出契約 |
| --- | --- | --- |
| `slot-math-model` | 自然語言規則 → `GameSpec`；pattern 結構性分析（如「是否所有 pattern 共用某格」）；推導同餘不變量 | `GameSpec` JSON + 結構分析報告 |
| `reel-strip-solver` | 編排求解：選長度組合、選階段、讀 gate 報告、決定何時放棄 | `ReelConfig` JSON + 求解過程報告 |
| `slot-config-verifier` | 執行三層驗證、產出 sign-off | gate 報告 + pass/fail verdict |
| `slot-solution-explorer` | 驅動探索 loop、維護 portfolio、選探索方向 | `portfolio.json` + 多樣性分析 |

每支 skill 的 `SKILL.md` 須包含：`name` / `description` frontmatter、工作流步驟、可執行的 CLI 命令、輸出契約、執行規則。

---

## 13. 測試策略

TDD 順序本身即設計——它決定 bug 能被攔在哪一層。

1. **先寫 `naive.py`，以手算案例驗證。** 它是系統的信任錨點，必須笨到不可能錯：直接展開盤面、直接比對格子、零抽象。
   手算 fixture：三輪全為同一符號 → 每次 spin 全盤同符號 → `max = FULL = mult × 5`，RTP / `win_rate = 1` / `spin_count` 全可純手算。五個符號各一組，涵蓋整張 paytable。
2. **cyclic wrap 邊界**：$L = \text{rows}$（window 繞回自身）；$L < \text{rows}$ → **明確拒絕**，$L \ge \text{rows}$ 列入 spec 驗證條件。
3. **再寫 `engine.py`，以 property-based test 對 `naive.py`**：隨機生成小 spec（1–3 欄、2–4 列、隨機 pattern mask、2–4 符號）與隨機 strip，斷言 `Fraction` 真等號。投報率最高的一組測試，同時涵蓋 signature 化的正確性。
4. **combine 規則**：`max` 與 `sum` 各自的固定案例，重點在「兩 pattern 同時中」。
5. **Golden regression**：fixtures A / B / C，斷言 RTP = 19/20 真等號、`win_rate`、`spin_count`、完整 `payout_distribution`。附 §4.3 的「A 為何不可刪」註解。
6. **mod 5 不變量 property test**：對任意隨機解斷言「若 RTP == 19/20 則 $n_1 \equiv 4N \pmod 5$」（必要條件方向）。
7. **`solver` 區塊非權威**：刪除該區塊 / 填入垃圾，斷言 verifier verdict 位元相同。
8. **Monte Carlo 收斂**：固定 seed，斷言落在 5σ 內（確定性測試）。
9. **反爆炸護欄**：構造 $\prod|\text{Sig}|$ 超預算的 spec，斷言拋出含「哪幾欄爆炸」資訊的明確錯誤，而非 OOM。
10. **Hook 行為**：不相關路徑靜默 exit 0；壞 ReelConfig exit 2 且 stderr 可讀；壞 JSON 給訊息而非 traceback。

---

## 14. 業界對照

「加長捲軸以取得更細的機率粒度」在業界稱為**虛擬捲軸（virtual reels）**，出自 Inge Telnaes 的 US Patent 4,448,419（1984），後由 IGT 取得。實體捲軸的可見停位有限（如 22 格），而 RNG 值域可遠大於此（如 128），透過映射表即可取得遠細於實體格數的機率粒度。本設計的齊次線性丟番圖建構（§8 Stage 3）本質上是該技術的精確化版本——差別在於我們解出的是「使 RTP 恰為目標值」的長度與組成，而非僅調整權重分佈。

全 cycle 計算 RTP 與 hit frequency 的方法對應業界的 **PAR sheet（Probability Accounting Report）**。捲軸長度不等亦為真實機台常態（如 Lobstermania 為 47/46/48/50/50）。

**文獻現況**：本特定組合問題（給定 paytable 與中獎樣式，求使 RTP 精確等於目標值的捲軸配置）**未查獲**專門的學術文獻。此處記為「未查獲」而非「不存在」。

參考資料：
- [Creating PAR Sheets, Slot Math Tutorial — Slot Game Design](https://slotgamedesign.com/2019/01/19/slot-math-tutorial-creating-par-sheets/)
- [Free Slot Machine PAR Sheets — Easy Vegas](https://easy.vegas/games/slots/par-sheets)
- [Slot Machine Reel Mechanics Explained — Run the Slots](https://runtheslots.com/learn/slot-machine-reel-mechanics-guide)
- [PAR Sheets, probabilities, and slot machine play (Harrigan & Dixon)](https://www.stoppredatorygambling.org/wp-content/uploads/2012/12/PAR-Sheets-Probabilities-and-Slot-Machine-Play-Implications-for-Problem-and-Non-Problem-Gambling.pdf)
- [Elements of Slot Design, 2nd Ed. — Slot Designer](http://slotdesigner.com/wp/wp-content/uploads/Elements-of-Slot-Design-2nd-Edition.pdf)

---

## 15. 範圍外

以下明確不做（即 §2 所述 L3 層級）：

- wild 代替符號。它會破壞「同一 spin 多重中獎必為同一符號」這類結構偵語，需要重寫匹配層。
- scatter（不依位置的計數型中獎）。
- 免費遊戲 / 多階段。這會使精確窮舉不再可行，需引入遞迴 EV 或退回模擬。
- 多線 / 多向（ways）計獎。
- 前端、動畫、RGS 整合。

---

## 16. 殘餘風險

| 風險 | 影響 | 緩解 |
| --- | --- | --- |
| Stage 3 的 signature 直方圖不可實現 | 解出方程卻無法轉回真實 strip | 已知限制，保留有限搜尋；失敗則調整 $N$ 回 Stage 0 |
| L2 通用化下 $\prod\|\text{Sig}_c\|$ 爆炸 | 大盤面不可用 | 明確預算護欄與具體錯誤訊息；不承諾任意規模 |
| Monte Carlo 固定 seed 只驗一條路徑 | 特定 seed 巧合通過 | 提供 `--mc-seed-sweep` thorough 模式 |
| 多樣性參數 $D$ / $K$ 憑經驗設定 | portfolio 過鬆或過緊 | 首輪校準（§11.3） |
| `engine` 與 `naive` 犯相同的翻譯錯誤 | 交叉檢查沉默 | Layer 3 走完全獨立路徑（§9.3） |
