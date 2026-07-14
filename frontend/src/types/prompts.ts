export interface PromptProfiles { active: string|null; names: string[]; profiles: Record<string,string> }
export interface PromptExport { format_version: 1; active: string|null; profiles: Array<{id:string;name:string;content:string}> }
export interface TaskIsolationConfig { promptEnabled:boolean; injectionMode:'normal'|'bannerlord'; playerFriendly:boolean; playerDialogue:boolean; actionDialogue:boolean; npcDialogue:boolean }
