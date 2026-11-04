/** Mask email addresses embedded in display labels without changing account identity. */
export function maskAccountLabel(label: string): string {
  // Match complete unquoted UTF-8 locals, rather than masking only an ASCII suffix.
  return label.replace(/(?:"(?:[^"\\\r\n]|\\.)+"|[^\s@"<>()\[\],;:]+)@[\p{L}\p{N}](?:[\p{L}\p{N}\p{M}.-]*[\p{L}\p{N}\p{M}])?/giu, email => {
    const at = email.lastIndexOf('@')
    const quoted = email.startsWith('"')
    const local = Array.from(email.slice(quoted ? 1 : 0, quoted ? at - 1 : at))
    const suffix = local.length > 1 ? local[local.length - 1] : ''
    const quote = quoted ? '"' : ''
    return `${quote}${local[0]}****${suffix}${quote}${email.slice(at)}`
  })
}
