# QA Checklist — Next Phase Features

**Date:** 2026-04-15
**Scope:** P1-1 ~ P3-3 (7 items from SPEC_next_phase.md)

---

## P1-1: Skill Pipeline Storage

| # | Test | Method | Expected |
|---|------|--------|----------|
| 1.1 | DB column exists | `SELECT column_name FROM information_schema.columns WHERE table_name='skill_definitions' AND column_name='pipeline_config'` | Row returned |
| 1.2 | POST /my-skills/from-pipeline creates skill | `curl -X POST /api/v1/my-skills/from-pipeline` with valid plan JSON | 201, skill in DB with pipeline_config |
| 1.3 | Auto-derived input_schema | POST without input_schema, plan has `data_retrieval.params: {step: "X"}` | input_schema auto-generated with `key: "step"` |
| 1.4 | GET /my-skills returns pipeline_config | List skills | pipeline_config field present in response |
| 1.5 | Pipeline Skill execution | `execute_skill(id)` on a pipeline skill | Returns `is_pipeline_skill: true` + pipeline_cards + flat_data |
| 1.6 | SSE emits pipeline_stage events | Execute pipeline skill via Copilot | Console shows 9-stage cards |
| 1.7 | Frontend "Save as Skill" button | Complete a plan_pipeline query, go to Console tab | "Save as Skill" button visible |
| 1.8 | Save flow end-to-end | Click save, enter name, confirm | Skill appears in My Skills page |
| 1.9 | Old skills unaffected | Execute a steps_mapping-based skill | Works as before (pipeline_config is NULL) |

## P1-2: Resizable Panel

| # | Test | Method | Expected |
|---|------|--------|----------|
| 2.1 | PanelGroup renders | Load app | Main area + Copilot panel visible, separator between them |
| 2.2 | Drag to resize | Drag separator left/right | Main area grows/shrinks, Copilot panel inverse |
| 2.3 | Min/max constraints | Drag Copilot panel below 20% or above 50% | Stops at constraint |
| 2.4 | Plotly charts reflow | Open DataExplorer, resize panel | Charts auto-resize (responsive: true) |
| 2.5 | Sidebar unaffected | Collapse/expand sidebar | Works independently of panel resize |

## P2-1: Histogram / Distribution / Box Plot

| # | Test | Method | Expected |
|---|------|--------|----------|
| 3.1 | Chart type selector visible | Open DataExplorer | [Line] [Scatter] [Histogram] [Box Plot] buttons shown |
| 3.2 | Line chart (default) | Click Line | Standard line chart with markers |
| 3.3 | Scatter chart | Click Scatter | Points only, no lines |
| 3.4 | Histogram | Click Histogram on SPC data | Frequency histogram with sigma bands (1-4 sigma) + mean line |
| 3.5 | Histogram < 5 points | Filter to dataset with < 5 rows, click Histogram | Shows "requires at least 5 numeric data points" |
| 3.6 | Box plot | Click Box Plot | Box plot grouped by chart_type/param_name |
| 3.7 | Box plot max 10 groups | Dataset with > 10 groups | Only first 10 shown |
| 3.8 | Sigma annotations | Histogram mode on SPC | Mean (mu), +1-4 sigma lines with labels |

## P2-2: Playwright E2E

| # | Test | Method | Expected |
|---|------|--------|----------|
| 4.1 | Config file exists | `ls e2e/playwright.config.ts` | File exists |
| 4.2 | Smoke tests exist | `ls e2e/smoke.spec.ts` | File exists with 4 tests |
| 4.3 | DataExplorer tests exist | `ls e2e/data-explorer.spec.ts` | File exists with 4 tests |
| 4.4 | npm script | `npm run e2e -- --help` | Playwright help shown |
| 4.5 | Two viewport projects | Check config | desktop-1920 + laptop-1366 |

## P3-1: Correlation Matrix (Heatmap)

