import { expect, it } from 'vitest'
import { maskAccountLabel } from './account-label'

it('masks email addresses embedded in account labels while retaining their context and domain', () => {
  expect(maskAccountLabel('Primary (danny@outlook.com) / backup+jobs@example.co.uk')).toBe('Primary (d****y@outlook.com) / b****s@example.co.uk')
  expect(maskAccountLabel('Work inbox')).toBe('Work inbox')
  expect(maskAccountLabel('a@example.com')).toBe('a****@example.com')
  expect(maskAccountLabel('ab@example.com')).toBe('a****b@example.com')
})


it('masks international email local parts without leaving their prefix visible', () => {
  expect(maskAccountLabel('Work (josé@example.com)')).toBe('Work (j****é@example.com)')
  expect(maskAccountLabel('用户@example.com')).toBe('用****户@example.com')
})

it('masks quoted mailboxes and international domains', () => {
  expect(maskAccountLabel('"private mailbox"@example.com')).toBe('"p****x"@example.com')
  expect(maskAccountLabel('用户@例子.公司')).toBe('用****户@例子.公司')
})

it('does not expose SMTPUTF8 symbols or prefixes around them', () => {
  expect(maskAccountLabel('🔒private🔒@example.com')).toBe('🔒****🔒@example.com')
  expect(maskAccountLabel('josé🔒private@example.com')).toBe('j****e@example.com')
})
