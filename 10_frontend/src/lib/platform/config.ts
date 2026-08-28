import type { PlatformSettings } from '../../../platform/settings'

declare const __UNS_PLATFORM_CONFIG__: string

export const platformConfig: PlatformSettings = JSON.parse(__UNS_PLATFORM_CONFIG__)
