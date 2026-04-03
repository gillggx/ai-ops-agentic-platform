/**
 * POST /api/admin/agent
 * Admin AI 助理：協助設計 MCP / Skill 定義。
 * 直接呼叫 Claude API（非 aiops-agent loop），回傳 SSE stream。
 */
import { NextRequest } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { readMcps, readSkills } from "@/lib/store";

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

function buildSystemPrompt(): string {
  const mcps = readMcps();
  const skills = readSkills();

  const mcpList = mcps
    .map((m) => `- ${m.name} (${m.is_handoff ? "HANDOFF" : "DATA"}): ${m.description.split("\n")[0]}`)
    .join("\n");

  const skillList = skills.length
    ? skills.map((s) => `- ${s.name}: ${s.description} [MCPs: ${s.mcp_sequence.join(" → ")}]`).join("\n")
    : "（尚無 Skill）";

  return `你是 AIOps Admin AI 助理，專門協助工程師設計和建立 MCP（工具定義）與 Skill（技能定義）。

## 你的角色
- 協助使用者設計結構良好、LLM 容易正確呼叫的 MCP 與 Skill 定義
- 當使用者描述需求時，生成完整的定義 JSON
- 給出建議時要具體、可直接使用，不要說廢話

## 現有 MCP 清單
${mcpList}

## 現有 Skill 清單
${skillList}

## MCP 定義格式（JSON）
當使用者要建立/修改 MCP 時，輸出 JSON block 並用 <fill_mcp_form> 標籤包住：
<fill_mcp_form>
{
  "name": "snake_case_name",
  "description": "【簡短標題】詳細說明...\\n\\n回傳欄位說明：\\n- field: 說明\\n\\n典型使用情境：\\n① ...\\n② ...\\n\\n⚠️ 必填：...",
  "is_handoff": false,
  "parameters": {
    "param_name": { "type": "string", "description": "說明", "required": true }
  },
  "usage_example": "何時呼叫、如何用回傳值",
  "output_description": "回傳 { field1, field2, ... } 結構說明"
}
</fill_mcp_form>

## Skill 定義格式（JSON）
當使用者要建立/修改 Skill 時，輸出 JSON block 並用 <fill_skill_form> 標籤包住：
<fill_skill_form>
{
  "name": "snake_case_skill_name",
  "description": "技能的一句話描述",
  "mcp_sequence": ["mcp_name_1", "mcp_name_2"],
  "event_trigger": "spc_ooc",
  "trigger_conditions": "當 SPC OOC 事件發生，需要診斷根因時",
  "diagnostic_prompt": "你是半導體製程 SPC 分析專家。\\n\\n以下是從各 MCP 收集到的資料：\\n{data}\\n\\n請分析根因並給出建議。",
  "expected_output": "{ root_cause: string, confidence: number, recommended_actions: string[] }"
}
</fill_skill_form>

## event_trigger 可用值
- "" → 不綁定事件，手動呼叫
- "spc_ooc" → SPC 超出管制限
- "fdc_fault" → FDC 偵測到設備故障
- "equipment_hold" → 設備進入 Hold 狀態
- "lot_delayed" → 批次延遲

## 原則
- description 要豐富、有回傳欄位說明、典型使用情境、⚠️ 注意事項
- mcp_sequence 只能使用現有 MCP 清單中的名稱
- diagnostic_prompt 要具體，說明角色、資料格式、期望輸出
- 回應語言：中文為主，程式碼/JSON 用英文`;
}

export async function POST(req: NextRequest) {
  const { message, history } = await req.json() as {
    message: string;
    history?: { role: "user" | "assistant"; content: string }[];
  };

  const systemPrompt = buildSystemPrompt();

  const messages: Anthropic.MessageParam[] = [
    ...(history ?? []).map((h) => ({
      role: h.role as "user" | "assistant",
      content: h.content,
    })),
    { role: "user", content: message },
  ];

  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const response = await client.messages.stream({
          model: "claude-haiku-4-5-20251001",
          max_tokens: 2048,
          system: systemPrompt,
          messages,
        });

        for await (const chunk of response) {
          if (chunk.type === "content_block_delta" && chunk.delta.type === "text_delta") {
            const data = JSON.stringify({ type: "text", text: chunk.delta.text });
            controller.enqueue(encoder.encode(`data: ${data}\n\n`));
          }
        }

        controller.enqueue(encoder.encode(`data: {"type":"done"}\n\n`));
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "error", message: msg })}\n\n`));
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}
