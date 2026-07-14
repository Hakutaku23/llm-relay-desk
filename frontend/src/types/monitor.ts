export type MonitorStatus='streaming'|'complete'|'error'|'cancelled'
export interface MonitorRecord{requestId:string;api:string;route:string;model:string;source:string;userAgent:string;stream:boolean;startedAt:string;finishedAt:string|null;elapsedMs:number|null;statusCode:number|null;status:MonitorStatus;content:string;reasoning:string;error:string}
export interface DebugLogSummary{id:string;timestamp:string|null;requestId:string|null;statusCode:number|null;outcome:string|null;sizeBytes:number}
export interface DebugLogStatus{enabled:boolean;directory:string;retentionFiles:number;fileCount:number;logs:DebugLogSummary[]}
