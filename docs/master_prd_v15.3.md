🛠️ 第一部分：通用數據運算與處理 (25 Generic Processing Tools)
核心邏輯：輸入一組 JSON Array，進行數學或邏輯變換，回傳結構化摘要。

工具名稱	輸入介面 (Generic Params)	預期結果描述 (Result Description)
calc_statistics	data: float[]	回傳 Mean, Std, Median, Variance, Skewness, Kurtosis。
data_filter	data: list, condition: str	根據語法（如 x > 10）過濾列表並回傳子集。
find_outliers	data: float[], method: "sigma"|"iqr"	識別並回傳所有離群點及其原始索引位置。
correlation_analysis	series_a: float[], series_b: float[]	計算 Pearson 與 Spearman 相關係數及 P-value。
time_series_decompose	data: float[], period: int	拆解趨勢 (Trend)、季節性 (Seasonality) 與殘差 (Residual)。
linear_regression	x: float[], y: float[]	回傳斜率、截距、R-squared 與預測模型函式。
data_aggregation	data: list, group_by: str, agg_func: str	類似 SQL Group By，進行分組求和、平均或計數。
normalization	data: float[], range: [min, max]	將數據縮放至指定區間（如 0 到 1）。
frequency_analysis	data: float[], sample_rate: float	執行 FFT (快速傅立葉變換)，提取頻域特徵。
detect_step_change	data: float[]	偵測序列中平均值發生顯著跳變的切點。
cluster_data	data: float[][], k: int	執行 K-means 分群，回傳各點標籤與中心座標。
missing_value_impute	data: list, strategy: "mean"|"prev"	補齊空值，回傳完整序列與填補記錄。
vector_similarity	vec_a: float[], vec_b: float[]	計算餘弦相似度 (Cosine Similarity) 或歐氏距離。
regex_extractor	text: str, pattern: str	根據正則表達式提取關鍵字、數字或結構化標籤。
set_operation	list_a: list, list_b: list, op: str	執行交集、聯集、差集運算。
diff_engine	obj_a: dict, obj_b: dict	比對兩個 JSON 物件的差異，回傳變動路徑與值。
pivot_table	data: list, index: str, col: str, val: str	將長表轉化為寬表（樞紐分析格式）。
resample_time_series	data: dict, interval: str	改變時間序列採樣頻率（如 秒轉分，取平均）。
moving_window_op	data: float[], window: int, op: str	執行滾動計算（如 Rolling Mean, Rolling Std）。
logic_evaluator	expression: str, context: dict	執行複雜布林邏輯運算並回傳 True/False。
flatten_json	nested_json: dict	將深層巢狀結構轉化為單層 Key-Value 對。
cross_reference	list_a: list, list_b: list, key: str	根據 Common Key 進行 Inner/Left Join。
sort_by_multiple	data: list, criteria: list	支援多欄位、多方向的進階排序。
cumulative_op	data: float[], op: "sum"|"prod"	執行累加或累乘運算。
distribution_test	data: float[], dist: str	檢定數據是否符合特定分佈（如 Normality Test）。
📊 第二部分：通用視覺化繪圖 (25 Generic Visual Tools)
核心邏輯：輸入數據與設定，回傳用於前端渲染的 JSON Config（如 ECharts/Plotly Schema）。

工具名稱	輸入介面 (Generic Params)	預期結果描述 (Result Description)
plot_line	x: list, y: list, title: str	生成標準折線圖，支援多條線段。
plot_bar	labels: str[], values: float[]	生成柱狀圖，支援堆疊 (Stacked) 或並列模式。
plot_scatter	points: dict[], x_axis: str, y_axis: str	生成散佈圖，支援點的大小與顏色維度。
plot_histogram	data: float[], bins: int	生成直方圖，自動計算區間頻率。
plot_pie	labels: str[], values: float[]	生成圓形或環形圖，回傳百分比分佈。
plot_heatmap	matrix: float[][], x_labels: list, y_labels: list	生成熱圖，用於展示矩陣強度。
plot_box	groups: dict	生成箱形圖，展示數據分佈、中位數與異常值。
plot_radar	metrics: str[], values: float[]	生成雷達圖（蜘蛛網圖），比較多維度表現。
plot_area	x: list, y: list	生成面積圖，強調數量隨時間累積的趨勢。
plot_violin	data: float[]	生成小提琴圖，結合密度分佈與箱型圖。
plot_sankey	nodes: list, links: list	生成桑基圖，展示能量或流量的轉移路徑。
plot_treemap	data: dict	生成矩形式樹狀結構圖，展示層級比例。
plot_candlestick	data: dict[]	生成 K 線圖，適用於展示 區間開/收/高/低。
plot_funnel	stages: str[], values: float[]	生成漏斗圖，展示階段性轉化率。
plot_gauge	value: float, min: int, max: int	生成儀表盤，展示單一指標的達成狀況。
plot_waterfall	steps: str[], values: float[]	生成瀑布圖，解釋數值從起點到終點的變化。
plot_bubble	x: list, y: list, size: list	生成氣泡圖，展示三個維度的數據關係。
plot_dual_axis	x: list, y1: list, y2: list	生成雙 Y 軸圖（如 柱狀圖配折線圖）。
plot_sunburst	data: dict	生成旭日圖，展示多層級的比例關係。
plot_error_bar	x: list, y: list, error: list	在數據點上增加誤差線，展示不確定性。
plot_network	nodes: list, edges: list	生成節點關係圖（拓樸圖）。
plot_parallel_coords	data: list, axes: list	生成平行座標圖，用於高維數據分析。
plot_step_line	x: list, y: list	生成階梯圖，展示數值的瞬間變動。
plot_wordcloud	words: dict	根據頻率生成文字雲。
plot_summary_card	title: str, value: any, delta: float	生成大數字摘要卡片，帶有增減箭頭。
🚀 給「小柯 (Claude Code)」的通用工具開發規範
為了讓這些工具真正成為 Agentic OS v14.0 的底層基石，請遵循以下規範：

