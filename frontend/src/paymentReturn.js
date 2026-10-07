export const PAYMENT_RETURN_STORAGE_KEY = 'ebaphone_pending_payment'
// Keep the fallback close to the server's stock-reservation window so a later
// ordinary visit does not unexpectedly reopen an old payment result.
export const PAYMENT_RETURN_MAX_AGE_MS = 45 * 60 * 1000

export const paymentReturnQueryKeys = new Set([
  'paymentreturn', 'payment_return', 'order', 'orderid', 'order_id',
  'clientreference', 'client_reference', 'reference', 'status', 'paymentstatus',
  'payment_status', 'transactionstatus', 'responsecode', 'response_code',
  'checkoutid', 'checkout_id', 'cancel', 'cancelled', 'canceled',
  'paymentcancelled', 'payment_cancelled',
])

function storageRemove(storage) {
  try { storage?.removeItem(PAYMENT_RETURN_STORAGE_KEY) } catch { /* Storage may be blocked. */ }
}

export function clearPendingPayment(storage) {
  storageRemove(storage)
}

export function rememberPendingPayment(storage, value, now = Date.now()) {
  const orderId = String(value?.orderId || '').trim()
  if (!orderId) return null
  const pending = {
    orderId,
    reference: String(value?.reference || '').trim(),
    userId: value?.userId == null ? '' : String(value.userId),
    startedAt: Number(value?.startedAt) || now,
  }
  try { storage?.setItem(PAYMENT_RETURN_STORAGE_KEY, JSON.stringify(pending)) } catch { /* In-memory state still works. */ }
  return pending
}

export function readPendingPayment(storage, now = Date.now()) {
  let pending = null
  try {
    const raw = storage?.getItem(PAYMENT_RETURN_STORAGE_KEY)
    pending = raw ? JSON.parse(raw) : null
  } catch {
    storageRemove(storage)
    return null
  }
  const orderId = String(pending?.orderId || '').trim()
  const startedAt = Number(pending?.startedAt)
  if (!orderId || !Number.isFinite(startedAt) || startedAt <= 0 || now - startedAt > PAYMENT_RETURN_MAX_AGE_MS) {
    storageRemove(storage)
    return null
  }
  return {
    orderId,
    reference: String(pending?.reference || '').trim(),
    userId: pending?.userId == null ? '' : String(pending.userId),
    startedAt,
  }
}

function paymentEntries(url) {
  const entries = [...url.searchParams.entries()]
  const rawHash = url.hash.replace(/^#/, '')
  const queryIndex = rawHash.indexOf('?')
  const hashQuery = queryIndex >= 0 ? rawHash.slice(queryIndex + 1) : (rawHash.includes('=') ? rawHash : '')
  if (hashQuery) entries.push(...new URLSearchParams(hashQuery).entries())
  return entries
}

export function parsePaymentReturn(href, storage, now = Date.now()) {
  const url = new URL(href, 'http://localhost/')
  const entries = paymentEntries(url)
  const get = (...names) => {
    const accepted = new Set(names.map((name) => name.toLowerCase()))
    const entry = entries.find(([key, value]) => accepted.has(key.toLowerCase()) && String(value || '').trim())
    return entry ? String(entry[1]).trim() : ''
  }
  const hasTruthy = (...names) => {
    const accepted = new Set(names.map((name) => name.toLowerCase()))
    return entries.some(([key, value]) => accepted.has(key.toLowerCase()) && !['', '0', 'false', 'no'].includes(String(value || '').trim().toLowerCase()))
  }

  const explicitOrderId = get('order', 'orderId', 'order_id', 'clientReference', 'client_reference')
  const reference = get('reference')
  const orderId = explicitOrderId || (/^EBA-/i.test(reference) ? reference : '')
  const checkoutId = get('checkoutId', 'checkout_id')
  const cancellationSignal = get('cancel', 'cancelled', 'canceled', 'paymentCancelled', 'payment_cancelled')
  const isCancellation = hasTruthy('cancel', 'cancelled', 'canceled', 'paymentCancelled', 'payment_cancelled')
  const sourceStatus = isCancellation
    ? 'cancelled'
    : get('status', 'paymentStatus', 'payment_status', 'transactionStatus')
  const responseCode = get('responseCode', 'response_code')
  const returnMarker = get('paymentReturn', 'payment_return')
  const hasExplicitSignal = Boolean(
    returnMarker || orderId || checkoutId || cancellationSignal
    || (sourceStatus && (reference || responseCode))
    || (responseCode && reference),
  )
  const pending = readPendingPayment(storage, now)
  if (!hasExplicitSignal && !pending) return null

  return {
    orderId: orderId || pending?.orderId || '',
    reference: checkoutId || reference || pending?.reference || '',
    sourceStatus,
    responseCode,
    ownerUserId: pending?.userId || '',
    fromStoredPayment: !hasExplicitSignal && Boolean(pending),
  }
}

export function cleanPaymentReturnUrl(href) {
  const url = new URL(href, 'http://localhost/')
  for (const key of [...url.searchParams.keys()]) {
    if (paymentReturnQueryKeys.has(key.toLowerCase())) url.searchParams.delete(key)
  }

  const rawHash = url.hash.replace(/^#/, '')
  const queryIndex = rawHash.indexOf('?')
  const hashPrefix = queryIndex >= 0 ? rawHash.slice(0, queryIndex) : ''
  const hashQuery = queryIndex >= 0 ? rawHash.slice(queryIndex + 1) : (rawHash.includes('=') ? rawHash : '')
  if (hashQuery) {
    const hashParams = new URLSearchParams(hashQuery)
    for (const key of [...hashParams.keys()]) {
      if (paymentReturnQueryKeys.has(key.toLowerCase())) hashParams.delete(key)
    }
    const cleanedHashQuery = hashParams.toString()
    url.hash = hashPrefix
      ? `${hashPrefix}${cleanedHashQuery ? `?${cleanedHashQuery}` : ''}`
      : (cleanedHashQuery ? cleanedHashQuery : '')
  }
  return `${url.pathname}${url.search}${url.hash}`
}
