/**
 * API client for the Phase 6 Skill Builder Copilot endpoints.
 * All requests require a valid JWT stored in localStorage.
 */

const API_BASE = '/api/v1/builder'
const TOKEN_KEY = 'glassbox_token'

function getHeaders() {
  const token = localStorage.getItem(TOKEN_KEY)
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
}

async function request(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text}`)
  }
  return res.json()
}

/**
 * Generate AI PE diagnostic logic suggestions for a given event schema.
 * @param {object} eventSchema - The SPC event schema object
 * @param {string} [context]   - Optional extra context
 * @returns {Promise<{suggestions: string[], event_analysis: string}>}
 */
export function suggestLogic(eventSchema, context = '') {
  return request('/suggest-logic', { event_schema: eventSchema, context })
}

/**
 * Semantically map event attributes to MCP tool input parameters.
 * @param {object} eventSchema     - The SPC event schema object
 * @param {object} toolInputSchema - The MCP tool's input JSON schema
 * @returns {Promise<{mappings: Array, unmapped_tool_params: string[], summary: string}>}
 */
export function autoMap(eventSchema, toolInputSchema) {
  return request('/auto-map', { event_schema: eventSchema, tool_input_schema: toolInputSchema })
}

/**
 * Validate that a diagnostic prompt only references fields the tool provides.
 * @param {string} userPrompt      - The diagnostic logic text to validate
 * @param {object} toolOutputSchema - Combined output schema of selected tools
 * @returns {Promise<{is_valid: boolean, issues: string[], suggestions: string[], validated_fields: string[]}>}
 */
export function validateLogic(userPrompt, toolOutputSchema) {
  return request('/validate-logic', { user_prompt: userPrompt, tool_output_schema: toolOutputSchema })
}