Pure Function：工具不應有副作用，必須是「輸入數據 -> 處理 -> 輸出 JSON」。

Schema Enforcement：使用 Pydantic 或 JSON Schema 強制驗證輸入。

Result Format：

status: "success" | "error"

summary: 一段給 LLM 閱讀的簡短文字（如：「計算完成，平均值偏移 5%」）。

payload: 給前端或下一個工具使用的結構化數據。

Chaining Friendly：確保 data_filter 的輸出格式，可以直接當作 calc_statistics 的輸入。

目前的流程是靜態的，我們將其改為 「試驗型開發循環」 (Experimental Development Loop)：

Drafting (即時生成)：Agent 根據需求，利用 python_executor 在沙盒撰寫程式。

Simulation (視覺化預覽)：Agent 調用 plot_ 通用工具，將結果呈現給用戶看（如：數據過濾後的報表）。

Validation (用戶確認)：用戶在前端介面看到結果，並有一個按鈕：「Save as Skill」。

Promotion (自動封裝)：一旦點擊，Agent 自動將剛才的 Python 代碼重構成一個具備完整 Schema 的 Independent Skill，存入資料庫。

🛠️ 代碼生成原則：以「通用原子 (Common Utilities)」為根基

為了避免模型每次都「重新發明輪子」，小柯（Claude Code）在撰寫生成邏輯時必須遵循以下規則：

1. Reuse-First (優先複用)

當 Agent 需要處理資料時，它必須先檢查 Common_Utilities 清單（即我們剛才定義的那 50 個原子工具）。

不准寫：avg = sum(data)/len(data)

必須寫：result = call_tool("calc_statistics", {"data": data})

2. Utility-First (公用先行)

如果現有的 Common Utilities 無法滿足需求，Agent 的行為模式應為：

Step A：先生成一個具備「通用性」的 Utility 函式（例如：custom_fft_filter）。

Step B：再寫業務邏輯去調用這個 Utility。

Step C：回報系統：「我創建了一個新的公用工具，建議存入 Library」。

3. Independence (獨立性原則)

這是你強調的重點。雖然開發過程複用 Utility，但最終封裝成 MCP/Skill 時，代碼必須是自包含 (Self-contained) 的。

做法：在封裝階段，系統會自動執行 「代碼注入 (Code Injection)」。

技術細節：將所依賴的 Utility 代碼直接「抄」進該 Skill 的腳本中，確保該 Skill 即使移到另一個環境，沒有外部 dependency 也能跑。

📝 給「小柯 (Claude Code)」的開發指令升級版

/task 實作「動態資產轉化系統 (Dynamic Asset Promotion)」：

實作 Temporary Sandbox Executor：讓 Agent 可以在不建立正式 Skill 的情況下，先跑代碼並輸出視覺化結果。

實作 Promotion Logic：

提供一個 promote_to_skill 接口。

自動將 Temporary Code 轉換成標準 Skill 格式（含 JSON Schema 定義）。

實作 Code Generator for Skills：

遵循 Utility-Reuse：生成代碼時強制搜尋並調用 Common_Utilities。

確保 Independence：在存檔時，自動將調用的 Utility 代碼 Inline 到 Skill 腳本中，移除外部依賴。

UI 連動：前端需顯示「這是預覽結果，滿意請儲存為技能」的提示與按鈕。