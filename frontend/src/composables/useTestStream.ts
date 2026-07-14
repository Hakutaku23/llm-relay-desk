import { onBeforeUnmount, ref } from 'vue'
import type { TestResult } from '@/types/apiTest'

const text = (value: unknown): string => typeof value === 'string' ? value : Array.isArray(value) ? value.map((item) => typeof item === 'string' ? item : typeof item === 'object' && item && 'text' in item && typeof item.text === 'string' ? item.text : '').join('') : ''
const reasoning = (value: Record<string, unknown>) => text(value.reasoning_content ?? value.reasoning ?? value.thinking)

export function useTestStream() {
  const controller = ref<AbortController | null>(null)
  const active = ref(false)
  function cancel() { controller.value?.abort(); controller.value = null; active.value = false }
  async function read(response: Response, protocol: 'sse'|'ndjson', started: number, onUpdate: (result: TestResult)=>void): Promise<TestResult> {
    if (!response.body) throw new Error('Readable response stream is unavailable.')
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='', doneMarker=false
    const result:TestResult={reasoning:'',content:'',raw:[],usage:null,elapsedMs:0,interrupted:false}; const events:unknown[]=[]
    const consume=(block:string)=>{ const source=protocol==='sse'?block.split(/\r?\n/).filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n').trim():block.trim(); if(!source)return; if(source==='[DONE]'){doneMarker=true;return} let event:unknown; try{event=JSON.parse(source)}catch{throw new Error(protocol==='sse'?'Malformed SSE response.':'Malformed NDJSON response.')} events.push(event); if(typeof event!=='object'||!event)return; const record=event as Record<string,unknown>; if(record.usage&&typeof record.usage==='object')result.usage=record.usage as Record<string,unknown>; if(protocol==='sse'){const choices=Array.isArray(record.choices)?record.choices:[]; const choice=choices[0] as Record<string,unknown>|undefined; const delta=(choice?.delta??choice?.message??{}) as Record<string,unknown>; result.reasoning+=reasoning(delta); result.content+=text(delta.content??delta.text)}else{const message=(record.message??{}) as Record<string,unknown>; result.reasoning+=reasoning(message)+reasoning(record); result.content+=text(message.content??record.response); if(record.done===true)doneMarker=true} result.raw=[...events]; result.elapsedMs=Math.round(performance.now()-started); onUpdate({...result}) }
    try{while(true){const chunk=await reader.read();buffer+=decoder.decode(chunk.value??new Uint8Array(),{stream:!chunk.done}); const separator=protocol==='sse'?/\r?\n\r?\n/:/\r?\n/; let match; while((match=separator.exec(buffer))&&match.index!==undefined){const block=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);consume(block)} if(chunk.done)break} if(buffer.trim())consume(buffer); result.interrupted=!doneMarker; result.elapsedMs=Math.round(performance.now()-started); onUpdate({...result}); return result} finally{reader.releaseLock()}
  }
  onBeforeUnmount(cancel)
  return { controller, active, cancel, read }
}
