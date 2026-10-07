import test from 'node:test'
import assert from 'node:assert/strict'

import {
  PAYMENT_RETURN_MAX_AGE_MS,
  PAYMENT_RETURN_STORAGE_KEY,
  cleanPaymentReturnUrl,
  parsePaymentReturn,
  rememberPendingPayment,
} from '../src/paymentReturn.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
}

test('reads the order-scoped success return generated for Hubtel', () => {
  const state = parsePaymentReturn(
    'https://shop.example.test/?campaign=launch&paymentReturn=1&orderId=EBA-1',
    memoryStorage(),
  )
  assert.equal(state.orderId, 'EBA-1')
  assert.equal(state.sourceStatus, '')
  assert.equal(state.fromStoredPayment, false)
})

test('marks a cancellation return while retaining its order context', () => {
  const state = parsePaymentReturn(
    'https://shop.example.test/?status=merchant-active&paymentReturn=1&orderId=EBA-2&paymentCancelled=1',
    memoryStorage(),
  )
  assert.equal(state.orderId, 'EBA-2')
  assert.equal(state.sourceStatus, 'cancelled')
})

test('recovers a bare provider return from the pending payment stored in the tab', () => {
  const storage = memoryStorage()
  rememberPendingPayment(storage, { orderId: 'EBA-3', reference: 'CHECKOUT-3', userId: 7 }, 10_000)
  const state = parsePaymentReturn('https://shop.example.test/', storage, 12_000)
  assert.deepEqual(state, {
    orderId: 'EBA-3',
    reference: 'CHECKOUT-3',
    sourceStatus: '',
    responseCode: '',
    ownerUserId: '7',
    fromStoredPayment: true,
  })
})

test('does not reopen an expired bare return context', () => {
  const storage = memoryStorage()
  rememberPendingPayment(storage, { orderId: 'EBA-4' }, 10_000)
  const state = parsePaymentReturn(
    'https://shop.example.test/',
    storage,
    10_000 + PAYMENT_RETURN_MAX_AGE_MS + 1,
  )
  assert.equal(state, null)
  assert.equal(storage.getItem(PAYMENT_RETURN_STORAGE_KEY), null)
})

test('cleans payment fields without removing unrelated URL state', () => {
  const cleaned = cleanPaymentReturnUrl(
    'https://shop.example.test/store?campaign=launch&orderId=EBA-5#products?paymentCancelled=1&color=red',
  )
  assert.equal(cleaned, '/store?campaign=launch#products?color=red')
})