| # | Test | Method | Expected |
|---|------|--------|----------|
| 5.1 | Heatmap button appears | Open DataExplorer with grouped data | [Heatmap] button in chart type selector |
| 5.2 | Heatmap renders | Click Heatmap | Plotly heatmap with RdBu colorscale, -1 to 1 range |
| 5.3 | Auto-detect compute_results | Pipeline returns compute_results with matrix key | Heatmap shows params x params matrix |
| 5.4 | Fallback correlation | No compute_results, but grouped data | Client-side Pearson correlation computed |
| 5.5 | < 2 groups | Single group dataset | Heatmap button not shown |

## P3-2: Time-window Slider

| # | Test | Method | Expected |
|---|------|--------|----------|
| 6.1 | Toggle button visible | Line or Scatter chart | "Time Range" toggle in chart type bar |
| 6.2 | Toggle not visible | Histogram or Box Plot | "Time Range" toggle hidden |
| 6.3 | Slider appears on toggle | Click "Time Range" | Plotly rangeslider under x-axis |
| 6.4 | Drag to filter time range | Drag slider handles | Chart updates to zoomed time window |
| 6.5 | Toggle off | Click "Time Range" again | Slider disappears, full range restored |

## P3-3: rem/clamp Fluid Typography

| # | Test | Method | Expected |
|---|------|--------|----------|
| 7.1 | CSS variables defined | Check globals.css | :root with --fs-xs through --fs-xl, --sp-xs through --sp-xl |
| 7.2 | AppShell uses variables | Check AppShell.tsx | NavLink fontSize uses var(--fs-sm) |
| 7.3 | PipelineConsole uses variables | Check PipelineConsole.tsx | fontSize uses var(--fs-sm), padding uses var(--sp-md) |
| 7.4 | DataExplorerPanel uses variables | Check DataExplorerPanel.tsx | Header fontSize uses var(--fs-lg) |
| 7.5 | Topbar uses variables | Check Topbar.tsx | Title fontSize uses var(--fs-xl) |
| 7.6 | Visual scaling | Resize browser from 1366px to 1920px | Font sizes and spacing smoothly scale |
| 7.7 | No broken layouts | Navigate all pages at 1366x768 | No overflow, no truncated text |

---

## Test Results

### Static Analysis

| Check | Result |
|-------|--------|
| TypeScript `tsc --noEmit` | PASS (0 errors) |
| Python AST parse (8 files) | PASS (all OK) |

### Files Modified

**Backend (Python):**
- `models/skill_definition.py` — added `pipeline_config` column
- `repositories/skill_definition_repository.py` — serialize/deserialize pipeline_config
- `schemas/skill_definition.py` — added `pipeline_result` to SkillExecuteResponse
- `routers/my_skills.py` — added `POST /from-pipeline` + SkillFromPipelineRequest
- `routers/agent_execute_router.py` — pipeline skill response path
- `services/skill_executor_service.py` — `_execute_pipeline_skill()` method
- `services/agent_orchestrator_v2/nodes/tool_execute.py` — pipeline skill render card

**Frontend (TypeScript):**
- `components/shell/AppShell.tsx` — resizable panels (Group/Panel/Separator)
- `components/copilot/AICopilot.tsx` — pipeline save state + handler
- `components/copilot/PipelineConsole.tsx` — "Save as Skill" button
- `components/copilot/ChartExplorer.tsx` — histogram, box plot, heatmap, scatter, rangeslider
- `components/layout/DataExplorerPanel.tsx` — fluid typography
- `components/layout/Topbar.tsx` — fluid typography
- `app/globals.css` — CSS design tokens
- `app/api/admin/my-skills/from-pipeline/route.ts` — proxy route (new)
- `e2e/playwright.config.ts` — Playwright config (new)
- `e2e/smoke.spec.ts` — smoke tests (new)
- `e2e/data-explorer.spec.ts` — DataExplorer tests (new)
- `package.json` — added react-resizable-panels, @playwright/test, e2e scripts
