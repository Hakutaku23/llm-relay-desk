export type TestProtocol = 'openai' | 'ollama-chat' | 'ollama-generate'
export type TaskType = 'player_npc_dialogue' | 'dynamic_event_world_state'
export interface TestRequest { protocol: TestProtocol; model: string; message: string; stream: boolean; reasoning: boolean; reasoningEffort: ''|'none'|'low'|'medium'|'high'|'max'; taskType: TaskType; temperature: number; maxTokens: number }
export interface TestResult { reasoning: string; content: string; raw: unknown; usage: Record<string, unknown>|null; elapsedMs: number; interrupted: boolean }
export interface ConnectivityResult { ok: boolean; elapsedMs: number; protocol: string; models: string[]; raw: unknown }
