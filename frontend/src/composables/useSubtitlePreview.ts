import { onBeforeUnmount, ref } from 'vue'
import { renderSubtitlePreview } from '@/api/subtitles'
import type { SubtitleConfig } from '@/types/subtitles'

export function useSubtitlePreview(delay=180){const url=ref(''),loading=ref(false),error=ref('');let timer:ReturnType<typeof setTimeout>|null=null,controller:AbortController|null=null
 const cleanupUrl=()=>{if(url.value){URL.revokeObjectURL(url.value);url.value=''}}
 const cancel=()=>{if(timer)clearTimeout(timer);timer=null;controller?.abort();controller=null;loading.value=false}
 const generate=async(c:SubtitleConfig)=>{cancel();controller=new AbortController();const current=controller;loading.value=true;error.value='';try{const blob=await renderSubtitlePreview(c,current.signal);if(current!==controller)return;const next=URL.createObjectURL(blob);cleanupUrl();url.value=next}catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:''}finally{if(current===controller){controller=null;loading.value=false}}}
 const schedule=(c:SubtitleConfig)=>{cancel();timer=setTimeout(()=>{timer=null;void generate(c)},delay)}
 onBeforeUnmount(()=>{cancel();cleanupUrl()});return{url,loading,error,generate,schedule,cancel}
}
