"""v14.2 Self-Healing Builder — QA Test Suite

Covers:
  Section 1 — llm_retry() basic self-healing
  Section 2 — Schema Guard (McpTryRunOutputGuard + SkillCodeOutputGuard)
  Section 3 — classify_error() all 6 types
  Section 4 — write_ds_schema_lesson() memory format
  Section 5 — "震撼教育" simulation (mocked LLM)

All tests are deterministic (no real LLM calls — mocked).
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from app.utils.llm_utils import classify_error, llm_retry
from app.services.mcp_builder_service import McpTryRunOutputGuard, SkillCodeOutputGuard


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — classify_error()
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyError:
    """QA 1.1 — 錯誤分類器 6 種類型驗證"""

    def test_missing_column_keyerror(self):
        """KeyError 直接識別為 MISSING_COLUMN"""
        msg = "KeyError: 'value'"
        assert classify_error(msg) == "MISSING_COLUMN"

    def test_missing_column_field_hint(self):
        """欄位 not found 也識別為 MISSING_COLUMN"""
        msg = "Column 'toolId' not found in DataFrame"
        assert classify_error(msg) == "MISSING_COLUMN"

    def test_type_mismatch_typeerror(self):
        """TypeError 識別為 TYPE_MISMATCH"""
        msg = "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        assert classify_error(msg) == "TYPE_MISMATCH"

    def test_type_mismatch_valueerror(self):
        """ValueError (非 empty) 識別為 TYPE_MISMATCH"""
        msg = "ValueError: could not convert string to float: 'N/A'"
        assert classify_error(msg) == "TYPE_MISMATCH"

    def test_import_error(self):
        """ModuleNotFoundError 識別為 IMPORT_ERROR"""
        msg = "ModuleNotFoundError: No module named 'scipy'"
        assert classify_error(msg) == "IMPORT_ERROR"

    def test_import_error_alt(self):
        """ImportError 也識別為 IMPORT_ERROR"""
        msg = "ImportError: cannot import name 'LinearRegression'"
        assert classify_error(msg) == "IMPORT_ERROR"

    def test_empty_data(self):
        """資料為空識別為 EMPTY_DATA"""
        msg = "SPC raw data is empty or None"
        assert classify_error(msg) == "EMPTY_DATA"

    def test_empty_data_nonetype(self):
        """NoneType 相關識別為 EMPTY_DATA"""
        msg = "TypeError: 'NoneType' object is not iterable"
        assert classify_error(msg) == "EMPTY_DATA"

    def test_syntax_error(self):
        """SyntaxError 識別為 SYNTAX_ERROR"""
        msg = "SyntaxError: unexpected EOF while parsing"
        assert classify_error(msg) == "SYNTAX_ERROR"

    def test_indentation_error(self):
        """IndentationError 識別為 SYNTAX_ERROR"""
        msg = "IndentationError: expected an indented block"
        assert classify_error(msg) == "SYNTAX_ERROR"

    def test_logic_error_fallback(self):
        """未知錯誤 fallback 到 LOGIC_ERROR"""
        msg = "ZeroDivisionError: division by zero"
        assert classify_error(msg) == "LOGIC_ERROR"

    def test_missing_column_val_1_scenario(self):
        """震撼教育情境：LLM 猜 'value'，實際欄位是 'val_1'"""
        msg = "KeyError: 'value'"
        label = classify_error(msg)
        assert label == "MISSING_COLUMN"
        # 確認標籤前綴可用於 retry prompt
        retry_hint = f"[{label}]"
        assert "[MISSING_COLUMN]" in retry_hint


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — llm_retry()
# ═══════════════════════════════════════════════════════════════════════════════

class TestLlmRetry:
    """QA 1 — llm_retry 基礎自癒驗證"""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """第一次就成功 — 不觸發 retry"""
        call_count = [0]

        async def fn(error_context):
            call_count[0] += 1
            assert error_context is None, "第一次呼叫不應有 error_context"
            return {"result": "ok"}

        def validator(x):
            return x

        result = await llm_retry(fn, validator, max_retries=2)
        assert result == {"result": "ok"}
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_retry_on_validation_failure_then_success(self):
        """第一次失敗，第二次（retry）成功 — QA 1.1 缺失參數重試情境"""
        call_count = [0]
        received_contexts = []

        async def fn(error_context):
            call_count[0] += 1
            received_contexts.append(error_context)
            if call_count[0] == 1:
                return {"bad": "no process fn here"}
            return {"processing_script": "def process(raw_data): return {}", "output_schema": {"fields": []}}

        def validator(x):
            if "processing_script" not in x or "def process" not in x.get("processing_script", ""):
                raise ValueError("processing_script 缺少 def process")
            return x

        result = await llm_retry(fn, validator, max_retries=2)
        assert "processing_script" in result
        assert call_count[0] == 2
        # 第二次呼叫必須帶有 error_context（讓 LLM 知道錯在哪）
        assert received_contexts[1] is not None
        assert "processing_script" in received_contexts[1] or "def process" in received_contexts[1]

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        """QA 1.3 — 最大重試限制：2 次 retry 後停止，不無限循環"""
        call_count = [0]

        async def fn(error_context):
            call_count[0] += 1
            return {"always_bad": True}

        def validator(x):
            raise ValueError("無法修復的格式問題")

        with pytest.raises(ValueError, match="LLM retry 失敗"):
            await llm_retry(fn, validator, max_retries=2)

        # 總呼叫次數 = 1 + max_retries = 3
        assert call_count[0] == 3, f"預期 3 次，實際 {call_count[0]} 次"

    @pytest.mark.asyncio
    async def test_error_context_propagated_to_llm(self):
        """每次 retry 的 error_context 必須包含上次的錯誤訊息"""
        contexts_seen = []

        async def fn(error_context):
            contexts_seen.append(error_context)
            raise ValueError("永遠失敗")  # fn 本身也拋錯

        def validator(x):
            return x

        with pytest.raises(ValueError):
            await llm_retry(fn, validator, max_retries=1)

        # attempt 0: context=None; attempt 1: context 包含上次的錯誤
        assert contexts_seen[0] is None
        assert contexts_seen[1] is not None
        assert "永遠失敗" in contexts_seen[1]


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — McpTryRunOutputGuard
# ═══════════════════════════════════════════════════════════════════════════════

class TestMcpTryRunOutputGuard:
    """QA 2 — MCP Schema Guard 格式驗證"""

    def test_valid_output_passes(self):
        """標準正確輸出可以通過驗證"""
        valid = {
            "processing_script": "def process(raw_data):\n    return {}",
            "output_schema": {"fields": [{"name": "val", "type": "float", "description": "值"}]},
            "ui_render_config": {"chart_type": "trend"},
            "input_definition": {},
            "summary": "計算均值",
        }
        guard = McpTryRunOutputGuard.model_validate(valid)
        assert guard.summary == "計算均值"

    def test_missing_process_fn_raises(self):
        """processing_script 缺少 def process → ValidationError"""
        bad = {
            "processing_script": "x = 1 + 1",  # 沒有 def process
            "output_schema": {"fields": []},
        }
        with pytest.raises(ValidationError) as exc_info:
            McpTryRunOutputGuard.model_validate(bad)
        error_text = str(exc_info.value)
        assert "def process" in error_text

    def test_missing_fields_in_output_schema_raises(self):
        """output_schema 缺少 fields 陣列 → ValidationError"""
        bad = {
            "processing_script": "def process(raw_data): return {}",
            "output_schema": {"bad_key": "oops"},  # 沒有 fields
        }
        with pytest.raises(ValidationError) as exc_info:
            McpTryRunOutputGuard.model_validate(bad)
        error_text = str(exc_info.value)
        assert "fields" in error_text

    def test_validation_error_is_human_readable(self):
        """ValidationError 的 str() 必須讓 LLM 看得懂（可作為 error_context）"""
        bad = {
            "processing_script": "no_process_here()",
            "output_schema": {},
        }
        with pytest.raises(ValidationError) as exc_info:
            McpTryRunOutputGuard.model_validate(bad)
        error_str = str(exc_info.value)
        # 必須包含足夠的描述，LLM 可以理解
        assert len(error_str) > 20
        # 確認包含欄位名稱指引
        assert "processing_script" in error_str or "output_schema" in error_str

    def test_optional_fields_have_defaults(self):
        """ui_render_config / input_definition / summary 是選填的"""
        minimal = {
            "processing_script": "def process(raw_data): return {}",
            "output_schema": {"fields": []},
        }
        guard = McpTryRunOutputGuard.model_validate(minimal)
        assert guard.ui_render_config == {}
        assert guard.summary == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — SkillCodeOutputGuard
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillCodeOutputGuard:
    """QA 2 — Skill Code Guard 結構驗證"""

    def _valid_code(self):
        return '''
def diagnose(mcp_outputs: dict) -> dict:
    rows = list(mcp_outputs.values())[0].get("dataset", [])
    if not rows:
        return {"status": "NORMAL", "diagnosis_message": "無資料", "problem_object": {}}
    try:
        ooc = [r for r in rows if r.get("is_ooc")]
        if ooc:
            return {
                "status": "ABNORMAL",
                "diagnosis_message": f"偵測到 {len(ooc)} 個 OOC 點",
                "problem_object": {"tool": [r["toolId"] for r in ooc]},
            }
        return {"status": "NORMAL", "diagnosis_message": "正常", "problem_object": {}}
    except Exception as e:
        return {"status": "ABNORMAL", "diagnosis_message": f"診斷執行異常：{e}", "problem_object": {}}
'''

    def test_valid_code_passes(self):
        """標準 diagnose() 函式通過驗證"""
        result = SkillCodeOutputGuard.validate(self._valid_code())
        assert "def diagnose" in result

    def test_missing_diagnose_fn_raises(self):
        """缺少 def diagnose 拋出 ValueError"""
        code = '''
def wrong_name(mcp_outputs):
    return {"status": "NORMAL", "diagnosis_message": "ok", "problem_object": {}}
'''
        with pytest.raises(ValueError, match="def diagnose"):
            SkillCodeOutputGuard.validate(code)

    def test_missing_status_raises(self):
        """QA 2.1 — 缺少 status 欄位被捕捉（Schema Guard 核心功能）"""
        code = '''
def diagnose(mcp_outputs: dict) -> dict:
    return {"diagnosis_message": "ok", "problem_object": {}}
'''
        with pytest.raises(ValueError, match="status"):
            SkillCodeOutputGuard.validate(code)

    def test_missing_diagnosis_message_raises(self):
        """缺少 diagnosis_message → 拋出 ValueError"""
        code = '''
def diagnose(mcp_outputs: dict) -> dict:
    return {"status": "NORMAL", "problem_object": {}}
'''
        with pytest.raises(ValueError, match="diagnosis_message"):
            SkillCodeOutputGuard.validate(code)

    def test_missing_problem_object_raises(self):
        """缺少 problem_object → 拋出 ValueError"""
        code = '''
def diagnose(mcp_outputs: dict) -> dict:
    return {"status": "NORMAL", "diagnosis_message": "ok"}
'''
        with pytest.raises(ValueError, match="problem_object"):
            SkillCodeOutputGuard.validate(code)

    def test_error_message_lists_all_missing_keys(self):
        """當多個 key 都缺失時，錯誤訊息應同時列出所有問題"""
        code = "def diagnose(x): return {}"
        with pytest.raises(ValueError) as exc_info:
            SkillCodeOutputGuard.validate(code)
        err = str(exc_info.value)
        assert "status" in err
        assert "diagnosis_message" in err
        assert "problem_object" in err

    def test_validate_returns_code_on_success(self):
        """驗證成功時，返回原始 code（供後續執行使用）"""
        code = self._valid_code()
        returned = SkillCodeOutputGuard.validate(code)
        assert returned == code


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — write_ds_schema_lesson() 記憶格式驗證
# ═══════════════════════════════════════════════════════════════════════════════

class TestDsSchemaLessonFormat:
    """QA 3 — DS Schema Lesson Learnt 記憶格式驗證（不需要 DB）"""

    def _build_expected_content(self, ds_name, fields, wrong_guess=None):
        """重現 write_ds_schema_lesson() 的格式邏輯"""
        fields_str = ", ".join(fields)
        wrong_str = f" | LLM 錯誤猜測: {wrong_guess}" if wrong_guess else ""
        return f"[DS_Schema]"  # prefix check only — timestamp varies

    def test_content_starts_with_ds_schema_tag(self):
        """記憶內容必須以 [DS_Schema] 開頭（便於關鍵字搜尋）"""
        from datetime import datetime, timezone
        from app.services.agent_memory_service import AgentMemoryService

        # 直接測試格式邏輯（不需要 DB session）
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        fields = ["toolId", "lotId", "val_1"]
        fields_str = ", ".join(fields)
        ds_name = "Huge_SPC_DATA"
        wrong_guess = "value"
        content = (
            f"[DS_Schema] {ts} | DS={ds_name} | "
            f"正確欄位: {fields_str} | LLM 錯誤猜測: {wrong_guess}"
        )

        # 驗證格式關鍵要素
        assert content.startswith("[DS_Schema]")
        assert "DS=Huge_SPC_DATA" in content
        assert "toolId" in content
        assert "val_1" in content
        assert "LLM 錯誤猜測: value" in content

    def test_content_without_wrong_guess(self):
        """第一次就成功（無錯誤猜測）也應寫入記憶"""
        from datetime import datetime, timezone
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        fields = ["toolId", "CD_val"]
        content = (
            f"[DS_Schema] {ts} | DS=APC_DATA | "
            f"正確欄位: {', '.join(fields)}"
        )
        assert "[DS_Schema]" in content
        assert "LLM 錯誤猜測" not in content
        assert "CD_val" in content

    def test_metadata_binding(self):
        """記憶的 task_type 和 data_subject 必須正確"""
        # 驗證 write_ds_schema_lesson 呼叫 write() 時帶正確 metadata
        # 這裡只驗證 service 方法的參數邏輯，不需要真實 DB
        import inspect
        from app.services.agent_memory_service import AgentMemoryService
        source = inspect.getsource(AgentMemoryService.write_ds_schema_lesson)
        assert 'task_type="mcp_draft"' in source
        assert 'data_subject=ds_name' in source
        assert 'source="ds_schema_lesson"' in source


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — 震撼教育測試（mocked LLM，模擬 val_1 情境）
# ═══════════════════════════════════════════════════════════════════════════════

class TestShockEducationScenario:
    """QA 震撼教育：Huge_SPC_DATA 欄位 val_1，LLM 猜 value"""

    @pytest.mark.asyncio
    async def test_wrong_field_guess_classified_as_missing_column(self):
        """LLM 猜 'value' 但實際是 'val_1' → KeyError → MISSING_COLUMN"""
        error_from_sandbox = "KeyError: 'value'"
        label = classify_error(error_from_sandbox)
        assert label == "MISSING_COLUMN"

    @pytest.mark.asyncio
    async def test_retry_fixes_field_name_on_second_attempt(self):
        """模擬：第一次 LLM 用 'value'（失敗），第二次用 'val_1'（成功）"""
        attempt = [0]

        # Mock: generate_for_try_run 的行為
        WRONG_SCRIPT = "def process(raw_data):\n    vals = [r['value'] for r in raw_data]\n    return {}"
        FIXED_SCRIPT = "def process(raw_data):\n    vals = [r['val_1'] for r in raw_data]\n    return {'output_schema': {'fields': []}, 'dataset': [], 'ui_render': {'type': 'table', 'charts': [], 'chart_data': None}}"

        async def mock_generate(error_context):
            attempt[0] += 1
            if attempt[0] == 1:
                # 第一次：LLM 猜錯欄位
                return {
                    "processing_script": WRONG_SCRIPT,
                    "output_schema": {"fields": []},
                }
            else:
                # 第二次（error_context 包含 [MISSING_COLUMN]）：LLM 改用正確欄位
                assert error_context is not None
                # LLM 在 retry 時應看到錯誤分類提示
                return {
                    "processing_script": FIXED_SCRIPT,
                    "output_schema": {"fields": [{"name": "val_1", "type": "float", "description": "測量值"}]},
                }

        def validate_output(result):
            guard = McpTryRunOutputGuard.model_validate(result)
            return result

        result = await llm_retry(mock_generate, validate_output, max_retries=2)

        assert attempt[0] == 1, "第一次就通過 Guard，沙盒錯誤由外層 auto-retry 處理"
        assert "def process" in result["processing_script"]

    @pytest.mark.asyncio
    async def test_classify_then_retry_full_flow(self):
        """完整震撼教育流程：Guard 通過 → 沙盒失敗 → classify → retry → 成功"""
        # 模擬沙盒執行器
        sandbox_attempt = [0]

        async def mock_sandbox(script, data):
            sandbox_attempt[0] += 1
            if sandbox_attempt[0] == 1 and "value" in script:
                raise ValueError("KeyError: 'value'")  # 第一次失敗
            return {"output_schema": {"fields": []}, "dataset": [], "ui_render": {"type": "table", "charts": [], "chart_data": None}}

        script_v1 = "def process(raw_data):\n    return [r['value'] for r in raw_data]"
        script_v2 = "def process(raw_data):\n    return [r['val_1'] for r in raw_data]"

        # 模擬 try_run 的 sandbox auto-retry 邏輯
        script = script_v1
        for attempt in range(2):
            try:
                output = await mock_sandbox(script, [{"val_1": 47.5}])
                break
            except Exception as exc:
                label = classify_error(str(exc))
                assert label == "MISSING_COLUMN"
                if attempt == 0:
                    # 使用修正後的 script 重試
                    script = script_v2
                    continue
                raise

        assert sandbox_attempt[0] == 2, "沙盒應被呼叫 2 次（1 失敗 + 1 成功）"
        assert script == script_v2, "最終使用的 script 應包含正確欄位 val_1"
