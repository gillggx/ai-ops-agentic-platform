#!/bin/bash
# i18n 防回歸檢查 — 已遷移的檔案不得再出現 CJK 字面字串，
# 新字串必須走 messages/ catalog。用 python 實作（macOS/Linux grep 差異）。
#
# 用法：bash scripts/check-i18n-literals.sh   （exit 0 = 乾淨）
cd "$(dirname "$0")/.." || exit 1
python3 - <<'EOF'
import re, sys, pathlib

# 全乾淨檔：任何 CJK 都不允許（註解除外）
CLEAN = [
    "src/components/copilot/BuildFlowCards.tsx",
    "src/components/layout/Topbar.tsx",
    "src/components/pipeline-builder/v30/PhaseTimeline.tsx",
]
# 部分遷移檔：允許 i18n-TODO 區塊與 addLog/makeLog（內部 log）行
PARTIAL = [
    "src/components/copilot/AgentConsole.tsx",
    "src/components/copilot/AIAgentPanel.tsx",
]

CJK = re.compile(r"[一-鿿぀-ヿ]")
COMMENT = re.compile(r"^\s*(//|\*|/\*)")
ALLOW_PARTIAL = re.compile(r"i18n-TODO|addLog|makeLog|console\.(log|warn|error)")

fail = False
for group, allow_partial in ((CLEAN, False), (PARTIAL, True)):
    for rel in group:
        p = pathlib.Path(rel)
        if not p.exists():
            continue
        in_todo_block = False
        in_block_comment = False
        hits = []
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "i18n-TODO-START" in line: in_todo_block = True
            if "i18n-TODO-END" in line: in_todo_block = False
            # 剝註解：block comment 狀態機 + 行內 {/* */} 與尾隨 //
            code = line
            if in_block_comment:
                if "*/" in code:
                    code = code.split("*/", 1)[1]; in_block_comment = False
                else:
                    continue
            code = re.sub(r"\{?/\*.*?\*/\}?", "", code)
            if "/*" in code:
                code = code.split("/*", 1)[0]; in_block_comment = True
            code = re.sub(r"//.*$", "", code)
            if not CJK.search(code): continue
            if COMMENT.match(line): continue
            if "i18n-exempt" in line: continue
            if in_todo_block: continue
            if allow_partial and ALLOW_PARTIAL.search(line): continue
            hits.append(f"  {i}: {line.strip()[:90]}")
        if hits:
            fail = True
            print(f"[FAIL] {rel} 含未抽取的 CJK 字串（{len(hits)} 行）：")
            print("\n".join(hits[:10]))

if not fail:
    print("[ok] migrated files clean")
sys.exit(1 if fail else 0)
EOF
