export type SubtitlePosition = 'top_left' | 'top_center' | 'top_right' | 'center_left' | 'center' | 'center_right' | 'bottom_left' | 'bottom_center' | 'bottom_right' | 'custom'
export type SubtitleTextAlign = 'left' | 'center' | 'right'
export type SubtitleContentMode = 'dialogue' | 'all'

export interface SubtitleConfig {
  enabled: boolean; closeSeconds: number; position: SubtitlePosition
  offsetX: number; offsetY: number; customX: number; customY: number
  width: number; height: number; fontSize: number; fontFamily: string
  textAlign: SubtitleTextAlign; textOpacity: number; backgroundOpacity: number
  contentMode: SubtitleContentMode; dialogueFields: string[]
  plainTextFallback: boolean; forceUpstreamStream: boolean; showReasoning: boolean
  clickThrough: boolean; textShadow: boolean; shadowColor: string; shadowOffset: number
  textOutline: boolean; outlineColor: string; outlineWidth: number
  backgroundColor: string; textColor: string; mutedColor: string
  borderColor: string; errorColor: string
}

export interface SubtitleFonts { fonts: string[]; platform: string | null }
export interface PositioningResult { requestId: string; positioning: boolean }
