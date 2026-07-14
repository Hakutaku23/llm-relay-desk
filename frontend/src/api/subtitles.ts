import type { PositioningResult, SubtitleConfig, SubtitleContentMode, SubtitleFonts, SubtitlePosition, SubtitleTextAlign } from '@/types/subtitles'

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { ...init, headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init?.headers } })
  const value: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new Error(record(value) && typeof value.detail === 'string' ? value.detail : `Request failed with status ${response.status}.`)
  return value
}
const positions = new Set(['top_left','top_center','top_right','center_left','center','center_right','bottom_left','bottom_center','bottom_right','custom'])
const aligns = new Set(['left','center','right'])
const modes = new Set(['dialogue','all'])
const num = (v: unknown, name: string) => { if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`Malformed subtitle field: ${name}`); return v }
const bool = (v: unknown, name: string) => { if (typeof v !== 'boolean') throw new Error(`Malformed subtitle field: ${name}`); return v }
const str = (v: unknown, name: string) => { if (typeof v !== 'string') throw new Error(`Malformed subtitle field: ${name}`); return v }

export function parseSubtitleConfig(value: unknown): SubtitleConfig {
  if (!record(value)) throw new Error('Malformed subtitle configuration response')
  const position = str(value.native_popup_position, 'position'), align = str(value.native_popup_text_align, 'textAlign'), mode = str(value.native_popup_content_mode, 'contentMode')
  if (!positions.has(position) || !aligns.has(align) || !modes.has(mode) || !Array.isArray(value.native_popup_dialogue_fields) || !value.native_popup_dialogue_fields.every((v) => typeof v === 'string')) throw new Error('Malformed subtitle configuration response')
  return {
    enabled: bool(value.native_popup_enabled, 'enabled'), closeSeconds: num(value.native_popup_close_seconds, 'closeSeconds'), position: position as SubtitlePosition,
    offsetX: num(value.native_popup_offset_x, 'offsetX'), offsetY: num(value.native_popup_offset_y, 'offsetY'), customX: num(value.native_popup_custom_x, 'customX'), customY: num(value.native_popup_custom_y, 'customY'),
    width: num(value.native_popup_width, 'width'), height: num(value.native_popup_height, 'height'), fontSize: num(value.native_popup_font_size, 'fontSize'), fontFamily: str(value.native_popup_font_family, 'fontFamily'),
    textAlign: align as SubtitleTextAlign, textOpacity: num(value.native_popup_text_opacity, 'textOpacity'), backgroundOpacity: num(value.native_popup_background_opacity, 'backgroundOpacity'),
    contentMode: mode as SubtitleContentMode, dialogueFields: [...value.native_popup_dialogue_fields] as string[], plainTextFallback: bool(value.native_popup_plain_text_fallback, 'plainTextFallback'), forceUpstreamStream: bool(value.native_popup_force_upstream_stream, 'forceUpstreamStream'), showReasoning: bool(value.native_popup_show_reasoning, 'showReasoning'), clickThrough: bool(value.native_popup_click_through, 'clickThrough'),
    textShadow: bool(value.native_popup_text_shadow, 'textShadow'), shadowColor: str(value.native_popup_shadow_color, 'shadowColor'), shadowOffset: num(value.native_popup_shadow_offset, 'shadowOffset'), textOutline: bool(value.native_popup_text_outline, 'textOutline'), outlineColor: str(value.native_popup_outline_color, 'outlineColor'), outlineWidth: num(value.native_popup_outline_width, 'outlineWidth'),
    backgroundColor: str(value.native_popup_background_color, 'backgroundColor'), textColor: str(value.native_popup_text_color, 'textColor'), mutedColor: str(value.native_popup_muted_color, 'mutedColor'), borderColor: str(value.native_popup_border_color, 'borderColor'), errorColor: str(value.native_popup_error_color, 'errorColor'),
  }
}
export function subtitlePayload(c: SubtitleConfig) { return { native_popup_enabled:c.enabled,native_popup_close_seconds:c.closeSeconds,native_popup_position:c.position,native_popup_offset_x:c.offsetX,native_popup_offset_y:c.offsetY,native_popup_custom_x:c.customX,native_popup_custom_y:c.customY,native_popup_width:c.width,native_popup_height:c.height,native_popup_font_size:c.fontSize,native_popup_font_family:c.fontFamily,native_popup_text_align:c.textAlign,native_popup_text_opacity:c.textOpacity,native_popup_background_opacity:c.backgroundOpacity,native_popup_content_mode:c.contentMode,native_popup_dialogue_fields:c.dialogueFields,native_popup_plain_text_fallback:c.plainTextFallback,native_popup_force_upstream_stream:c.forceUpstreamStream,native_popup_show_reasoning:c.showReasoning,native_popup_click_through:c.clickThrough,native_popup_text_shadow:c.textShadow,native_popup_shadow_color:c.shadowColor,native_popup_shadow_offset:c.shadowOffset,native_popup_text_outline:c.textOutline,native_popup_outline_color:c.outlineColor,native_popup_outline_width:c.outlineWidth,native_popup_background_color:c.backgroundColor,native_popup_text_color:c.textColor,native_popup_muted_color:c.mutedColor,native_popup_border_color:c.borderColor,native_popup_error_color:c.errorColor } }
export async function getSubtitleConfig() { return parseSubtitleConfig(await request('/admin/subtitle-config')) }
export async function saveSubtitleConfig(c: SubtitleConfig) { const v=await request('/admin/subtitle-config',{method:'PUT',body:JSON.stringify(subtitlePayload(c))}); if(!record(v)||v.ok!==true)throw new Error('Malformed subtitle save response'); return parseSubtitleConfig(v.config) }
export async function getSubtitleFonts(): Promise<SubtitleFonts> { const v=await request('/admin/subtitle-fonts'); if(!record(v)||!Array.isArray(v.fonts)||!v.fonts.every(x=>typeof x==='string'))throw new Error('Malformed font response'); return {fonts:[...v.fonts] as string[],platform:typeof v.platform==='string'?v.platform:null} }
export async function renderSubtitlePreview(c: SubtitleConfig, signal: AbortSignal) { const response=await fetch('/admin/subtitle-preview.png',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(subtitlePayload(c)),signal,cache:'no-store'}); if(!response.ok)throw new Error(`Preview failed with status ${response.status}.`); return response.blob() }
export async function startSubtitlePositioning(): Promise<PositioningResult> { const v=await request('/admin/subtitle-positioning/start',{method:'POST'}); if(!record(v)||typeof v.request_id!=='string'||typeof v.positioning!=='boolean')throw new Error('Malformed positioning response'); return {requestId:v.request_id,positioning:v.positioning} }
