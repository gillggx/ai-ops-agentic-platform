-- V14 — Enrich 18 chart-block descriptions with a Keywords section so the
-- Builder Mode Block Advisor (RECOMMEND path) can match natural-language
-- queries via naïve substring scoring on description.
--
-- Mirrors python_ai_sidecar/pipeline_builder/seed.py — both append the
-- SAME keyword strings. If you change the keywords for a block, update
-- BOTH places to keep sidecar's SeedlessBlockRegistry and Java's pb_blocks
-- consistent (CLAUDE.md "Block Description 是唯一文件來源").
--
-- Idempotent: skips rows that already have '== Keywords ==' so re-runs are
-- safe (in dev where Flyway re-checks history).


UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$time series 时序 時序, trend 趋势 趨勢, line chart 折线图 折線圖, multi-line, dual-axis 双轴 雙軸$kw$, updated_at = now()
  WHERE name = 'block_line_chart' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$bar chart 长条图 長條圖 柱状图 柱狀圖, comparison 比较 比較, count 计数 計數, ranking 排名, categorical 类别 類別$kw$, updated_at = now()
  WHERE name = 'block_bar_chart' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$scatter plot 散点图 散點圖 散布图 散布圖, correlation 相关 相關, x-vs-y, dispersion 分散$kw$, updated_at = now()
  WHERE name = 'block_scatter_chart' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$box plot 箱型图 箱型圖 盒须图 盒鬚圖, distribution 分布 分佈, IQR, outlier 异常点 異常點 离群值 離群值, group comparison 组间比较 組間比較$kw$, updated_at = now()
  WHERE name = 'block_box_plot' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$scatter matrix 散布矩阵 散布矩陣 SPLOM, pairwise 配对 配對, multi-variable correlation 多变量相关 多變量相關$kw$, updated_at = now()
  WHERE name = 'block_splom' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$histogram 直方图 直方圖, distribution 分布 分佈, frequency 频率 頻率, normality, normal distribution 正态分布 常態分佈, 鐘形$kw$, updated_at = now()
  WHERE name = 'block_histogram_chart' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$SPC 统计制程管制 統計製程管制, control chart 管制图 管制圖, X-bar R X̄/R, WECO, OOC out of control, outlier 异常点 異常點 离群值 離群值, anomaly 异常 異常, anomaly detection 异常检测 異常檢測, subgroup 子群组 子群組$kw$, updated_at = now()
  WHERE name = 'block_xbar_r' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$SPC, control chart 管制图 管制圖, IMR individual moving range, OOC, outlier 异常点 異常點, anomaly 异常 異常, single measurement n=1 单测量 單測量$kw$, updated_at = now()
  WHERE name = 'block_imr' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$SPC, EWMA, CUSUM, small shift 微小偏移, drift 漂移, trend detection 趋势侦测 趨勢偵測, early warning 早期警示 早期预警, anomaly 异常 異常, outlier 异常点 異常點$kw$, updated_at = now()
  WHERE name = 'block_ewma_cusum' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$Pareto, 80/20, top-N, ranking 排序, cumulative 累计 累計, root cause 主要原因 主要因素, contributor 贡献 貢獻, frequency analysis 频率分析 頻率分析$kw$, updated_at = now()
  WHERE name = 'block_pareto' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$variability 变异 變異, dispersion 分散, variance decomposition 变异分解 變異分解, between-group within-group, lot-to-lot tool-to-tool, repeatability 重复性 重複性, shift detection 漂移偵測$kw$, updated_at = now()
  WHERE name = 'block_variability_gauge' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$parallel coordinates 平行座标 平行座標, multi-dimensional 多维 多維, profile, recipe comparison, brushing 刷选 刷選, multi-param outlier 多参数 多參數$kw$, updated_at = now()
  WHERE name = 'block_parallel_coords' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$QQ plot Q-Q plot, normality test 常态检定 常態檢定, Anderson-Darling AD test, distribution test, normality 正态性 常態性, Cpk preparation 常态分布检测 常態分佈檢測$kw$, updated_at = now()
  WHERE name = 'block_probability_plot' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$heatmap 热图 熱圖, correlation matrix 相关矩阵 相關矩陣, clustering 聚类 聚類, dendrogram 树状图 樹狀圖, hierarchical 阶层分群 階層分群, similarity 相似度$kw$, updated_at = now()
  WHERE name = 'block_heatmap_dendro' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$wafer 晶圆 晶圓, wafer map 晶圆图 晶圓圖, spatial 空间分布 空間分佈, IDW interpolation 内插 內插, uniformity 均匀性 均勻性, edge ring center-to-edge, thickness map 厚度图 厚度圖$kw$, updated_at = now()
  WHERE name = 'block_wafer_heatmap' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$wafer 晶圆 晶圓, defect 缺陷, particle 颗粒 顆粒, defect map 缺陷地图 缺陷地圖, spatial defect 空间缺陷 空間缺陷$kw$, updated_at = now()
  WHERE name = 'block_defect_stack' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$wafer 晶圆 晶圓, yield 良率, spatial ranking, worst region 最差区域 最差區域, edge yield 边缘良率 邊緣良率, yield map 良率图 良率圖$kw$, updated_at = now()
  WHERE name = 'block_spatial_pareto' AND description NOT LIKE '%== Keywords ==%';

UPDATE pb_blocks SET description = description || E'\n\n== Keywords ==\n' || $kw$wafer 晶圆 晶圓, time series 时序 時序, multi-wafer 多片 多晶圓, small multiples 小倍数 小倍數, PM comparison 维护比较 維護比較, drift 漂移, lot-to-lot 批次差异 批次差異$kw$, updated_at = now()
  WHERE name = 'block_trend_wafer_maps' AND description NOT LIKE '%== Keywords ==%';
