/**
 * A fresh session id: a random UUID, version 4.
 *
 * The client names a new session, because the agent starts one for any id it
 * does not know (backend/openapi.yaml, `chat_turn_create`). Built from
 * `crypto.getRandomValues` rather than `crypto.randomUUID`, which browsers
 * offer only on HTTPS and localhost — and the portal is also reached over
 * plain http by address, before a host has its certificate.
 */
export function newSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // the RFC 4122 variant
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
