🎯 v15.4.1 Qwen 模型適配與 Prompt 優化規範

1. 定位與目標

本文件旨在透過大量範例引導，強化 Qwen 在 AI Ops 平台中的兩大核心能力：

精準工具路由 (Intent Routing)：看到需求能精確對接到 150 個 Arsenal 工具。

高品質代碼生成 (Code Crafting)：強制複用 Common Utilities，並自動生成具備「自我描述」能力的獨立 Skill。

2. 核心路由 Prompt 範例庫 (25 個測試案例)

將以下案例作為 Few-shot 注入 Qwen 的 System Prompt 中，確保它在處理用戶請求時能準確「對號入座」。

編號

用戶請求場景 (User Input)

預期對接工具 (Target Tools)

關鍵推理要點 (Reasoning Key)

01

「畫出 CD 值的常態分佈圖」

plot_histogram + distribution_test

需先檢定分佈類型再繪圖。

02

「比較這兩台機台數據的相關性」

correlation_analysis + plot_scatter

雙變數分析必備組合。

03

「幫我算這批 100 點的 Cpk」

calc_statistics

需提取 Mean 與 Std 進行製程能力計算。

04

「為什麼這週的良率一直在掉？」

time_series_decompose + plot_waterfall

需分解趨勢項並展示損失組成。

05

「找尋日誌中出現 Error 505 的頻率」

regex_extractor + plot_bar

文本提取後進行頻率統計。

06

「預測下一小時的溫度走勢」

linear_regression (High Order)

執行趨勢擬合。

07

「找出這堆數據裡的怪點」

find_outliers + plot_box

識別離群值並視覺化。

08

「這兩組數據有交集嗎？」

set_operation

進行集合運算。

09

「將時間戳格式統一為 ISO」

resample_time_series

執行數據重採樣與對齊。

10

「畫一個紅綠燈摘要給老闆」

plot_summary_card

提取 KPI 並轉化為視覺狀態。

11

「檢測數據是否有突然的跳變」

detect_step_change

偵測均值偏移切點。

12

「把巢狀 JSON 拍平，我要看 CSV」

flatten_json

結構化數據轉換。

13

「這批貨的良率受哪個參數影響最大？」

cluster_data + correlation_analysis

進行特徵關聯度排序。

14

「模擬如果壓力增加 10% 會怎樣」

logic_evaluator + sandbox_exec

進行假設性模擬運算。

15

「顯示 10 台機台的綜合戰情圖」

plot_radar

多維度指標比對。

16

「檢查數據是否符合 3-sigma 規範」

distribution_test + plot_line

帶有 Sigma 邊界線的趨勢檢查。

17

「將這兩份表按批號合併」

cross_reference

執行數據 Join 動作。

18

「提取日誌裡所有的機台 ID」

regex_extractor

使用正規表達式進行清洗。

19

「畫出數據流向圖」

plot_sankey

節點與路徑的流量分析。

20

「這組數據有周期性嗎？」

frequency_analysis

執行 FFT 頻率偵測。

21

「找出與黃金樣本最像的一組」

vector_similarity

計算餘弦相似度。

22

「把這 100 點數據做平滑處理」

moving_window_op

執行滑動平均。

23

「顯示最近三次維修的差異」

diff_engine

JSON 物件深度比對。

24

「產出一個 5x5 的相關性矩陣」

plot_heatmap

矩陣視覺化。

25

「生成這段分析的自動化腳本」

Skill_Builder

進入 Code Gen 流程。

3. Skill Builder 描述強化 Prompt

當 Qwen 在生成新的 MCP 或 Skill 時，必須遵循以下「元數據 (Metadata)」描述規範，以便日後檢索與自我核對：

描述範本 (必須包含三要素)：

使用時機 (Usage Context)：明確說明在哪種工業場景、哪種數據特徵下應調用此工具。

使用說明 (Instruction)：逐步指導如何操作該工具及其參數含義。

介面定義 (Interface)：嚴格定義 input_schema 與 output_format。

4. Arsenal 兵工廠全集規範 (75+75)

模型必須熟知 75 個數據工具與 75 個視覺化工具的詳細定義。

數據工具 (75 項) 標準範例：calc_cpk

使用時機：當製程處於穩定狀態且需評估產品品質是否符合規格界限 (USL/LSL) 時。

使用說明：輸入一組量測值與規格界限，工具會自動計算均值與標準差，並輸出 Cpk 指標。

介面定義：

Input: {"values": float[], "usl": float, "lsl": float}

Output: {"cpk": float, "mean": float, "std": float}

視覺化工具 (75 項) 標準範例：plot_spc_control

使用時機：需要長期監控製程穩定性並標記出 Out-of-Control (OOC) 點位時。

使用說明：接收時序數據與控制界限，自動渲染帶有 UCL/LCL 的趨勢圖，並將異常點標紅。

介面定義：

Input: {"data": dict[], "ucl": float, "lcl": float, "time_col": str}

Output: {"chart_type": "plotly", "config": JSON_SCHEMA}

5. Code Generation 指令調校 (The "Bridge" Rule)

為了確保代碼品質與複用性，小柯在引導 Qwen 寫 code 時必須加入以下強制約束：

Utilities-First Mandate：

寫代碼前，先輸出 // Used Utilities: [List]。

若需計算平均、回歸、繪圖，嚴禁自寫原生代碼，必須調用 common_utils。

Data Bridging (橋接模式)：

所有的資料處理邏輯必須與「數據載入」解耦。

範例：data = fetch_raw(); clean_data = data_filter(data); result = calc_statistics(clean_data);

Self-Contained Injection：

在儲存 Skill 時，若有調用公用工具，需將該工具原始碼注入到 Skill 底部，確保無外部 Dependency。

6. 視覺化校正專項 Prompt (針對 100 點垂直線問題)

針對視覺失效問題，強制加入視覺自檢指令：

「在繪製包含 datetime 的圖表時，必須計算 data_span = max(t) - min(t)。若數據點密集度高於 10 points / 1% axis_width，則必須顯式設定 xaxis_range 與 autorange=False，禁止模型使用預設的全局時間軸。」

7. 模型自我檢核考題 (Qwen Self-Verification Exam)

當 Qwen 擬稿完成後，必須自我回答以下問題進行檢查（此過程需記錄在 <thinking> 標籤中）：

工具精確度考題：我選用的工具是否包含在 150 個 Arsenal 中？它的使用時機是否與用戶場景 100% 匹配？

介面符合度考題：我傳入工具的參數名稱與類型，是否完全符合該工具的 Interface 定義？

代碼重用考題：我有沒有在代碼中重複寫了 common_utils 已經有的邏輯（如 np.mean）？如果有，請立即重構。

描述完備度考題：我寫的 Skill 描述是否包含了「使用時機、說明、介面」三要素？

若以上任一題答案為「否」，則必須推翻目前的代碼生成，重新執行 Stage 4 Reflection。