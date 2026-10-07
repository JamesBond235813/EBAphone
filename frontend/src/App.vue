<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Headphones,
  House,
  MapPin,
  Package,
  PhoneCall,
  ShoppingCart,
  Store,
  Truck,
  UserRound,
  X,
} from 'lucide-vue-next'
import {
  cleanPaymentReturnUrl,
  clearPendingPayment,
  parsePaymentReturn,
  rememberPendingPayment,
} from './paymentReturn.js'

const api = '/api'
const PAGE_STATE_KEY = 'ebaphone_current_page'
const pageStateReady = ref(false)

function readStoredJson(key, fallback) {
  try {
    const value = localStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch {
    return fallback
  }
}

function readSessionJson(key, fallback) {
  try {
    const value = sessionStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch {
    return fallback
  }
}

function readPageState() {
  const value = readSessionJson(PAGE_STATE_KEY, null)
  return value && typeof value === 'object' ? value : null
}

const skus = ref([])
const stores = ref([])
const deliveryCoverage = ref(null)
const banners = ref([])
const bannerIndex = ref(0)
const bannerImageFailed = ref(false)
const selected = ref(null)
const selectedQuantity = ref(1)
const step = ref('catalog')
const loading = ref(true)
const activeTab = ref('home')
const activeCategory = ref('all')
const meSection = ref('cart')
const apiError = ref('')
const orderError = ref('')
const paymentError = ref('')
const cartNotice = ref('')
const ordersError = ref('')
const ordersBusy = ref(false)
const orderCancelBusy = ref('')
const orderPaymentBusy = ref('')
const orderDetail = ref(null)
const orderBusy = ref(false)
const paymentBusy = ref(false)
const order = ref(null)
const orders = ref([])
const paymentReturn = ref(null)
const paymentReturnBusy = ref(false)
const paymentReturnError = ref('')
const cart = ref(readStoredJson('ebaphone_cart', []))
const selectedCartIds = ref(cart.value.map((item) => item.id))
const search = ref('')

const messages = ref([{ role: 'assistant', text: 'Hi, I’m the EBAphone support assistant. I can help with FAQs, products and store information. For order-specific help, a team member can follow up here.' }])
const chatInput = ref('')
const quickQuestions = ['Check product stock', 'How do deposits work?', 'Delivery or store pickup', 'Recommend a device']
const supportBusy = ref(false)
const supportError = ref('')

const authOpen = ref(false)
const authAccount = ref('')
const authName = ref('')
const authUser = ref(readStoredJson('ebaphone_user', null))
const profileDraft = ref({
  name: authUser.value?.name || '',
  email: authUser.value?.email || '',
  default_address: authUser.value?.default_address || '',
})
const profileBusy = ref(false)
const profileError = ref('')
const authError = ref('')
const smsCode = ref('')
const smsSent = ref(false)
const smsBusy = ref(false)
const smsCountdown = ref(0)
const authCardRef = ref(null)
const authPhoneInputRef = ref(null)
const smsCodeInputRef = ref(null)
const cartSectionRef = ref(null)
const ordersSectionRef = ref(null)
let smsTimer = null
let previouslyFocusedElement = null

const plan = ref('deposit')
const fulfillment = ref('pickup')
const storeId = ref(null)
const address = ref('')
const name = ref('')
const phone = ref('')
// A signed-in customer should never have to retype the account phone at
// checkout.  Keep the field editable for a canonical-format correction, but
// fall back to the authenticated profile if a browser autofill or a stale
// component render temporarily leaves the local ref empty.
const checkoutPhone = computed({
  get: () => phone.value || authUser.value?.phone || '',
  set: (value) => { phone.value = value },
})
// Keep one idempotency key for a checkout attempt.  If the network drops after
// the API committed the order, pressing the button again must return that same
// order instead of creating a second reservation.
const storedOrderAttempt = readSessionJson('ebaphone_pending_order', {})
const orderAttemptKey = ref(storedOrderAttempt.key || '')
const orderAttemptFingerprint = ref(storedOrderAttempt.fingerprint || '')

function persistPageState() {
  const snapshot = {
    activeTab: activeTab.value,
    step: step.value,
    meSection: meSection.value,
    activeCategory: activeCategory.value,
    search: search.value,
    selectedProductId: selected.value?.id ?? null,
    selectedQuantity: selectedQuantity.value,
    plan: plan.value,
    fulfillment: fulfillment.value,
    storeId: storeId.value,
    order: order.value ? {
      id: order.value.id,
      product_name: order.value.product_name,
      payment_status: order.value.payment_status,
      deposit_amount: order.value.deposit_amount,
      remaining_amount: order.value.remaining_amount,
      store_name: order.value.store_name,
      quantity: order.value.quantity,
    } : null,
    paymentReturn: paymentReturn.value ? {
      orderId: paymentReturn.value.orderId,
      reference: paymentReturn.value.reference,
      ownerUserId: paymentReturn.value.ownerUserId,
      outcome: paymentReturn.value.outcome,
      urlOutcome: paymentReturn.value.urlOutcome,
    } : null,
    scrollY: window.scrollY,
  }
  try { sessionStorage.setItem(PAGE_STATE_KEY, JSON.stringify(snapshot)) } catch { /* Session storage may be unavailable. */ }
  const routeHash = snapshot.step === 'detail' && snapshot.selectedProductId != null
    ? `#/product/${encodeURIComponent(snapshot.selectedProductId)}`
    : snapshot.step === 'success'
      ? '#/success'
      : snapshot.activeTab === 'stores'
        ? '#/stores'
        : snapshot.activeTab === 'msg'
          ? '#/support'
          : snapshot.activeTab === 'me'
            ? `#/me/${snapshot.meSection}`
            : '#/home'
  if (window.location.hash !== routeHash) {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${routeHash}`)
  }
}

function pageStateFromRoute() {
  const route = window.location.hash.replace(/^#\/?/, '')
  if (route === 'stores') return { activeTab: 'stores', step: 'catalog' }
  if (route === 'support') return { activeTab: 'msg', step: 'catalog' }
  const account = route.match(/^me\/(cart|receive|completed)$/)
  if (account) return { activeTab: 'me', meSection: account[1], step: 'catalog' }
  const product = route.match(/^product\/([^/?#]+)$/)
  if (product) return { activeTab: 'home', step: 'detail', selectedProductId: decodeURIComponent(product[1]) }
  if (route === 'success') return { activeTab: 'home', step: 'success' }
  if (route === 'home') return { activeTab: 'home', step: 'catalog' }
  return null
}

async function restorePageState() {
  const snapshot = readPageState()
  const route = pageStateFromRoute()
  // The URL represents the page the user refreshed; keep the snapshot for details
  // such as quantities and order data, while letting its route fields win.
  const saved = route ? { ...snapshot, ...route } : snapshot
  if (!saved) return

  const validTabs = new Set(['home', 'stores', 'msg', 'me'])
  activeTab.value = validTabs.has(saved.activeTab) ? saved.activeTab : 'home'
  meSection.value = ['cart', 'receive', 'completed'].includes(saved.meSection) ? saved.meSection : 'cart'
  activeCategory.value = categoryOptions.some((item) => item.id === saved.activeCategory) ? saved.activeCategory : 'all'
  search.value = typeof saved.search === 'string' ? saved.search.slice(0, 100) : ''

  if (saved.step === 'detail' && saved.selectedProductId != null) {
    const product = skus.value.find((item) => Number(item.id) === Number(saved.selectedProductId))
    if (product) {
      selected.value = product
      selectedQuantity.value = Math.max(1, Math.floor(Number(saved.selectedQuantity) || 1))
      plan.value = saved.plan === 'full' ? 'full' : 'deposit'
      fulfillment.value = saved.fulfillment === 'shipping' ? 'shipping' : 'pickup'
      const preferredStore = stores.value.find((item) => Number(item.id) === Number(saved.storeId))
      storeId.value = preferredStore?.id ?? stores.value[0]?.id ?? null
      chooseFirstAvailableStore(product)
      selectedQuantity.value = Math.min(selectedQuantity.value, Math.max(1, maxSelectedStoreStock.value))
      step.value = 'detail'
    }
  } else if (saved.step === 'success') {
    if (saved.order?.id) order.value = saved.order
    if (saved.paymentReturn?.orderId) paymentReturn.value = saved.paymentReturn
    if (order.value || paymentReturn.value) {
      activeTab.value = 'home'
      step.value = 'success'
    }
  }

  if (activeTab.value === 'msg' && authUser.value) await loadSupportConversation()
  if (activeTab.value === 'me' && authUser.value) await loadOrders({ prompt: false })
  await nextTick()
  const scrollY = Number(saved.scrollY)
  if (Number.isFinite(scrollY) && scrollY > 0) window.scrollTo(0, scrollY)
}

const categoryOptions = [
  { id: 'all', label: 'All products' },
  { id: 'phones', label: 'Phones' },
  { id: 'audio', label: 'Audio' },
  { id: 'cases', label: 'Cases & accessories' },
]

const categoryAliases = {
  phone: 'phones',
  phones: 'phones',
  smartphone: 'phones',
  smartphones: 'phones',
  audio: 'audio',
  headphones: 'audio',
  earbuds: 'audio',
  speaker: 'audio',
  speakers: 'audio',
  case: 'cases',
  cases: 'cases',
  accessory: 'cases',
  accessories: 'cases',
  'case-accessories': 'cases',
  'case-and-accessories': 'cases',
  'cases-and-accessories': 'cases',
  'cases-accessories': 'cases',
}

function normalizedCategory(item) {
  const raw = String(item?.category || '').trim().toLowerCase().replace(/[\s_]/g, '-')
  if (categoryAliases[raw]) return categoryAliases[raw]
  const text = `${item?.brand || ''} ${item?.product_name || ''} ${item?.variant || ''}`.toLowerCase()
  if (/headphone|earbud|speaker|audio|sound/.test(text)) return 'audio'
  if (/case|cover|charger|cable|screen|stand|accessor/.test(text)) return 'cases'
  return 'phones'
}

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return skus.value.filter((item) => {
    const inCategory = activeCategory.value === 'all' || normalizedCategory(item) === activeCategory.value
    const inSearch = !query || `${item.brand} ${item.product_name} ${item.variant}`.toLowerCase().includes(query)
    return inCategory && inSearch
  })
})

const categoryCounts = computed(() => Object.fromEntries(categoryOptions.map((category) => [
  category.id,
  category.id === 'all' ? skus.value.length : skus.value.filter((item) => normalizedCategory(item) === category.id).length,
])))

const cartCount = computed(() => cart.value.reduce((total, item) => total + safeCartQuantity(item), 0))
const cartTotal = computed(() => cart.value.reduce((total, item) => total + Number(item.price || 0) * safeCartQuantity(item), 0))
const selectedCartItems = computed(() => cart.value.filter((item) => selectedCartIds.value.includes(item.id)))
const selectedCartCount = computed(() => selectedCartItems.value.reduce((total, item) => total + safeCartQuantity(item), 0))
const selectedCartTotal = computed(() => selectedCartItems.value.reduce((total, item) => total + Number(item.price || 0) * safeCartQuantity(item), 0))
const allCartSelected = computed(() => cart.value.length > 0 && cart.value.every((item) => selectedCartIds.value.includes(item.id)))
const completedOrderCount = computed(() => orders.value.filter((item) => item.order_status === 'completed').length)
const visibleOrders = computed(() => {
  if (meSection.value === 'receive') return orders.value.filter((item) => item.order_status === 'shipped')
  if (meSection.value === 'completed') return orders.value.filter((item) => item.order_status === 'completed')
  return []
})
const hasUserMessage = computed(() => messages.value.some((message) => message.role === 'user'))
const currentBanner = computed(() => banners.value[bannerIndex.value] || null)
const bannerHasImage = computed(() => Boolean(currentBanner.value?.image && !bannerImageFailed.value))
const paymentReturnOutcome = computed(() => paymentReturn.value?.outcome || 'pending')
const paymentReturnTitle = computed(() => {
  if (paymentReturnOutcome.value === 'success') return 'Payment confirmed'
  if (paymentReturnOutcome.value === 'failed') return 'Payment was not completed'
  return 'Payment confirmation pending'
})
const paymentReturnDescription = computed(() => {
  if (paymentReturnOutcome.value === 'success') return 'Your payment has been received. Our store team can now prepare the next step for your order.'
  if (paymentReturnOutcome.value === 'failed') return 'Hubtel did not confirm this payment. You can retry the same order without creating a duplicate order.'
  return 'We are still waiting for confirmation from Hubtel. Please check again before starting another payment.'
})
const phoneDigits = computed(() => authAccount.value.replace(/\D/g, '').slice(0, 9))
const phoneSlots = computed(() => Array.from({ length: 9 }, (_, index) => phoneDigits.value[index] || ''))
const authPhone = computed(() => (phoneDigits.value.length === 9 ? `+233${phoneDigits.value}` : phoneDigits.value))
const selectedStore = computed(() => stores.value.find((store) => Number(store.id) === Number(storeId.value)) || null)
const selectedStock = computed(() => selected.value ? Number(selected.value.store_stock?.[storeId.value] || 0) : 0)
const totalSelectedStock = computed(() => selected.value
  ? Object.values(selected.value.store_stock || {}).reduce((total, value) => total + Number(value || 0), 0)
  : 0)
const maxSelectedStoreStock = computed(() => selected.value
  ? Math.max(0, ...Object.values(selected.value.store_stock || {}).map((value) => Number(value || 0)))
  : 0)
const dueNow = computed(() => {
  if (!selected.value) return 0
  const quantity = Math.max(1, Number(selectedQuantity.value) || 1)
  return plan.value === 'deposit'
    ? Number(selected.value.price) * quantity * Number(selected.value.deposit_rate) / 100
    : Number(selected.value.price) * quantity
})
const canPlaceOrder = computed(() => {
  const requestedQuantity = Math.max(1, Number(selectedQuantity.value) || 1)
  if (!selected.value || orderBusy.value || maxSelectedStoreStock.value < requestedQuantity) return false
  if (!authUser.value) return true
  if (!name.value.trim() || checkoutPhone.value.replace(/\D/g, '').length < 7) return false
  if (plan.value === 'deposit' || fulfillment.value === 'pickup') return selectedStock.value >= requestedQuantity
  return address.value.trim().length >= 10
})

const money = (value) => new Intl.NumberFormat('en-GH', { style: 'currency', currency: 'GHS' }).format(Number(value || 0))
const cardMoney = (value) => `₵${new Intl.NumberFormat('en-GH', { maximumFractionDigits: 0 }).format(Number(value || 0))}`
const stockFor = (item, id) => Number(item?.store_stock?.[id] || 0)
const stockLabel = (item, id) => {
  const stock = stockFor(item, id)
  return stock > 0 ? `${stock} available` : 'Out of stock'
}
const totalStockFor = (item) => Object.values(item?.store_stock || {}).reduce((total, value) => total + Number(value || 0), 0)
const storesWithStock = (item) => Object.values(item?.store_stock || {}).filter((value) => Number(value || 0) > 0).length
const liveSkuFor = (item) => skus.value.find((sku) => Number(sku.id) === Number(item?.id)) || (skus.value.length ? null : item)
const cartStockLimit = (item) => {
  const live = liveSkuFor(item)
  return live ? Math.max(0, ...Object.values(live.store_stock || {}).map((value) => Number(value || 0))) : 0
}
const safeCartQuantity = (item) => {
  const limit = cartStockLimit(item)
  if (limit < 1) return 0
  const requested = Math.max(1, Math.floor(Number(item?.qty) || 1))
  return Math.min(requested, limit)
}
const cancellableOrderStatuses = new Set(['pending', 'awaiting_payment', 'awaiting_store_process', 'processing'])
const canCancelOrder = (item) => Boolean(item?.id) && item.payment_status === 'pending' && cancellableOrderStatuses.has(item.order_status)
const canContinuePayment = (item) => Boolean(item?.id) && item.payment_status === 'pending' && !['completed', 'shipped', 'cancelled', 'released'].includes(item.order_status)
const fulfillmentEstimate = (item) => {
  if (item?.fulfillment_type === 'pickup') return 'Pickup timing confirmed by the selected store'
  if (item?.fulfillment_type === 'shipping') return 'Delivery timing confirmed after address review'
  return 'Store reservation'
}
const statusLabel = (status) => String(status || '').replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const initials = (value) => String(value || 'G').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
const dateLabel = (value) => value ? new Intl.DateTimeFormat('en-GH', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'Not available'
const balanceAfterInitialPayment = (item) => Number(item?.payment_plan === 'deposit' ? item?.remaining_amount : item?.balance_due ?? item?.remaining_amount ?? 0)
const balanceLabel = (item) => item?.payment_plan === 'deposit' ? 'Balance after deposit' : 'Balance due'

function createOrderAttemptKey() {
  try {
    if (globalThis.crypto?.randomUUID) return `web-${globalThis.crypto.randomUUID()}`
  } catch {
    // Fall back below for older browsers or restricted web views.
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

function orderRequestFingerprint(payload) {
  return JSON.stringify({
    sku_id: payload.sku_id,
    quantity: payload.quantity,
    payment_plan: payload.payment_plan,
    fulfillment_type: payload.fulfillment_type || null,
    store_id: payload.store_id || null,
    shipping_address: payload.shipping_address || null,
    customer_phone: payload.customer_phone,
  })
}

function idempotencyKeyFor(payload) {
  const fingerprint = orderRequestFingerprint(payload)
  if (!orderAttemptKey.value || orderAttemptFingerprint.value !== fingerprint) {
    orderAttemptKey.value = createOrderAttemptKey()
    orderAttemptFingerprint.value = fingerprint
    try {
      sessionStorage.setItem('ebaphone_pending_order', JSON.stringify({ key: orderAttemptKey.value, fingerprint }))
    } catch {
      // In-memory retry protection still works if browser storage is blocked.
    }
  }
  return orderAttemptKey.value
}

function clearOrderAttempt() {
  orderAttemptKey.value = ''
  orderAttemptFingerprint.value = ''
  try { sessionStorage.removeItem('ebaphone_pending_order') } catch { /* Storage can be unavailable in private web views. */ }
}

function authHeaders(headers = {}) {
  const token = localStorage.getItem('ebaphone_token')
  return token ? { ...headers, Authorization: `Bearer ${token}` } : headers
}

function paymentStorage() {
  const storages = []
  try { if (window.sessionStorage) storages.push(window.sessionStorage) } catch { /* Storage may be blocked. */ }
  try { if (window.localStorage) storages.push(window.localStorage) } catch { /* Storage may be blocked. */ }
  return {
    getItem: (key) => {
      for (const storage of storages) {
        try {
          const value = storage.getItem(key)
          if (value != null) return value
        } catch { /* Try the next available storage. */ }
      }
      return null
    },
    setItem: (key, value) => {
      for (const storage of storages) {
        try { storage.setItem(key, value) } catch { /* Try the next available storage. */ }
      }
    },
    removeItem: (key) => {
      for (const storage of storages) {
        try { storage.removeItem(key) } catch { /* Try the next available storage. */ }
      }
    },
  }
}

function rememberPaymentAttempt(orderId, reference = '') {
  return rememberPendingPayment(paymentStorage(), {
    orderId,
    reference,
    userId: authUser.value?.id,
  })
}

function clearRememberedPayment() {
  clearPendingPayment(paymentStorage())
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${api}${path}`, {
    ...options,
    headers: authHeaders({ ...(options.headers || {}) }),
  })
  const raw = await response.text()
  let data = null
  try { data = raw ? JSON.parse(raw) : null } catch { data = raw }
  if (!response.ok) {
    const error = new Error(data?.detail || data?.message || `Service unavailable (${response.status})`)
    error.status = response.status
    error.retryAfter = Number(data?.retry_after || response.headers.get('retry-after') || 0)
    throw error
  }
  return data
}

async function loadCatalog() {
  loading.value = true
  apiError.value = ''
  try {
    const [catalog, storeList, bannerList, coverage] = await Promise.all([
      apiRequest('/skus'),
      apiRequest('/stores'),
      apiRequest('/banners'),
      apiRequest('/delivery/coverage').catch(() => null),
    ])
    skus.value = Array.isArray(catalog) ? catalog : []
    stores.value = Array.isArray(storeList) ? storeList : []
    deliveryCoverage.value = coverage
    banners.value = Array.isArray(bannerList) ? bannerList : []
    syncCartWithCatalog()
    if (bannerIndex.value >= banners.value.length) bannerIndex.value = 0
    bannerImageFailed.value = false
    if (!storeId.value && stores.value.length) storeId.value = stores.value[0].id
  } catch (error) {
    apiError.value = error.message || 'We could not load the store right now. Please refresh in a moment.'
  } finally {
    loading.value = false
  }
}

async function restoreAuthenticatedUser() {
  const storedToken = localStorage.getItem('ebaphone_token')
  if (!storedToken) {
    // Keep any Hubtel return parameters intact; handlePaymentReturn() parses
    // them immediately after session restoration and can then ask the user
    // to sign in again without losing the checkout context.
    if (authUser.value) logout(false, { clearPaymentReturn: false })
    return
  }
  try {
    const verifiedUser = await apiRequest('/auth/me')
    authUser.value = verifiedUser
    localStorage.setItem('ebaphone_user', JSON.stringify(verifiedUser))
    name.value = verifiedUser?.name || ''
    phone.value = verifiedUser?.phone || ''
    address.value = verifiedUser?.default_address || ''
  } catch (error) {
    if (error.status === 401 || error.status === 403 || error.status === 404) logout(false, { clearPaymentReturn: false })
    // A temporary API outage must not destroy a valid local session. Public
    // catalogue loading will surface the connectivity error independently.
  }
}

function syncCartWithCatalog() {
  if (!skus.value.length || !cart.value.length) return
  cart.value = cart.value.flatMap((item) => {
    const latest = skus.value.find((sku) => Number(sku.id) === Number(item?.id))
    if (!latest?.id) return []
    const limit = Math.max(0, ...Object.values(latest.store_stock || {}).map((value) => Number(value || 0)))
    if (limit < 1) return []
    return [{
      ...item,
      ...latest,
      qty: Math.min(Math.max(1, Math.floor(Number(item.qty) || 1)), limit),
    }]
  })
}

function syncKeyboardOffset() {
  const viewport = window.visualViewport
  if (!viewport) return
  const offset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
  document.documentElement.style.setProperty('--keyboard-offset', `${offset}px`)
}

function chooseFirstAvailableStore(item = selected.value) {
  if (!item || !stores.value.length) return
  const required = Math.max(1, Number(selectedQuantity.value) || 1)
  if (stockFor(item, storeId.value) >= required) return
  const available = stores.value.find((store) => stockFor(item, store.id) >= required)
  if (available) storeId.value = available.id
}

function resetCheckoutState() {
  selected.value = null
  selectedQuantity.value = 1
  storeId.value = null
  plan.value = 'deposit'
  fulfillment.value = 'pickup'
  name.value = ''
  phone.value = ''
  address.value = ''
  order.value = null
  orderDetail.value = null
  orderError.value = ''
  paymentError.value = ''
  orderBusy.value = false
  paymentBusy.value = false
  orderCancelBusy.value = ''
  orderPaymentBusy.value = ''
  clearOrderAttempt()
}

function resetUserScopedState({ clearPaymentReturn = true } = {}) {
  const keepReturnPage = !clearPaymentReturn && Boolean(paymentReturn.value)
  resetCheckoutState()
  profileDraft.value = { name: '', email: '', default_address: '' }
  profileError.value = ''
  profileBusy.value = false
  orders.value = []
  ordersError.value = ''
  ordersBusy.value = false
  chatInput.value = ''
  supportError.value = ''
  supportBusy.value = false
  messages.value = [{ role: 'assistant', text: 'Hi, I’m the EBAphone support assistant. I can help with FAQs, products and store information. For order-specific help, a team member can follow up here.' }]
  authAccount.value = ''
  authName.value = ''
  authError.value = ''
  resetSmsState()
  activeTab.value = 'home'
  meSection.value = 'cart'
  step.value = keepReturnPage ? 'success' : 'catalog'
  if (clearPaymentReturn) {
    paymentReturn.value = null
    paymentReturnError.value = ''
    paymentReturnBusy.value = false
    clearRememberedPayment()
  }
}

function clearPaymentReturnUrl() {
  window.history.replaceState(window.history.state, '', cleanPaymentReturnUrl(window.location.href))
}

function clearPaymentReturnState() {
  paymentReturn.value = null
  paymentReturnError.value = ''
  paymentReturnBusy.value = false
  clearRememberedPayment()
  clearPaymentReturnUrl()
}

function goHome() {
  activeTab.value = 'home'
  step.value = 'catalog'
  selected.value = null
  order.value = null
  orderError.value = ''
  paymentError.value = ''
  clearPaymentReturnState()
  clearOrderAttempt()
  selectedQuantity.value = 1
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goStores() {
  activeTab.value = 'stores'
  step.value = 'catalog'
  clearPaymentReturnState()
  apiError.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function goSupport() {
  activeTab.value = 'msg'
  step.value = 'catalog'
  clearPaymentReturnState()
  orderError.value = ''
  paymentError.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
  if (authUser.value) await loadSupportConversation()
}

async function goMe(section = 'cart') {
  activeTab.value = 'me'
  step.value = 'catalog'
  clearPaymentReturnState()
  focusMeSection(section)
  if (authUser.value) await loadOrders({ prompt: false })
}

// The account shortcuts are intentionally available on both desktop and
// mobile.  Keep the target in a template ref so the scroll still works after
// Vue switches the active tab and renders the account page.
function focusMeSection(section = 'cart') {
  meSection.value = section === 'receive' || section === 'completed' ? section : 'cart'
  const target = meSection.value === 'cart' ? cartSectionRef : ordersSectionRef
  nextTick(() => target.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

function selectMeView(view) {
  focusMeSection(view)
}

function selectCategory(category) {
  activeCategory.value = category
  activeTab.value = 'home'
  step.value = 'catalog'
  clearPaymentReturnState()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function choose(item, quantity = 1) {
  if (authUser.value?.phone && !phone.value.trim()) phone.value = authUser.value.phone
  if (authUser.value?.name && !name.value.trim()) name.value = authUser.value.name
  selected.value = item
  clearPaymentReturnState()
  selectedQuantity.value = Math.max(1, Math.floor(Number(quantity) || 1))
  step.value = 'detail'
  activeTab.value = 'home'
  plan.value = 'deposit'
  fulfillment.value = 'pickup'
  orderError.value = ''
  paymentError.value = ''
  order.value = null
  clearOrderAttempt()
  chooseFirstAvailableStore(item)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function changeSelectedQuantity(delta) {
  if (!selected.value) return
  const current = Math.max(1, Math.floor(Number(selectedQuantity.value) || 1))
  const limit = Math.max(1, maxSelectedStoreStock.value)
  selectedQuantity.value = Math.min(limit, Math.max(1, current + delta))
  chooseFirstAvailableStore(selected.value)
}

function addToCart(item) {
  const limit = cartStockLimit(item)
  if (limit < 1) {
    cartNotice.value = `${item.product_name} is currently out of stock.`
    window.setTimeout(() => { cartNotice.value = '' }, 2800)
    return
  }
  const existing = cart.value.find((cartItem) => cartItem.id === item.id)
  if (existing) {
    const next = Math.min(limit, Math.max(1, Number(existing.qty) || 1) + 1)
    existing.qty = next
    if (next >= limit) cartNotice.value = `Only ${limit} ${item.product_name} available at one store for this order.`
  }
  else {
    cart.value.push({ ...item, qty: 1 })
    if (!selectedCartIds.value.includes(item.id)) selectedCartIds.value = [...selectedCartIds.value, item.id]
  }
  if (!existing || Number(existing.qty) < limit) cartNotice.value = `${item.product_name} added to your cart.`
  activeTab.value = 'me'
  meSection.value = 'cart'
  window.setTimeout(() => { cartNotice.value = '' }, 2800)
}

function changeCartQuantity(item, delta) {
  const limit = cartStockLimit(item)
  if (limit < 1) {
    removeFromCart(item)
    cartNotice.value = `${item.product_name} was removed because it is out of stock.`
    window.setTimeout(() => { cartNotice.value = '' }, 2800)
    return
  }
  const current = safeCartQuantity(item)
  const next = current + delta
  if (next <= 0) {
    removeFromCart(item)
    return
  }
  item.qty = Math.min(limit, next)
  if (delta > 0 && current >= limit) {
    cartNotice.value = `Only ${limit} ${item.product_name} available at one store for this order.`
    window.setTimeout(() => { cartNotice.value = '' }, 2800)
  }
}

function removeFromCart(item) {
  cart.value = cart.value.filter((cartItem) => cartItem.id !== item.id)
  selectedCartIds.value = selectedCartIds.value.filter((id) => id !== item.id)
}

function toggleCartSelection(item) {
  selectedCartIds.value = selectedCartIds.value.includes(item.id)
    ? selectedCartIds.value.filter((id) => id !== item.id)
    : [...selectedCartIds.value, item.id]
}

function toggleAllCartSelection() {
  selectedCartIds.value = allCartSelected.value ? [] : cart.value.map((item) => item.id)
}

function removeSelectedCartItems() {
  const selectedIds = new Set(selectedCartIds.value)
  cart.value = cart.value.filter((item) => !selectedIds.has(item.id))
  selectedCartIds.value = []
}

function checkoutSelectedCartItems() {
  const item = selectedCartItems.value.find((entry) => cartStockLimit(entry) > 0)
  if (item) checkoutCartItem(item)
}

function checkoutCartItem(item) {
  const latest = liveSkuFor(item)
  const limit = cartStockLimit(item)
  if (!latest?.id || limit < 1) {
    removeFromCart(item)
    cartNotice.value = `${item.product_name} is no longer available and was removed from your cart.`
    window.setTimeout(() => { cartNotice.value = '' }, 3200)
    return
  }
  item.qty = Math.min(safeCartQuantity(item), limit)
  choose(latest, safeCartQuantity(item))
}

function markBannerImageFailed() {
  bannerImageFailed.value = true
}

function reloadPage() {
  window.location.reload()
}

function useImageFallback(event, label = 'EBAphone') {
  const image = event?.target
  if (!image || image.dataset.fallbackApplied) return
  image.dataset.fallbackApplied = 'true'
  const safeLabel = String(label || 'EBAphone').slice(0, 32).replace(/[<>&'\"]/g, (character) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[character]))
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 700"><rect width="900" height="700" fill="#efe2d5"/><circle cx="450" cy="280" r="112" fill="#fff8f2"/><text x="450" y="285" text-anchor="middle" dominant-baseline="middle" font-family="Arial,sans-serif" font-size="54" font-weight="700" fill="#ff666b">EBA</text><text x="450" y="505" text-anchor="middle" font-family="Arial,sans-serif" font-size="30" fill="#333333">${safeLabel}</text></svg>`
  image.src = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

async function loadOrders({ prompt = true } = {}) {
  if (!localStorage.getItem('ebaphone_token')) {
    orders.value = []
    orderDetail.value = null
    if (prompt) openAuth()
    return
  }
  ordersBusy.value = true
  ordersError.value = ''
  try {
    const result = await apiRequest('/orders')
    orders.value = Array.isArray(result) ? result : []
    if (orderDetail.value) orderDetail.value = orders.value.find((item) => item.id === orderDetail.value.id) || null
  } catch (error) {
    ordersError.value = error.message || 'Orders are temporarily unavailable.'
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      ordersError.value = 'Your session expired. Sign in again to continue.'
      openAuth()
    }
  } finally {
    ordersBusy.value = false
  }
}

function updateOrderEverywhere(updated) {
  if (!updated?.id) return
  const index = orders.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) orders.value[index] = updated
  if (order.value?.id === updated.id) order.value = updated
  if (orderDetail.value?.id === updated.id) orderDetail.value = updated
}

async function cancelOrder(item) {
  if (!canCancelOrder(item) || orderCancelBusy.value) return
  const confirmed = window.confirm(`Cancel order ${item.id}?`)
  if (!confirmed) return
  orderCancelBusy.value = item.id
  ordersError.value = ''
  try {
    const result = await apiRequest(`/orders/${encodeURIComponent(item.id)}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Customer requested cancellation' }),
    })
    updateOrderEverywhere(result)
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      ordersError.value = 'Your session expired. Sign in again to continue.'
      openAuth()
      return
    }
    ordersError.value = error.message || 'Unable to cancel this order.'
  } finally {
    orderCancelBusy.value = ''
  }
}

function toggleOrderDetail(item) {
  orderDetail.value = orderDetail.value?.id === item.id ? null : item
}

async function continueOrderPayment(item) {
  if (!canContinuePayment(item) || orderPaymentBusy.value) return
  orderPaymentBusy.value = item.id
  ordersError.value = ''
  try {
    const result = await apiRequest(`/orders/${encodeURIComponent(item.id)}/payment-session`, { method: 'POST' })
    if (!result?.checkout_url) throw new Error('The payment provider did not return a checkout link.')
    rememberPaymentAttempt(item.id, result.checkout_id)
    window.location.href = result.checkout_url
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      ordersError.value = 'Your session expired. Sign in again to continue.'
      openAuth()
      return
    }
    ordersError.value = error.message || 'Unable to continue payment for this order.'
  } finally {
    orderPaymentBusy.value = ''
  }
}

function openAuth() {
  if (!authOpen.value) previouslyFocusedElement = document.activeElement
  authOpen.value = true
  authError.value = ''
  nextTick(() => authPhoneInputRef.value?.focus())
}

function closeAuth() {
  authOpen.value = false
  authError.value = ''
  resetSmsState()
  authAccount.value = ''
  authName.value = ''
  nextTick(() => previouslyFocusedElement?.focus?.())
  previouslyFocusedElement = null
}

function trapAuthFocus(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeAuth()
    return
  }
  if (event.key !== 'Tab' || !authCardRef.value) return
  const focusable = [...authCardRef.value.querySelectorAll('button:not([disabled]), input:not([disabled])')]
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function resetSmsState() {
  smsSent.value = false
  smsCode.value = ''
  smsCountdown.value = 0
  if (smsTimer) clearInterval(smsTimer)
  smsTimer = null
}

function changeAuthPhone() {
  resetSmsState()
  authError.value = ''
  nextTick(() => authPhoneInputRef.value?.focus())
}

function startSmsCountdown(seconds = 60) {
  if (smsTimer) clearInterval(smsTimer)
  smsCountdown.value = Math.max(0, Math.ceil(Number(seconds) || 0))
  if (!smsCountdown.value) {
    smsTimer = null
    return
  }
  smsTimer = window.setInterval(() => {
    smsCountdown.value -= 1
    if (smsCountdown.value <= 0) {
      smsCountdown.value = 0
      clearInterval(smsTimer)
      smsTimer = null
    }
  }, 1000)
}

function onPhoneInput(event) {
  const previousDigits = phoneDigits.value
  let digits = String(event.target.value || '').replace(/\D/g, '')
  if (digits.startsWith('00')) digits = digits.slice(2)
  if (digits.length > 9 && digits.startsWith('233')) digits = digits.slice(3)
  if (digits.length === 10 && digits.startsWith('0')) digits = digits.slice(1)
  const nextDigits = digits.slice(0, 9)
  if (smsSent.value && nextDigits !== previousDigits) resetSmsState()
  authAccount.value = nextDigits
  // Keep the native control in sync with the sanitised value. This matters
  // for autofill, assistive technology and browsers that read input.value
  // before Vue's next render pass.
  event.target.value = nextDigits
}

function onSmsCodeInput(event) {
  const digits = String(event.target.value || '').replace(/\D/g, '').slice(0, 6)
  smsCode.value = digits
  event.target.value = digits
}

async function submitAuth() {
  if (phoneDigits.value.length !== 9 || smsBusy.value || (smsSent.value && smsCode.value.trim().length !== 6)) return
  smsBusy.value = true
  authError.value = ''
  try {
    const endpoint = smsSent.value ? '/auth/sms/verify' : '/auth/sms/send'
    const payload = smsSent.value
      ? { phone: authPhone.value, code: smsCode.value.trim(), name: authName.value.trim() || null }
      : { phone: authPhone.value }
    const result = await apiRequest(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!smsSent.value) {
      smsSent.value = true
      if (import.meta.env.DEV && result?.test_code) smsCode.value = result.test_code
      startSmsCountdown(result?.retry_after ?? 60)
      return
    }
    const previousUserId = authUser.value?.id
    const nextUser = result.user || null
    const switchedUser = previousUserId != null && String(previousUserId) !== String(nextUser?.id ?? '')
    if (switchedUser) {
      resetCheckoutState()
      step.value = 'catalog'
      activeTab.value = 'home'
    }
    localStorage.setItem('ebaphone_token', result.access_token)
    localStorage.setItem('ebaphone_user', JSON.stringify(nextUser))
    authUser.value = nextUser
    // Always replace checkout identity with the authenticated profile. Keeping
    // the previous values here can leak one customer's name/address into the
    // next customer's checkout when the same browser changes accounts.
    name.value = nextUser?.name || ''
    phone.value = nextUser?.phone || ''
    address.value = nextUser?.default_address || ''
    orderError.value = ''
    closeAuth()
    await loadOrders({ prompt: false })
    if (activeTab.value === 'msg') await loadSupportConversation()
    if (paymentReturn.value) await checkPaymentReturnStatus()
  } catch (error) {
    if (error.status === 429 && error.retryAfter > 0) {
      smsSent.value = true
      startSmsCountdown(error.retryAfter)
    }
    authError.value = error.message || 'Unable to continue'
  } finally {
    smsBusy.value = false
  }
}

async function resendCode() {
  if (smsCountdown.value > 0 || smsBusy.value || phoneDigits.value.length !== 9) return
  smsSent.value = false
  await submitAuth()
}

function logout(showMessage = true, { clearPaymentReturn = true } = {}) {
  localStorage.removeItem('ebaphone_token')
  localStorage.removeItem('ebaphone_user')
  authUser.value = null
  resetUserScopedState({ clearPaymentReturn })
  if (showMessage) cartNotice.value = 'You have been signed out.'
}

function classifyPaymentValue(status, responseCode = '') {
  const value = String(status || '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  const code = String(responseCode || '').trim().toLowerCase()
  // A provider may report a successful charge after the stock reservation has
  // expired.  The backend intentionally exposes that money as
  // `paid_pending_review`/`payment_review` until an operator resolves the
  // inventory or refund decision; never present it as a confirmed success in
  // the customer-facing payment return screen.
  if (/pending_review|review_required|payment_review|manual_review|under_review/.test(value)) return 'pending'
  if (/failed|failure|cancelled|canceled|declined|rejected|expired|error|unsuccessful|not_paid|amount_mismatch|currency_mismatch/.test(value)) return 'failed'
  if (/^(paid|deposit_paid|partial|success|successful|approved|complete|completed)$/.test(value)) return 'success'
  if (value && /(^|_)(paid|success|successful|approved|completed)($|_)/.test(value)) return 'success'
  if (!value && ['0000', '0'].includes(code)) return 'success'
  return 'pending'
}

function remotePaymentOutcome(remote) {
  if (!remote || typeof remote !== 'object') return classifyPaymentValue(remote)
  const statuses = []
  const responseCodes = []
  const visit = (value, depth = 0) => {
    if (!value || typeof value !== 'object' || depth > 5) return
    for (const [key, child] of Object.entries(value)) {
      const normalizedKey = key.toLowerCase().replace(/[^a-z]/g, '')
      if (child != null && typeof child !== 'object') {
        if (normalizedKey.includes('status') || normalizedKey === 'outcome') statuses.push(child)
        if (normalizedKey === 'responsecode') responseCodes.push(child)
      } else {
        visit(child, depth + 1)
      }
    }
  }
  visit(remote)
  for (const value of statuses) {
    const outcome = classifyPaymentValue(value)
    if (outcome === 'failed') return outcome
  }
  for (const value of statuses) {
    const outcome = classifyPaymentValue(value)
    if (outcome === 'success') return outcome
  }
  if (statuses.length) return 'pending'
  return responseCodes.some((code) => ['0000', '0'].includes(String(code).trim())) ? 'success' : 'pending'
}

function readPaymentReturnParams() {
  const parsed = parsePaymentReturn(window.location.href, paymentStorage())
  if (!parsed) return null
  const { orderId, reference, sourceStatus, responseCode, ownerUserId, fromStoredPayment } = parsed
  return {
    orderId,
    reference,
    sourceStatus,
    responseCode,
    ownerUserId,
    fromStoredPayment,
    urlOutcome: classifyPaymentValue(sourceStatus, responseCode),
    outcome: 'pending',
    providerStatus: null,
    checkedAt: '',
    needsAuth: !localStorage.getItem('ebaphone_token'),
  }
}

function resolvePaymentReturnOutcome(statusResult, state, matchedOrder) {
  const orderPaymentOutcome = classifyPaymentValue(matchedOrder?.payment_status)
  // A late success callback is recorded as paid locally but deliberately held
  // for an operator because its reservation has expired.  The payment row's
  // `paid` status must not override the order-level review state.
  if (matchedOrder?.payment_status === 'paid_pending_review' || matchedOrder?.order_status === 'payment_review') return 'pending'
  if (orderPaymentOutcome === 'success') return 'success'
  const localOutcome = classifyPaymentValue(statusResult?.local_status)
  if (localOutcome !== 'pending') return localOutcome
  if (statusResult?.remote && typeof statusResult.remote === 'object' && statusResult.remote.error) {
    return state.urlOutcome === 'failed' ? 'failed' : 'pending'
  }
  const remoteOutcome = remotePaymentOutcome(statusResult?.remote)
  if (remoteOutcome !== 'pending') return remoteOutcome
  // A cancellation/failure hint is safe to show immediately, but a URL
  // success flag alone is not proof of payment. Wait for the local webhook or
  // provider status before presenting a confirmed-payment state.
  if (state.urlOutcome === 'failed') return 'failed'
  if (!statusResult?.local_status && state.urlOutcome !== 'pending') return state.urlOutcome
  if (orderPaymentOutcome === 'failed' || ['cancelled', 'released'].includes(matchedOrder?.order_status)) return 'failed'
  return 'pending'
}

async function checkPaymentReturnStatus() {
  const state = paymentReturn.value
  if (!state || paymentReturnBusy.value) return
  activeTab.value = 'home'
  step.value = 'success'
  paymentReturnBusy.value = true
  paymentReturnError.value = ''
  state.needsAuth = !localStorage.getItem('ebaphone_token')

  if (!state.orderId) {
    state.outcome = state.urlOutcome === 'failed' ? 'failed' : 'pending'
    paymentReturnError.value = 'Hubtel returned without an order reference. Sign in and open Purchase history to verify the payment before retrying.'
    paymentReturnBusy.value = false
    return
  }
  if (state.needsAuth) {
    state.outcome = state.urlOutcome === 'failed' ? 'failed' : 'pending'
    paymentReturnBusy.value = false
    return
  }

  if (state.ownerUserId && authUser.value?.id != null && String(state.ownerUserId) !== String(authUser.value.id)) {
    state.outcome = 'failed'
    state.needsAuth = false
    paymentReturnError.value = 'This payment belongs to a different customer account. Open Purchase history on that account to check it.'
    clearRememberedPayment()
    paymentReturnBusy.value = false
    return
  }

  let statusResult = null
  let statusLookupFailed = false
  try {
    statusResult = await apiRequest(`/orders/${encodeURIComponent(state.orderId)}/payment-status`)
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: false })
      state.needsAuth = true
      state.outcome = state.urlOutcome === 'failed' ? 'failed' : 'pending'
      paymentReturnError.value = 'Your session expired. Sign in again to confirm this payment.'
      paymentReturnBusy.value = false
      return
    }
    paymentReturnError.value = error.message || 'We could not confirm the payment yet. Please check again in a moment.'
    statusLookupFailed = true
  }

  if (authUser.value) await loadOrders({ prompt: false })
  if (!authUser.value) {
    state.needsAuth = true
    state.outcome = state.urlOutcome === 'failed' ? 'failed' : 'pending'
    paymentReturnError.value ||= 'Your session expired. Sign in again to confirm this payment.'
    paymentReturnBusy.value = false
    return
  }
  const matchedOrder = orders.value.find((item) => String(item.id) === String(state.orderId)) || null
  if (matchedOrder) order.value = matchedOrder
  state.providerStatus = statusResult
  state.checkedAt = new Date().toISOString()
  state.needsAuth = !authUser.value
  state.outcome = statusLookupFailed
    ? (state.urlOutcome === 'failed' ? 'failed' : 'pending')
    : resolvePaymentReturnOutcome(statusResult, state, matchedOrder)
  if (state.outcome !== 'pending') clearRememberedPayment()
  paymentReturnBusy.value = false
}

async function handlePaymentReturn() {
  const state = readPaymentReturnParams()
  if (!state) return
  paymentReturn.value = state
  paymentReturnError.value = ''
  activeTab.value = 'home'
  step.value = 'success'
  selected.value = null
  order.value = null
  clearOrderAttempt()
  clearPaymentReturnUrl()
  window.scrollTo({ top: 0 })
  await checkPaymentReturnStatus()
}

function applySupportConversation(conversation) {
  const greeting = { role: 'assistant', text: 'Hi, I’m the EBAphone support assistant. I can help with FAQs, products and store information. For order-specific help, a team member can follow up here.' }
  const history = Array.isArray(conversation?.messages) ? conversation.messages.map((message) => ({
    role: message.sender_type === 'customer' ? 'user' : 'assistant',
    text: message.message,
  })) : []
  messages.value = [greeting, ...history]
}

async function loadSupportConversation() {
  if (!authUser.value || supportBusy.value) return
  supportBusy.value = true
  supportError.value = ''
  try {
    applySupportConversation(await apiRequest('/support/conversation'))
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      openAuth()
      supportError.value = 'Your session expired. Sign in again to continue.'
    } else {
      supportError.value = error.message || 'Support messages are temporarily unavailable.'
    }
  } finally {
    supportBusy.value = false
  }
}

async function sendMessage() {
  const text = chatInput.value.trim()
  if (!text || supportBusy.value) return
  if (text.length > 1000) {
    supportError.value = 'Please keep your message under 1,000 characters.'
    return
  }
  if (!authUser.value) {
    supportError.value = 'Sign in with your phone to send this message.'
    openAuth()
    return
  }
  supportBusy.value = true
  supportError.value = ''
  try {
    const conversation = await apiRequest('/support/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
    chatInput.value = ''
    applySupportConversation(conversation)
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      supportError.value = 'Your session expired. Sign in again to continue.'
      openAuth()
    } else {
      supportError.value = error.message || 'Unable to send this message.'
    }
  } finally {
    supportBusy.value = false
  }
}

function askQuick(question) {
  chatInput.value = question
  sendMessage()
}

function focusChatInput(event) {
  window.setTimeout(() => event.target.scrollIntoView({ block: 'center', behavior: 'smooth' }), 80)
}

async function saveProfile() {
  if (!authUser.value || profileBusy.value) return
  if (profileDraft.value.name.trim().length < 2) {
    profileError.value = 'Enter your full name.'
    return
  }
  profileBusy.value = true
  profileError.value = ''
  try {
    const updated = await apiRequest('/auth/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: profileDraft.value.name.trim(),
        email: profileDraft.value.email.trim() || null,
        default_address: profileDraft.value.default_address.trim() || null,
      }),
    })
    authUser.value = updated
    localStorage.setItem('ebaphone_user', JSON.stringify(updated))
    name.value = updated.name || ''
    phone.value = updated.phone || ''
    // An explicitly cleared default address comes back as null. Do not keep
    // the previous checkout address in that case.
    address.value = updated.default_address || ''
    cartNotice.value = 'Account details saved.'
    window.setTimeout(() => { cartNotice.value = '' }, 2800)
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      openAuth()
      profileError.value = 'Your session expired. Sign in again to continue.'
    } else {
      profileError.value = error.message || 'Unable to save account details.'
    }
  } finally {
    profileBusy.value = false
  }
}

async function placeOrder() {
  orderError.value = ''
  if (!authUser.value) {
    orderError.value = 'Sign in with your phone before placing an order.'
    openAuth()
    return
  }
  if (!canPlaceOrder.value) {
    if (maxSelectedStoreStock.value < Math.max(1, Number(selectedQuantity.value) || 1)) orderError.value = 'A single store does not have enough stock for this quantity.'
    else if (!name.value.trim()) orderError.value = 'Enter your full name to continue.'
    else if (checkoutPhone.value.replace(/\D/g, '').length < 7) orderError.value = 'Enter a valid phone number to continue.'
    else if (plan.value === 'full' && fulfillment.value === 'shipping') orderError.value = 'Enter a delivery address of at least 10 characters.'
    else orderError.value = 'Choose an available store to continue.'
    return
  }
  orderBusy.value = true
  orderError.value = ''
  paymentError.value = ''
  const payload = {
    sku_id: selected.value.id,
    quantity: Math.max(1, Math.floor(Number(selectedQuantity.value) || 1)),
    payment_plan: plan.value,
    customer_name: name.value.trim(),
    customer_phone: checkoutPhone.value.trim(),
  }
  if (plan.value === 'full') {
    payload.fulfillment_type = fulfillment.value
    if (fulfillment.value === 'pickup') payload.store_id = Number(storeId.value)
    else payload.shipping_address = address.value.trim()
  } else {
    payload.store_id = Number(storeId.value)
  }
  const idempotencyKey = idempotencyKeyFor(payload)
  try {
    order.value = await apiRequest('/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    })
    const cartItem = cart.value.find((item) => item.id === selected.value.id)
    if (cartItem) {
      const remaining = safeCartQuantity(cartItem) - payload.quantity
      if (remaining > 0) cartItem.qty = remaining
      else removeFromCart(cartItem)
    }
    clearOrderAttempt()
    step.value = 'success'
    activeTab.value = 'home'
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (error) {
    if (error.status === 401) {
      logout(false, { clearPaymentReturn: !paymentReturn.value })
      orderError.value = 'Your session expired. Sign in again to continue.'
      openAuth()
      clearOrderAttempt()
      return
    }
    if (!error.status) {
      orderError.value = 'The connection dropped before we could confirm the order. Please try again; your checkout will not be duplicated.'
      // Keep the key for a safe retry after a transient network failure.
    } else {
      clearOrderAttempt()
      orderError.value = error.message || 'Unable to create the order.'
    }
  } finally {
    orderBusy.value = false
  }
}

async function payNow() {
  if (!order.value || paymentBusy.value) return
  paymentBusy.value = true
  paymentError.value = ''
  try {
    const data = await apiRequest(`/orders/${order.value.id}/payment-session`, { method: 'POST' })
    if (!data?.checkout_url) throw new Error('The payment provider did not return a checkout link.')
    rememberPaymentAttempt(order.value.id, data.checkout_id)
    window.location.href = data.checkout_url
  } catch (error) {
    paymentError.value = error.message || 'Unable to start payment.'
  } finally {
    paymentBusy.value = false
  }
}

function storeDirections(store) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${store.name}, ${store.address}`)}`
}

watch(cart, (value) => {
  localStorage.setItem('ebaphone_cart', JSON.stringify(value))
  const ids = new Set(value.map((item) => item.id))
  selectedCartIds.value = selectedCartIds.value.filter((id) => ids.has(id))
}, { deep: true })
watch([
  activeTab,
  step,
  meSection,
  activeCategory,
  search,
  selectedQuantity,
  plan,
  fulfillment,
  storeId,
  () => selected.value?.id,
  () => order.value?.id,
  () => paymentReturn.value?.outcome,
], () => {
  if (pageStateReady.value) persistPageState()
})
watch([name, phone, address, storeId, plan, fulfillment, selectedQuantity], () => {
  orderError.value = ''
  if (selected.value) chooseFirstAvailableStore(selected.value)
})
watch([authAccount, authName, smsCode], () => { authError.value = '' })
watch(authUser, (user) => {
  profileDraft.value = {
    name: user?.name || '',
    email: user?.email || '',
    default_address: user?.default_address || '',
  }
  if (!user) {
    // Keep paymentReturn intact so an expired session can be re-authenticated
    // on the Hubtel return page, but never retain the old customer's checkout
    // identity or order details.
    resetCheckoutState()
    return
  }
  name.value = user.name || ''
  phone.value = user.phone || ''
  address.value = user.default_address || ''
}, { immediate: true })
watch(bannerIndex, () => { bannerImageFailed.value = false })
watch(smsSent, async (sent) => {
  if (!authOpen.value) return
  await nextTick()
  if (sent) smsCodeInputRef.value?.focus()
  else authPhoneInputRef.value?.focus()
})
watch(authOpen, (open) => {
  document.body.classList.toggle('modal-open', open)
})

onMounted(async () => {
  await Promise.all([loadCatalog(), restoreAuthenticatedUser()])
  await restorePageState()
  pageStateReady.value = true
  persistPageState()
  if (readPaymentReturnParams()) await handlePaymentReturn()
  else if (paymentReturn.value) await checkPaymentReturnStatus()
  if (window.visualViewport) {
    syncKeyboardOffset()
    window.visualViewport.addEventListener('resize', syncKeyboardOffset)
    window.visualViewport.addEventListener('scroll', syncKeyboardOffset)
  }
  window.addEventListener('beforeunload', persistPageState)
})

onBeforeUnmount(() => {
  document.body.classList.remove('modal-open')
  if (smsTimer) clearInterval(smsTimer)
  if (window.visualViewport) {
    window.visualViewport.removeEventListener('resize', syncKeyboardOffset)
    window.visualViewport.removeEventListener('scroll', syncKeyboardOffset)
  }
  window.removeEventListener('beforeunload', persistPageState)
})
</script>

<template>
  <header class="topbar">
    <div class="nav wrap">
      <button class="brand" aria-label="EBAphone home" @click="goHome"><span>EBA</span>phone</button>
      <nav aria-label="Main navigation">
        <button class="nav-link" :class="{ active: activeTab === 'home' }" @click="goHome">Products</button>
        <button class="nav-link" :class="{ active: activeTab === 'stores' }" @click="goStores">Stores</button>
        <button class="nav-link" :class="{ active: activeTab === 'msg' }" @click="goSupport">Support</button>
        <button class="nav-link" :class="{ active: activeTab === 'me' }" @click="authUser ? goMe('cart') : openAuth()">{{ authUser ? 'Account' : 'Sign in' }}</button>
      </nav>
      <button class="mobile-store-link" type="button" @click="goStores">Stores</button>
      <button class="icon cart-button" aria-label="Open shopping cart" @click="goMe('cart')"><ShoppingCart /><sup v-if="cartCount">{{ cartCount }}</sup></button>
    </div>
  </header>

  <main v-if="activeTab === 'msg'" class="mobile-page wrap chat-page">
    <div class="page-title"><p class="eyebrow">EBAphone AI support assistant</p><h1>How can we help?</h1><p>Ask about FAQs, products, prices, stock and store locations. Order-specific help is handled by our support team.</p></div>
    <div class="chat-box" aria-live="polite">
      <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" :class="['bubble', message.role]">{{ message.text }}</div>
      <div v-if="!hasUserMessage" class="quick-questions" aria-label="Suggested questions">
        <button v-for="question in quickQuestions" :key="question" type="button" :disabled="supportBusy" @click="askQuick(question)">{{ question }}</button>
      </div>
      <p v-if="supportError" class="chat-error" role="alert" aria-live="assertive">{{ supportError }}</p>
    </div>
    <form class="chat-compose" @submit.prevent="sendMessage">
      <input v-model="chatInput" aria-label="Message" autocomplete="off" maxlength="1000" placeholder="Ask about products or stores..." :disabled="supportBusy" @focus="focusChatInput" />
      <button type="submit" :disabled="supportBusy || !chatInput.trim()">{{ supportBusy ? 'Sending…' : 'Send' }}</button>
    </form>
  </main>

  <main v-else-if="activeTab === 'stores'" class="stores-page wrap">
    <div class="page-title"><p class="eyebrow">Across Ghana</p><h1>Find an EBAphone store</h1><p>Choose the nearest store for pickup, support and faster local fulfilment.</p></div>
    <div v-if="deliveryCoverage" class="coverage-note"><Truck /><div><b>Local delivery coverage</b><span>{{ deliveryCoverage.zones.join(', ') }} · {{ deliveryCoverage.fee_policy }}</span><small>{{ deliveryCoverage.timing }}</small></div></div>
    <div v-if="!stores.length && !loading" class="empty">Store locations are unavailable right now. Please try again later.</div>
    <div class="store-grid">
      <article v-for="store in stores" :key="store.id" class="store-card">
        <div class="store-card-icon"><Store /></div>
        <h2>{{ store.name }}</h2>
        <p><MapPin />{{ store.address }}</p>
        <p><PhoneCall /><a :href="`tel:${store.phone}`">{{ store.phone }}</a></p>
        <p class="store-hours"><Package />{{ store.open_hours }}</p>
        <div class="store-actions"><a class="secondary" :href="storeDirections(store)" target="_blank" rel="noreferrer">Directions</a><button class="primary small" @click="goHome">Shop products</button></div>
      </article>
    </div>
  </main>

  <main v-else-if="activeTab === 'me'" class="mobile-page wrap account-page">
    <div class="profile-card">
      <div class="avatar">{{ initials(authUser?.name) }}</div>
      <div><h2>{{ authUser?.name || 'Guest customer' }}</h2><p>{{ authUser?.phone || 'Sign in to manage your orders' }}</p></div>
      <button @click="authUser ? logout() : openAuth()">{{ authUser ? 'Sign out' : 'Sign in' }}</button>
    </div>
    <section v-if="authUser" class="me-section profile-editor" aria-labelledby="profile-heading">
      <div class="section-line"><h2 id="profile-heading">Account details</h2><span>Used for faster checkout</span></div>
      <form class="profile-form" @submit.prevent="saveProfile">
        <div class="field">
          <label for="profile-name">Full name</label>
          <input id="profile-name" v-model="profileDraft.name" autocomplete="name" maxlength="120" required />
        </div>
        <div class="field">
          <label for="profile-email">Email <span class="optional-label">(optional)</span></label>
          <input id="profile-email" v-model="profileDraft.email" type="email" autocomplete="email" maxlength="160" placeholder="you@example.com" />
        </div>
        <div class="field">
          <label for="profile-address">Default delivery address <span class="optional-label">(optional)</span></label>
          <textarea id="profile-address" v-model="profileDraft.default_address" autocomplete="street-address" maxlength="500" rows="3" placeholder="Add your usual delivery address"></textarea>
        </div>
        <p v-if="profileError" class="inline-error" role="alert" aria-live="assertive">{{ profileError }}</p>
        <button class="primary profile-save" type="submit" :disabled="profileBusy">{{ profileBusy ? 'Saving…' : 'Save account details' }}</button>
      </form>
    </section>
    <div class="quick-orders">
      <button @click="selectMeView('cart')"><b>{{ cartCount }}</b><span>To pay</span></button>
      <button @click="selectMeView('receive')"><b>{{ orders.filter((item) => item.order_status === 'shipped').length }}</b><span>To receive</span></button>
      <button @click="selectMeView('completed')"><b>{{ completedOrderCount }}</b><span>Completed</span></button>
      <button @click="goSupport"><b>?</b><span>Help</span></button>
    </div>
    <p v-if="cartNotice" class="toast" role="status">{{ cartNotice }}</p>
    <section v-if="meSection === 'cart'" id="cart-section" ref="cartSectionRef" class="me-section" aria-labelledby="cart-heading">
      <div class="section-line"><h2 id="cart-heading">Shopping cart</h2><span>{{ cartCount }} items</span></div>
      <div v-if="!cart.length" class="empty">Your cart is empty.<button @click="goHome">Browse products</button></div>
      <template v-else>
        <div class="cart-select-bar"><label class="cart-select-all"><input type="checkbox" :checked="allCartSelected" @change="toggleAllCartSelection" /> <span>Select all</span></label><span class="cart-select-hint">Select items to checkout</span></div>
        <div v-for="item in cart" :key="item.id" class="cart-item" :class="{ 'cart-item-unavailable': cartStockLimit(item) < 1 }">
          <label class="cart-check"><input type="checkbox" :checked="selectedCartIds.includes(item.id)" :aria-label="`Select ${item.product_name}`" @change="toggleCartSelection(item)" /></label>
          <img class="cart-item-image" :src="item.image" :alt="item.product_name" loading="lazy" @error="useImageFallback($event, item.product_name)" />
          <div class="cart-item-main"><b>{{ item.product_name }}</b><span class="cart-variant">{{ item.variant }}</span><div class="cart-price-quantity"><strong class="cart-item-price">{{ money(item.price) }}</strong><div class="cart-item-quantity"><span class="cart-mobile-label">Quantity</span><div class="quantity" :aria-label="`Quantity for ${item.product_name}`"><button type="button" aria-label="Decrease quantity" :disabled="safeCartQuantity(item) < 1" @click="changeCartQuantity(item, -1)">−</button><span>{{ safeCartQuantity(item) }}</span><button type="button" aria-label="Increase quantity" :disabled="safeCartQuantity(item) >= cartStockLimit(item)" @click="changeCartQuantity(item, 1)">+</button></div></div></div></div>
        </div>
        <div class="cart-settle-bar"><label><input type="checkbox" :checked="allCartSelected" @change="toggleAllCartSelection" /> <span>Selected {{ selectedCartCount }} item{{ selectedCartCount === 1 ? '' : 's' }}</span></label><strong>{{ money(selectedCartTotal) }}</strong><button class="primary" :disabled="!selectedCartItems.length" @click="checkoutSelectedCartItems">Checkout selected</button></div>
      </template>
    </section>
    <section v-else id="orders-section" ref="ordersSectionRef" class="me-section" aria-labelledby="orders-heading">
      <div class="section-line"><h2 id="orders-heading">{{ meSection === 'receive' ? 'To receive' : 'Completed' }}</h2><button class="text-button" :disabled="ordersBusy" @click="loadOrders()">{{ ordersBusy ? 'Loading…' : 'Refresh' }}</button></div>
      <div v-if="ordersError" class="inline-error" role="alert" aria-live="assertive">{{ ordersError }} <button @click="loadOrders()">Try again</button></div>
      <div v-else-if="!authUser" class="empty">Sign in to view your orders.<button @click="openAuth">Sign in</button></div>
      <div v-else-if="!visibleOrders.length && !ordersBusy" class="empty">No orders in this section.<button @click="selectMeView('cart')">View shopping cart</button></div>
      <article v-for="item in visibleOrders.slice(0, 8)" :key="item.id" class="order-item">
        <div class="order-item-main">
          <b>{{ item.product_name }}<template v-if="item.quantity > 1"> × {{ item.quantity }}</template></b>
          <span>{{ item.id }} · {{ item.fulfillment_type === 'pickup' ? 'Store pickup' : item.fulfillment_type === 'shipping' ? 'Delivery' : 'Store reservation' }}</span>
          <small v-if="item.store_name">{{ item.store_name }}</small>
          <small v-if="item.pickup_code" class="order-detail">Pickup code: <strong>{{ item.pickup_code }}</strong></small>
          <small v-if="item.tracking_number" class="order-detail">Tracking: <strong>{{ item.tracking_number }}</strong></small>
          <small class="order-detail">Payment: <strong>{{ statusLabel(item.payment_status) }}</strong></small>
          <small v-if="balanceAfterInitialPayment(item) > 0" class="order-detail">{{ balanceLabel(item) }}: <strong>{{ money(balanceAfterInitialPayment(item)) }}</strong></small>
          <small class="order-detail">{{ fulfillmentEstimate(item) }}</small>
          <small class="order-detail">{{ dateLabel(item.created_at) }}</small>
        </div>
        <div class="order-item-side">
          <strong class="order-status">{{ statusLabel(item.order_status) }}</strong>
          <button type="button" class="text-button order-details-toggle" :aria-expanded="orderDetail?.id === item.id" :aria-controls="`order-details-${item.id}`" @click="toggleOrderDetail(item)">{{ orderDetail?.id === item.id ? 'Hide details' : 'View details' }}</button>
          <button v-if="canContinuePayment(item)" type="button" class="primary order-pay-button" :disabled="orderPaymentBusy === item.id" @click="continueOrderPayment(item)">{{ orderPaymentBusy === item.id ? 'Opening…' : 'Continue payment' }}</button>
          <button v-if="canCancelOrder(item)" type="button" class="remove-button cancel-order" :disabled="orderCancelBusy === item.id" @click="cancelOrder(item)">{{ orderCancelBusy === item.id ? 'Cancelling…' : 'Cancel order' }}</button>
        </div>
        <div v-if="orderDetail?.id === item.id" :id="`order-details-${item.id}`" class="order-expanded">
          <div><span>Variant</span><b>{{ item.variant }}</b></div>
          <div><span>Quantity</span><b>{{ item.quantity || 1 }}</b></div>
          <div><span>Unit price</span><b>{{ money(item.unit_price) }}</b></div>
          <div><span>Order total</span><b>{{ money(item.total_amount || item.unit_price) }}</b></div>
          <div><span>Initial payment</span><b>{{ money(item.deposit_amount) }}</b></div>
          <div><span>Paid</span><b>{{ money(item.paid_amount) }}</b></div>
          <div><span>{{ balanceLabel(item) }}</span><b>{{ money(balanceAfterInitialPayment(item)) }}</b></div>
          <div><span>Fulfillment</span><b>{{ item.fulfillment_type === 'shipping' ? item.shipping_address : item.store_name || 'Store pickup' }}</b></div>
          <div><span>Estimated timing</span><b>{{ fulfillmentEstimate(item) }}</b></div>
          <div v-if="item.release_reason"><span>Order note</span><b>{{ item.release_reason }}</b></div>
        </div>
      </article>
    </section>
    <section class="settings" aria-label="Account shortcuts"><button @click="authUser ? logout() : openAuth()">{{ authUser ? 'Sign out of this device' : 'Sign in with phone' }} <ChevronRight /></button><button @click="goStores">Store locations and opening hours <ChevronRight /></button><button @click="goSupport">Contact support <ChevronRight /></button></section>
  </main>

  <main v-else-if="step === 'catalog'">
    <div v-if="apiError" class="api-error wrap" role="alert">{{ apiError }} <button @click="reloadPage">Refresh</button></div>
    <section class="intro wrap banner" :class="{ 'banner-with-media': bannerHasImage }">
      <div class="banner-copy"><p class="eyebrow">{{ bannerIndex === 0 ? 'Genuine products. Flexible payments.' : 'Your local device partner.' }}</p><h1>{{ currentBanner?.title || 'Your next device, made affordable.' }}</h1><p>{{ currentBanner?.subtitle || 'Pay in full or reserve your product at a nearby EBAphone store.' }}</p></div>
      <div class="banner-media" :class="{ 'banner-fallback': !bannerHasImage }" aria-label="EBAphone promotion">
        <img v-if="bannerHasImage" :src="currentBanner.image" :alt="currentBanner.title || 'EBAphone promotion'" loading="eager" @error="markBannerImageFailed" />
        <span v-else aria-hidden="true"><b>EBA</b>phone</span>
      </div>
      <div v-if="banners.length > 1" class="banner-dots"><button v-for="(_, index) in banners" :key="index" type="button" :aria-label="`Show banner ${index + 1}`" :aria-pressed="index === bannerIndex" :class="{ active: index === bannerIndex }" @click="bannerIndex = index"></button></div>
    </section>
    <nav class="category-strip wrap" aria-label="Product categories"><button v-for="category in categoryOptions" :key="category.id" type="button" :aria-pressed="activeCategory === category.id" :class="{ active: activeCategory === category.id }" @click="selectCategory(category.id)">{{ category.label }} <small>{{ categoryCounts[category.id] }}</small></button></nav>
    <section class="catalog wrap">
      <div v-if="loading" class="loading" role="status">Loading products…</div>
      <div v-else-if="!filtered.length" class="empty catalog-empty">No products match this search or category.<button v-if="search || activeCategory !== 'all'" @click="search = ''; activeCategory = 'all'">Show all products</button></div>
      <div v-else class="products"><article v-for="item in filtered" :key="item.id" class="product" @click="choose(item)"><button type="button" class="product-photo-button" :aria-label="`View ${item.product_name}`" @click.stop="choose(item)"><span class="photo"><img :src="item.image" :alt="item.product_name" loading="lazy" @error="useImageFallback($event, item.product_name)" /><span class="tag">{{ item.deposit_rate }}% deposit</span></span></button><div class="product-info"><button type="button" class="product-title-button" @click.stop="choose(item)">{{ item.product_name }}</button><span>{{ item.variant }}</span><div class="price"><b>{{ cardMoney(item.price) }}</b><button type="button" class="add-cart-button" aria-label="Add to cart" @click.stop="addToCart(item)">+</button></div></div></article></div>
    </section>
  </main>

  <main v-else-if="step === 'detail' && selected" class="detail wrap">
    <button class="back" @click="step = 'catalog'"><ArrowLeft /> Back to products</button>
    <div class="detail-grid"><div class="detail-photo"><img :src="selected.image" :alt="selected.product_name" @error="useImageFallback($event, selected.product_name)" /><span>{{ totalSelectedStock }} available across {{ storesWithStock(selected) }} stores</span></div>
      <div class="buy"><div class="detail-title-row"><h1>{{ selected.product_name }}</h1><p class="variant">{{ selected.variant }}</p></div><div class="detail-price-row"><h2>{{ money(selected.price) }}</h2><div class="quantity-summary"><span>Quantity</span><div class="quantity detail-quantity" :aria-label="`Quantity for ${selected.product_name}`"><button type="button" aria-label="Decrease quantity" :disabled="selectedQuantity <= 1" @click="changeSelectedQuantity(-1)">−</button><b>{{ selectedQuantity }}</b><button type="button" aria-label="Increase quantity" :disabled="selectedQuantity >= maxSelectedStoreStock" @click="changeSelectedQuantity(1)">+</button></div><span class="unit-price">{{ money(selected.price) }} each</span></div></div>
        <div class="choice-title">How would you like to pay?</div><div class="segmented"><button type="button" :class="{ active: plan === 'deposit' }" @click="plan = 'deposit'"><span>Pay deposit</span><small>{{ selected.deposit_rate }}% today</small></button><button type="button" :class="{ active: plan === 'full' }" @click="plan = 'full'"><span>Pay in full</span><small>Delivery or pickup</small></button></div>
        <div v-if="plan === 'deposit'" class="deposit-note"><div><b>Reserve {{ selectedQuantity }} unit{{ selectedQuantity === 1 ? '' : 's' }} with {{ money(dueNow) }}</b><p>The remaining {{ money(Number(selected.price) * selectedQuantity - dueNow) }} is completed in store.</p></div></div>
        <template v-if="plan === 'full'"><div class="choice-title">How will you receive it?</div><div class="fulfillment"><button type="button" :class="{ active: fulfillment === 'pickup' }" @click="fulfillment = 'pickup'"><Store />Store pickup</button><button type="button" :class="{ active: fulfillment === 'shipping' }" @click="fulfillment = 'shipping'"><Truck />Delivery</button></div></template>
        <div v-if="plan === 'deposit' || fulfillment === 'pickup'" class="field store-field"><label for="store-select">Select a store</label><select id="store-select" v-model="storeId"><option v-for="store in stores" :key="store.id" :value="store.id" :disabled="stockFor(selected, store.id) < Math.max(1, Number(selectedQuantity) || 1)">{{ store.name }} · {{ stockLabel(selected, store.id) }}</option></select><p v-if="selectedStore"><MapPin />{{ selectedStore.address }} · {{ selectedStore.open_hours }}</p><div class="store-availability"><span v-for="store in stores" :key="store.id" :class="{ available: stockFor(selected, store.id) >= Math.max(1, Number(selectedQuantity) || 1) }">{{ store.name }}: {{ stockLabel(selected, store.id) }}</span></div></div>
        <div v-if="plan === 'full' && fulfillment === 'shipping'" class="field"><label for="delivery-address">Delivery address</label><textarea id="delivery-address" v-model="address" minlength="10" maxlength="500" placeholder="Street, area, city (Accra, Tema or Kumasi)" autocomplete="street-address"></textarea><small class="field-hint">Use a full address in Accra, Tema or Kumasi.</small></div>
        <div class="customer"><div class="field compact-field"><label for="customer-name">Full name</label><input id="customer-name" v-model="name" placeholder="Your name" autocomplete="name" /></div><div class="field compact-field"><label for="customer-phone">Account phone</label><div id="customer-phone" class="account-phone" aria-label="Account phone">{{ checkoutPhone }}</div><small>This order uses your verified login number.</small></div></div>
        <p v-if="orderError" class="inline-error" role="alert" aria-live="assertive">{{ orderError }}</p><div class="summary"><span>Due today</span><b>{{ money(dueNow) }}</b></div><button class="primary" :disabled="!canPlaceOrder" @click="placeOrder">{{ orderBusy ? 'Creating order…' : !authUser ? 'Sign in to continue' : plan === 'deposit' ? 'Reserve and continue' : 'Continue to payment' }}</button>
      </div></div>
  </main>

  <main v-else-if="paymentReturn" class="success wrap payment-return-page">
    <div class="success-mark" :class="{ failed: paymentReturnOutcome === 'failed', pending: paymentReturnOutcome === 'pending' }"><Check v-if="paymentReturnOutcome === 'success'" /><X v-else-if="paymentReturnOutcome === 'failed'" /><span v-else>…</span></div>
    <p class="eyebrow">{{ paymentReturn.providerStatus?.provider || 'Hubtel payment' }}</p>
    <h1>{{ paymentReturnTitle }}</h1>
    <p>{{ paymentReturnDescription }}</p>
    <div class="receipt">
      <div v-if="paymentReturn.orderId"><span>Order</span><b>{{ paymentReturn.orderId }}</b></div>
      <div v-if="order?.product_name"><span>Product</span><b>{{ order.product_name }}</b></div>
      <div v-if="order?.store_name"><span>Store</span><b>{{ order.store_name }}</b></div>
      <div v-if="paymentReturn.reference"><span>Payment reference</span><b>{{ paymentReturn.reference }}</b></div>
      <div v-if="paymentReturn.checkedAt"><span>Last checked</span><b>{{ dateLabel(paymentReturn.checkedAt) }}</b></div>
    </div>
    <p v-if="paymentReturnError" class="inline-error" role="alert" aria-live="assertive">{{ paymentReturnError }}</p>
    <button v-if="paymentReturn.needsAuth" class="primary" @click="openAuth">Sign in to check status</button>
    <button v-else-if="paymentReturnOutcome === 'pending'" class="primary" :disabled="paymentReturnBusy" @click="checkPaymentReturnStatus">{{ paymentReturnBusy ? 'Checking…' : 'Check payment status' }}</button>
    <button v-if="order?.payment_status === 'pending' && !paymentReturn.needsAuth" class="secondary full-width" :disabled="paymentBusy" @click="payNow">{{ paymentBusy ? 'Connecting…' : 'Retry payment' }}</button>
    <button class="secondary full-width success-back" @click="goHome">Continue shopping</button>
  </main>

  <main v-else class="success wrap"><div class="success-mark"><Check /></div><p class="eyebrow">{{ order?.payment_status === 'pending' ? 'Order created' : 'Payment confirmed' }}</p><h1>{{ order?.payment_status === 'pending' ? 'Your product is almost yours.' : 'Your product is reserved.' }}</h1><p v-if="order?.payment_status === 'pending'">Complete your secure payment of <b>{{ money(order.deposit_amount) }}</b> to confirm the order.</p><p v-else>Your payment has been confirmed. Our store team will handle the next step.</p><div class="receipt"><div><span>Order</span><b>{{ order?.id }}</b></div><div><span>Product</span><b>{{ order?.product_name }}</b></div><div v-if="order?.quantity > 1"><span>Quantity</span><b>{{ order.quantity }}</b></div><div v-if="order?.store_name"><span>Store</span><b>{{ order.store_name }}</b></div><div><span>Balance after payment</span><b>{{ money(order?.remaining_amount) }}</b></div></div><p v-if="paymentError" class="inline-error" role="alert">{{ paymentError }}</p><button v-if="order?.payment_status === 'pending'" class="primary" :disabled="paymentBusy" @click="payNow">{{ paymentBusy ? 'Connecting…' : 'Pay securely' }}</button><button class="secondary full-width success-back" @click="goHome">Continue shopping</button></main>

  <nav class="mobile-bottom-nav" aria-label="Mobile tabs"><button :class="{ active: activeTab === 'home' }" @click="goHome"><House />Home</button><button :class="{ active: activeTab === 'msg' }" @click="goSupport"><Headphones />Support</button><button :class="{ active: activeTab === 'me' }" @click="goMe('cart')"><UserRound />Me</button></nav>

<div v-if="authOpen" class="auth-overlay" @click.self="closeAuth"><div ref="authCardRef" class="auth-card" role="dialog" aria-modal="true" aria-labelledby="auth-title" :aria-describedby="authError ? 'auth-error' : undefined" @keydown="trapAuthFocus"><button type="button" class="auth-close" aria-label="Close sign in" @click="closeAuth"><X /></button><p class="eyebrow">EBAphone account</p><h2 id="auth-title">Sign in with your phone</h2><div class="phone-field"><span class="phone-prefix"><span class="ghana-flag" aria-hidden="true">🇬🇭</span><b>+233</b></span><div class="phone-number-part"><div class="phone-input-wrap"><div class="phone-slots" aria-hidden="true"><span v-for="(digit, index) in phoneSlots" :key="index" class="phone-slot"><span class="phone-placeholder">0</span><span v-if="digit" class="phone-digit">{{ digit }}</span></span></div><input ref="authPhoneInputRef" v-model="authAccount" type="tel" :aria-invalid="Boolean(authError)" aria-label="Nine digit Ghana phone number" inputmode="numeric" pattern="[0-9]*" maxlength="16" autocomplete="tel-national" @input="onPhoneInput" /></div><span class="phone-counter" aria-live="polite" aria-atomic="true">{{ phoneDigits.length }}/9</span></div></div><input v-if="smsSent" ref="smsCodeInputRef" v-model="smsCode" @input="onSmsCodeInput" :aria-invalid="Boolean(authError)" aria-label="Verification code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="6-digit verification code" @keyup.enter="submitAuth" /><input v-if="!smsSent" v-model="authName" aria-label="Your name" placeholder="Your name (optional)" autocomplete="name" /><p v-if="authError" id="auth-error" class="auth-error" role="alert" aria-live="assertive">{{ authError }}</p><button type="button" class="primary" :disabled="smsBusy || phoneDigits.length !== 9 || (smsSent && smsCode.length !== 6)" @click="submitAuth">{{ smsBusy ? 'Please wait…' : smsSent ? 'Verify and sign in' : 'Send verification code' }}</button><button v-if="smsSent" type="button" class="auth-switch" :disabled="smsBusy || smsCountdown > 0" @click="resendCode">{{ smsCountdown ? `Resend in ${smsCountdown}s` : 'Resend code' }}</button><button v-if="smsSent" type="button" class="auth-switch" @click="changeAuthPhone">Change phone number</button></div></div>
</template>
