/**
 * File-based JSON store for admin data.
 * Reads/writes from <project-root>/data/*.json
 * Initialises from static defaults on first run.
 */
import fs from "fs";
import path from "path";
import { MCP_CATALOG, MCPDefinition } from "@/mcp/catalog";

const DATA_DIR = path.join(process.cwd(), "data");

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function storePath(name: string) {
  return path.join(DATA_DIR, `${name}.json`);
}

export function readStore<T>(name: string, defaultValue: T): T {
  ensureDataDir();
  const file = storePath(name);
  if (!fs.existsSync(file)) {
    fs.writeFileSync(file, JSON.stringify(defaultValue, null, 2));
    return defaultValue;
  }
  return JSON.parse(fs.readFileSync(file, "utf-8")) as T;
}

export function writeStore<T>(name: string, data: T): void {
  ensureDataDir();
  fs.writeFileSync(storePath(name), JSON.stringify(data, null, 2));
}

// ---------------------------------------------------------------------------
// MCP store
// ---------------------------------------------------------------------------

export interface StoredMCP extends MCPDefinition {
  id: string;
  created_at: string;
  updated_at: string;
}

function defaultMcps(): StoredMCP[] {
  return MCP_CATALOG.map((m, i) => ({
    ...m,
    id: `mcp-${String(i + 1).padStart(3, "0")}`,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }));
}

export function readMcps(): StoredMCP[] {
  const stored = readStore<StoredMCP[]>("mcps", defaultMcps());
  // Backward-compat: merge new fields from catalog if stored entries are missing them
  const catalogMap = new Map(MCP_CATALOG.map((m) => [m.name, m]));
  return stored.map((m) => {
    const catalog = catalogMap.get(m.name);
    return {
      usage_example: "",
      output_description: "",
      ...(catalog ?? {}),
      ...m,
    };
  });
}

export function writeMcps(mcps: StoredMCP[]): void {
  writeStore("mcps", mcps);
}

// ---------------------------------------------------------------------------
// Skill store
// ---------------------------------------------------------------------------

export interface StoredSkill {
  id: string;
  name: string;
  description: string;
  mcp_sequence: string[];
  /** 觸發條件：自由文字 */
  trigger_conditions: string;
  /** 機器可讀的觸發事件類型，例如 "spc_ooc" | "fdc_fault" | "equipment_hold" | "lot_delayed" | "" */
  event_trigger: string;
  /** 執行時注入給 LLM 的 Prompt template，支援 {data} 佔位符 */
  diagnostic_prompt: string;
  /** Skill 最終產出的格式說明（給 Agent 理解輸出結構用） */
  expected_output: string;
  created_at: string;
  updated_at: string;
}

export function readSkills(): StoredSkill[] {
  const skills = readStore<StoredSkill[]>("skills", []);
  // Backward-compat: add missing new fields with empty defaults
  return skills.map((s) => ({
    event_trigger:    "",
    diagnostic_prompt: "",
    expected_output:  "",
    ...s,
  }));
}

export function writeSkills(skills: StoredSkill[]): void {
  writeStore("skills", skills);
}

// ---------------------------------------------------------------------------
// Event Type store
// ---------------------------------------------------------------------------

export interface StoredEventType {
  id: string;
  name: string;
  severity: "info" | "warning" | "critical";
  description: string;
  created_at: string;
}

const DEFAULT_EVENT_TYPES: StoredEventType[] = [
  { id: "et-005", name: "OOC", severity: "warning", description: "SPC out-of-control event — published by Ontology Simulator via NATS", created_at: new Date().toISOString() },
];

export function readEventTypes(): StoredEventType[] {
  return readStore<StoredEventType[]>("event_types", DEFAULT_EVENT_TYPES);
}

export function writeEventTypes(types: StoredEventType[]): void {
  writeStore("event_types", types);
}
