# regression_pack — builder / ChatOps 一鍵回歸

把 2026-07-12/13 實戰踩過的案例固化：動 builder（goal_plan / phase_verifier /
finalize / chart blocks）、ChatOps 卡片、或偏好/knowledge 分離前先跑。

| # | 案例 | 驗什麼 | 型態 |
|---|---|---|---|
| 1 | sort 多鍵/逗號解析 | `columns` 收 "a,b" / ["a,b"] / ["a","b"] 都排對 | 單測（deterministic）|
| 2 | 多機台分色 trend | series_field 分色 + P1 殘料剪枝不再 failed_structural | UI + LLM |
| 3 | scatter 迴歸線 | regression=true 出紫虛線 + R²（D6）| UI + LLM |
| 4 | 偏好頁分離 | /me/preferences 列偏好、/agent-knowledge 手冊 0 筆 preference | UI |

```bash
bash tools/regression_pack/run.sh          # 全跑 ~5 分鐘
AIOPS_BASE=https://aiops-gill.com REG_OUT=/tmp/reg bash tools/regression_pack/run.sh
```

LLM case（2/3）非決定性：單次 FAIL 先重跑；穩定判定要 3 連過
（feedback_self_smoke_before_user）。截圖與 log 落在 `$REG_OUT`。
