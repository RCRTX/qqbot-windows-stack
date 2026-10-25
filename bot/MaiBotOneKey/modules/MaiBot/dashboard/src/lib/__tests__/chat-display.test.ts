import { describe, expect, it } from 'vitest'

import { formatChatAccountLabel, formatChatDisplayName } from '@/lib/chat-display'

describe('chat display', () => {
  it('在聊天流名称后展示 Bot 平台账号', () => {
    expect(formatChatDisplayName('同名群聊', '1000000005')).toBe('同名群聊 · 账号 1000000005')
    expect(formatChatAccountLabel('1000000005')).toBe('账号 1000000005')
  })

  it('旧聊天流缺少账号时保持原名称', () => {
    expect(formatChatDisplayName('历史群聊', null)).toBe('历史群聊')
    expect(formatChatAccountLabel('  ')).toBe('')
  })
})
