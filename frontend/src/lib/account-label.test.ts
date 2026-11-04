import { expect, it } from 'vitest'
import { maskAccountLabel } from './account-label'

it('masks email addresses embedded in account labels while retaining their context and domain', () => {
  expect(maskAccountLabel('Primary (danny@outlook.com) / backup+jobs@example.co.uk')).toBe('Primary (d****y@outlook.com) / b****s@example.co.uk')
  expect(maskAccountLabel('Work inbox')).toBe('Work inbox')
  expect(maskAccountLabel('a@example.com')).toBe('a****@example.com')
  expect(maskAccountLabel('ab@example.com')).toBe('a****b@example.com')
})
