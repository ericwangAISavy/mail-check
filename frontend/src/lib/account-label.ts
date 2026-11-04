/** Mask email addresses embedded in display labels without changing account identity. */
export function maskAccountLabel(label: string): string {
  return label.replace(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?/gi, email => {
    const at = email.lastIndexOf('@')
    const local = email.slice(0, at)
    const suffix = local.length > 1 ? local.slice(-1) : ''
    return `${local[0]}****${suffix}${email.slice(at)}`
  })
}
