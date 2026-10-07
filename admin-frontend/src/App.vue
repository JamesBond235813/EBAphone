<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  BarChart3,
  Bot,
  Boxes,
  CheckCircle2,
  Clock3,
  Copy,
  Download,
  Edit3,
  ExternalLink,
  LayoutDashboard,
  KeyRound,
  LockKeyhole,
  LogOut,
  Menu,
  MapPin,
  MessageCircle,
  PackageSearch,
  Phone,
  Plus,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  ShieldCheck,
  ShoppingBag,
  Store,
  Truck,
  UserRound,
  UserCog,
  Users,
  WalletCards,
  X,
} from 'lucide-vue-next'
import BannerManager from './BannerManager.vue'

const api = '/api'
const PAGE_STATE_KEY = 'ebaphone_admin_current_page'
const pageStateReady = ref(false)
const token = ref(localStorage.getItem('eba_admin_token'))
const sessionChecking = ref(Boolean(token.value))
function storedJson(key, fallback = null) {
  try {
    const value = localStorage.getItem(key)
    return value ? JSON.parse(value) : fallback
  } catch {
    return fallback
  }
}
const admin = ref(storedJson('eba_admin_user'))
const username = ref('')
const password = ref('')
const loginBusy = ref(false)
const loginError = ref('')
const page = ref('dashboard')
const orders = ref([])
const skus = ref([])
const stores = ref([])
const adminUsers = ref([])
const customers = ref([])
const supportConversations = ref([])
const loading = ref(false)
const loadError = ref('')
const notice = ref('')
const lastRefresh = ref(null)
const health = ref(null)
const mobileNavOpen = ref(false)
const assistantConfig = ref({ enabled: false, base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini', api_key_configured: false, prompt: 'Answer briefly and helpfully. Use the catalog, store, and FAQ information provided below.', temperature: 0.3, max_tokens: 300, max_input_chars: 1000, history_messages: 8, per_user_cooldown_seconds: 3, per_user_daily_limit: 20, global_daily_limit: 1000, usage_today: 0 })
const assistantApiKey = ref('')
const assistantClearKey = ref(false)
const assistantBusy = ref(false)
const assistantTesting = ref(false)
const assistantError = ref('')
const assistantNotice = ref('')

const nav = [
  ['dashboard', 'Dashboard', LayoutDashboard],
  ['users', 'Customers', Users],
  ['orders', 'Orders', ShoppingBag],
  ['catalog', 'Products', Boxes],
  ['inventory', 'Inventory', PackageSearch],
  ['finance', 'Finance', WalletCards],
  ['service', 'Customer service', MessageCircle],
  ['assistant', 'AI assistant', Bot],
  ['fulfillment', 'Fulfillment', Truck],
  ['reports', 'Reports', BarChart3],
  ['banners', 'Banners', LayoutDashboard],
  ['stores', 'Stores', Store],
  ['staff', 'Staff accounts', UserCog],
  ['settings', 'Settings', Settings],
]

const pageTitle = computed(() => nav.find((item) => item[0] === page.value)?.[1] || 'Dashboard')
const money = (value) => new Intl.NumberFormat('en-GH', { style: 'currency', currency: 'GHS' }).format(Number(value) || 0)
const orderTotal = (order) => Number(order?.total_amount ?? (Number(order?.unit_price || 0) * Math.max(1, Number(order?.quantity || 1))))
const dateLabel = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('en-GH', { dateStyle: 'medium', timeStyle: 'short' })
}
const shortDate = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('en-GH', { month: 'short', day: 'numeric' })
}
const statusLabel = (value) => String(value || 'unknown').replaceAll(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const statusClass = (value) => `status-${String(value || 'unknown').replaceAll('_', '-')}`
function useProductImageFallback(event, label = 'EBAphone') {
  const image = event?.target
  if (!image || image.dataset.fallbackApplied) return
  image.dataset.fallbackApplied = 'true'
  const safeLabel = String(label || 'EBAphone').slice(0, 32).replace(/[<>&'\"]/g, (character) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[character]))
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 700"><rect width="900" height="700" fill="#efe2d5"/><circle cx="450" cy="280" r="112" fill="#fff8f2"/><text x="450" y="285" text-anchor="middle" dominant-baseline="middle" font-family="Arial,sans-serif" font-size="54" font-weight="700" fill="#ff666b">EBA</text><text x="450" y="505" text-anchor="middle" font-family="Arial,sans-serif" font-size="30" fill="#333333">${safeLabel}</text></svg>`
  image.src = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

const accessibleStores = computed(() => stores.value.filter((store) => {
  return canAccessStore(store.id)
}))
const isGlobalAdmin = computed(() => admin.value?.role === 'super_admin' || (admin.value?.role === 'manager' && admin.value?.store_id == null))
// Keep navigation honest about API capabilities.  Store-scoped staff can
// inspect the catalogue, but product and banner mutations are global-admin
// operations and would otherwise only fail after a click with a 403.
const visibleNav = computed(() => nav.filter(([key]) => (key !== 'banners' || isGlobalAdmin.value) && (key !== 'assistant' || isGlobalAdmin.value)))
const canEditCatalog = computed(() => isGlobalAdmin.value)
const canManageOrganisation = computed(() => isGlobalAdmin.value)
function canAccessStore(storeId) {
  const role = admin.value?.role
  if (storeId == null) return role === 'super_admin' || (role === 'manager' && admin.value?.store_id == null)
  return role === 'super_admin' || (role === 'manager' && admin.value?.store_id == null) || (admin.value?.store_id != null && Number(admin.value.store_id) === Number(storeId))
}
function selectPage(nextPage) {
  if (nextPage === 'banners' && !isGlobalAdmin.value) {
    showNotice('Banner management requires global administrator access.')
    return
  }
  if (nextPage === 'assistant' && !isGlobalAdmin.value) {
    showNotice('AI assistant settings require global administrator access.')
    return
  }
  page.value = nextPage
  mobileNavOpen.value = false
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

watch(page, (value) => {
  if (!pageStateReady.value) return
  try { sessionStorage.setItem(PAGE_STATE_KEY, value) } catch { /* Session storage may be unavailable. */ }
  const routeHash = `#/${value}`
  if (window.location.hash !== routeHash) {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${routeHash}`)
  }
})

function openOrdersPage(nextPage = 'orders', { payment = 'all', status = 'all' } = {}) {
  orderSearch.value = ''
  orderStatusFilter.value = status
  orderPaymentFilter.value = payment
  orderStoreFilter.value = 'all'
  selectPage(nextPage)
}

function clearAdminSession() {
  token.value = null
  admin.value = null
  localStorage.removeItem('eba_admin_token')
  localStorage.removeItem('eba_admin_user')
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (token.value) headers.set('Authorization', `Bearer ${token.value}`)
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let response
  try {
    response = await fetch(`${api}${path}`, { ...options, headers })
  } catch {
    throw new Error('Unable to reach the service. Check that the API is running.')
  }
  const type = response.headers.get('content-type') || ''
  const data = type.includes('application/json') ? await response.json() : await response.text()
  if (response.status === 401 && token.value) {
    clearAdminSession()
    throw new Error('Your admin session has expired. Please sign in again.')
  }
  if (!response.ok) {
    const detail = typeof data === 'string'
      ? data
      : data?.detail || data?.message || (data?.status ? `${data.status}${data.database ? ` (${data.database})` : ''}` : null)
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return data
}

async function load() {
  if (!token.value) return
  loading.value = true
  loadError.value = ''
  try {
    const results = await Promise.allSettled([apiFetch('/orders'), apiFetch('/admin/skus'), apiFetch('/admin/stores'), loadCustomers(), loadSupportConversations()])
    const [orderResult, skuResult, storeResult, customerResult, supportResult] = results
    if (orderResult.status === 'fulfilled') orders.value = Array.isArray(orderResult.value) ? orderResult.value : []
    if (skuResult.status === 'fulfilled') skus.value = Array.isArray(skuResult.value) ? skuResult.value : []
    if (storeResult.status === 'fulfilled') stores.value = Array.isArray(storeResult.value) ? storeResult.value : []
    if (customerResult.status === 'fulfilled' && Array.isArray(customerResult.value)) customers.value = customerResult.value
    if (supportResult.status === 'fulfilled' && Array.isArray(supportResult.value)) supportConversations.value = supportResult.value
    // Management endpoints intentionally sit alongside the public read APIs.
    // Only global administrators can see the full store directory and staff
    // roster; scoped accounts keep their normal store-scoped read experience.
    if (isGlobalAdmin.value) {
      const managementResults = await Promise.allSettled([apiFetch('/admin/users')])
      const [adminUserResult] = managementResults
      if (adminUserResult.status === 'fulfilled' && Array.isArray(adminUserResult.value)) adminUsers.value = adminUserResult.value
      const managementFailures = managementResults.filter((result) => result.status === 'rejected')
      if (managementFailures.length) {
        const messages = managementFailures.map((result) => result.reason?.message || 'Management data could not be loaded')
        loadError.value = [...new Set(messages)].join(' ')
      }
    } else {
      adminUsers.value = admin.value ? [admin.value] : []
    }
    seedStockDraft()
    const failures = results.filter((result) => result.status === 'rejected')
    if (failures.length) loadError.value = failures.map((result) => result.reason?.message || 'Some data could not be loaded').join(' ')
    lastRefresh.value = new Date()
  } finally {
    loading.value = false
  }
}

async function login() {
  if (!username.value.trim() || !password.value) {
    loginError.value = 'Enter your username and password.'
    return
  }
  loginBusy.value = true
  loginError.value = ''
  try {
    const data = await apiFetch('/admin/auth/login', { method: 'POST', body: JSON.stringify({ account: username.value.trim(), password: password.value }) })
    token.value = data.access_token
    admin.value = data.user
    localStorage.setItem('eba_admin_token', token.value)
    localStorage.setItem('eba_admin_user', JSON.stringify(admin.value))
    password.value = ''
    await load()
    await checkHealth()
    if (isGlobalAdmin.value) await loadAssistantConfig()
  } catch (error) {
    loginError.value = error.message
  } finally {
    loginBusy.value = false
  }
}

async function loadAssistantConfig() {
  if (!isGlobalAdmin.value) return
  assistantError.value = ''
  try {
    assistantConfig.value = { ...assistantConfig.value, ...await apiFetch('/admin/support/assistant') }
  } catch (error) {
    assistantError.value = error.message
  }
}

async function saveAssistantConfig() {
  assistantBusy.value = true
  assistantError.value = ''
  assistantNotice.value = ''
  try {
    const payload = { ...assistantConfig.value, api_key: assistantApiKey.value || null, clear_api_key: assistantClearKey.value }
    assistantConfig.value = { ...assistantConfig.value, ...await apiFetch('/admin/support/assistant', { method: 'PUT', body: JSON.stringify(payload) }) }
    assistantApiKey.value = ''
    assistantClearKey.value = false
    assistantNotice.value = 'Assistant settings saved.'
  } catch (error) {
    assistantError.value = error.message
  } finally {
    assistantBusy.value = false
  }
}

async function testAssistantConnection() {
  assistantTesting.value = true
  assistantError.value = ''
  assistantNotice.value = ''
  try {
    const result = await apiFetch('/admin/support/assistant/test', {
      method: 'POST',
      body: JSON.stringify({ base_url: assistantConfig.value.base_url, model: assistantConfig.value.model, api_key: assistantApiKey.value || null }),
    })
    assistantNotice.value = `Connection successful (${result.model}).`
  } catch (error) {
    assistantError.value = error.message
  } finally {
    assistantTesting.value = false
  }
}

function logout() {
  clearAdminSession()
  page.value = 'dashboard'
  mobileNavOpen.value = false
}

// BannerManager uses its own fetch calls, so forward an expired-session
// response into the same sign-out flow as the shared API client.
function handleBannerUnauthorized() {
  clearAdminSession()
  page.value = 'dashboard'
  mobileNavOpen.value = false
  loginError.value = 'Your admin session has expired. Please sign in again.'
}

function showNotice(message) {
  notice.value = message
  window.clearTimeout(showNotice.timer)
  showNotice.timer = window.setTimeout(() => { notice.value = '' }, 3200)
}

const paidOrders = computed(() => orders.value.filter((order) => ['paid', 'deposit_paid', 'paid_pending_review'].includes(order.payment_status)))
const grossPayments = computed(() => paidOrders.value.reduce((sum, order) => sum + Number(order.paid_amount ?? order.deposit_amount ?? 0), 0))
const pendingFulfillment = computed(() => orders.value.filter((order) => ['awaiting_store_process', 'processing', 'stock_in_transit', 'shipped'].includes(order.order_status)))
const scopedStores = computed(() => stores.value.filter((store) => canAccessStore(store.id)))
const lowStockRows = computed(() => skus.value.flatMap((sku) => scopedStores.value.map((store) => ({ sku, store, quantity: Number(sku.store_stock?.[store.id] || 0) })).filter((row) => row.quantity <= 1)))
const totalAvailable = computed(() => skus.value.reduce((sum, sku) => sum + scopedStores.value.reduce((inner, store) => inner + Number(sku.store_stock?.[store.id] || 0), 0), 0))
const storeStats = computed(() => scopedStores.value.map((store) => {
  const rows = skus.value.map((sku) => ({ sku, quantity: Number(sku.store_stock?.[store.id] || 0) }))
  return { store, units: rows.reduce((sum, row) => sum + row.quantity, 0), activeSkus: rows.filter((row) => row.quantity > 0).length, lowStock: rows.filter((row) => row.quantity <= 1).length }
}))

const orderSearch = ref('')
const orderStatusFilter = ref('all')
const orderPaymentFilter = ref('all')
const orderStoreFilter = ref('all')
const filteredOrders = computed(() => {
  const query = orderSearch.value.trim().toLowerCase()
  return orders.value.filter((order) => {
    const matchesQuery = !query || [order.id, order.customer_name, order.customer_phone, order.product_name].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesStatus = orderStatusFilter.value === 'all' || order.order_status === orderStatusFilter.value
    const matchesPayment = orderPaymentFilter.value === 'all' || order.payment_status === orderPaymentFilter.value
    const matchesStore = orderStoreFilter.value === 'all' || String(order.store_id) === String(orderStoreFilter.value)
    return matchesQuery && matchesStatus && matchesPayment && matchesStore
  })
})
const orderStatuses = computed(() => [...new Set(orders.value.map((order) => order.order_status).filter(Boolean))])
const fulfillmentOrders = computed(() => filteredOrders.value.filter((order) => ['awaiting_store_process', 'processing', 'stock_in_transit', 'shipped'].includes(order.order_status)))

const orderAction = ref(null)
const orderDialogRef = ref(null)
let orderActionPreviousFocus = null
const actionInput = ref('')
const allowInTransit = ref(false)
const actionBusy = ref(false)
const actionError = ref('')
const settlementDraft = ref({ amount: '', payment_method: 'Cash at store', reference: '', note: '' })
const orderHasPayment = (order) => ['paid', 'deposit_paid', 'partial', 'paid_pending_review'].includes(String(order?.payment_status || '').toLowerCase()) && Number(order?.paid_amount ?? order?.deposit_amount ?? 0) > 0
const dispatchTargetStore = computed(() => {
  if (!orderAction.value || orderAction.value.key !== 'dispatch' || !actionInput.value) return null
  return accessibleStores.value.find((store) => Number(store.id) === Number(actionInput.value)) || null
})
const dispatchTargetStock = computed(() => {
  const store = dispatchTargetStore.value
  const order = orderAction.value?.order
  if (!store || !order) return 0
  const sku = skus.value.find((item) => Number(item.id) === Number(order.sku_id))
  return Number(sku?.store_stock?.[store.id] || 0)
})
const reviewTargetStore = computed(() => {
  if (!orderAction.value || orderAction.value.key !== 'fulfill-payment-review' || !actionInput.value) return null
  return accessibleStores.value.find((store) => Number(store.id) === Number(actionInput.value)) || null
})
const reviewTargetStock = computed(() => {
  const store = reviewTargetStore.value
  const order = orderAction.value?.order
  if (!store || !order) return 0
  const sku = skus.value.find((item) => Number(item.id) === Number(order.sku_id))
  return Number(sku?.store_stock?.[store.id] || 0)
})
function actionsFor(order) {
  if (!canAccessStore(order.store_id)) return []
  const actions = []
  const balanceDue = Number(order.balance_due ?? order.remaining_amount ?? 0)
  const fullyPaid = balanceDue <= 0 || Number(order.paid_amount || 0) >= orderTotal(order)
  const paymentReview = order.payment_status === 'paid_pending_review' || order.order_status === 'payment_review'
  // Review holds have exactly one provider payment and can be refunded even
  // when that payment covered the full order.  For ordinary deposit orders,
  // keep the existing guard that hides provider refunds after a manual
  // balance settlement; the API requires a separate manual refund review for
  // those multi-payment orders.
  const providerRefundable = paymentReview
    ? order.payment_status === 'paid_pending_review' && Number(order.paid_amount || 0) > 0
    : ['paid', 'deposit_paid'].includes(order.payment_status) && Number(order.paid_amount || 0) > 0 && Number(order.paid_amount || 0) <= Number(order.deposit_amount || 0)
  if (paymentReview) {
    // A late provider success has been recorded but no stock is reserved.
    // Require an explicit destination choice before reclaiming a new unit;
    // refund remains available when no store can fulfil the order.
    if (orderHasPayment(order) && isGlobalAdmin.value) actions.push({ key: 'fulfill-payment-review', label: 'Reserve stock', icon: PackageSearch })
    if (providerRefundable && isGlobalAdmin.value) actions.push({ key: 'refund', label: 'Request refund', icon: RotateCcw, danger: true })
    return actions
  }
  if (order.order_status === 'stock_in_transit') {
    actions.push({ key: 'receive-transfer', label: 'Receive transfer', icon: PackageSearch })
    return actions
  }
  // The API deliberately limits provider refunds to global administrators;
  // hiding the action for scoped store staff avoids a guaranteed 403 and
  // keeps the operations UI aligned with the permission model.
  if (providerRefundable && isGlobalAdmin.value) actions.push({ key: 'refund', label: 'Request refund', icon: RotateCcw, danger: true })
  if (order.payment_plan === 'deposit' && order.payment_status !== 'pending' && !fullyPaid && !['cancelled', 'released', 'completed'].includes(order.order_status)) actions.push({ key: 'settle', label: 'Collect balance', icon: WalletCards })
  if (order.payment_status === 'pending' && order.stock_reserved && !['cancelled', 'released', 'completed'].includes(order.order_status)) actions.push({ key: 'release', label: order.fulfillment_type === 'pickup' ? 'Release reservation' : 'Release order', icon: RotateCcw, danger: true })
  if (['awaiting_store_process', 'processing'].includes(order.order_status) && order.fulfillment_type === 'shipping' && fullyPaid) actions.push({ key: 'tracking', label: 'Add tracking', icon: Truck })
  if (((order.fulfillment_type === 'pickup' && ['awaiting_store_process', 'processing'].includes(order.order_status)) || (order.fulfillment_type === 'shipping' && order.order_status === 'shipped')) && (order.payment_plan !== 'deposit' || fullyPaid)) actions.push({ key: 'complete', label: order.fulfillment_type === 'pickup' ? 'Complete pickup' : 'Mark delivered', icon: CheckCircle2 })
  const paymentNeedsReview = ['pending', 'initiating', 'expired', 'amount_missing', 'amount_mismatch', 'currency_mismatch'].includes(order.payment_status)
  if (paymentNeedsReview && ['awaiting_payment', 'payment_review'].includes(order.order_status)) {
    actions.push({ key: 'payment-status', label: 'Check payment', icon: Clock3 })
    if (isGlobalAdmin.value) actions.push({ key: 'reconcile-payment', label: 'Reconcile payment', icon: RefreshCw })
  }
  // Dispatch moves reserved stock between our Ghana stores.  The API rejects
  // unpaid reservations, so hide the action until at least a confirmed
  // deposit/full payment is present instead of presenting a guaranteed 409.
  if (isGlobalAdmin.value && orderHasPayment(order) && order.stock_reserved && !['completed', 'cancelled', 'released', 'shipped'].includes(order.order_status)) actions.push({ key: 'dispatch', label: 'Dispatch store', icon: Store })
  return actions
}
function openOrderAction(order, key) {
  if (!actionsFor(order).some((action) => action.key === key)) {
    showNotice('This action is outside your store or role permissions.')
    return
  }
  orderActionPreviousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  orderAction.value = { order, key }
  allowInTransit.value = false
  actionInput.value = key === 'tracking'
    ? order.tracking_number || ''
    : key === 'release'
      ? 'Stock reservation released by store team'
      : key === 'dispatch'
        ? String(accessibleStores.value.find((store) => Number(store.id) !== Number(order.store_id))?.id || '')
        : key === 'receive-transfer'
          ? 'Stock received and checked by destination store'
        : key === 'fulfill-payment-review'
          ? String(accessibleStores.value.find((store) => Number(store.id) === Number(order.store_id) && store.active)?.id || accessibleStores.value.find((store) => store.active)?.id || '')
        : ''
  if (key === 'settle') {
    settlementDraft.value = {
      amount: Number(order.balance_due ?? order.remaining_amount ?? 0).toFixed(2),
      payment_method: 'Cash at store',
      reference: '',
      note: '',
    }
  }
  actionError.value = ''
  nextTick(() => orderDialogRef.value?.focus())
}
function closeOrderAction(force = false) {
  if (actionBusy.value && !force) return
  orderAction.value = null
  actionInput.value = ''
  allowInTransit.value = false
  settlementDraft.value = { amount: '', payment_method: 'Cash at store', reference: '', note: '' }
  actionError.value = ''
  const returnFocus = orderActionPreviousFocus
  orderActionPreviousFocus = null
  nextTick(() => returnFocus?.focus())
}
function trapOrderDialogFocus(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeOrderAction()
    return
  }
  if (event.key !== 'Tab' || !orderDialogRef.value) return
  const focusable = [...orderDialogRef.value.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
  if (!focusable.length) {
    event.preventDefault()
    orderDialogRef.value.focus()
    return
  }
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
async function performOrderAction() {
  if (!orderAction.value) return
  const { order, key } = orderAction.value
  if (key === 'refund' && !window.confirm(`Request a refund for ${order.id}?`)) return
  if (key === 'tracking' && actionInput.value.trim().length < 3) { actionError.value = 'Enter a tracking number (at least 3 characters).'; return }
  if (key === 'release' && actionInput.value.trim().length < 3) { actionError.value = 'Enter a short release reason.'; return }
  if (key === 'settle') {
    const amount = Number(settlementDraft.value.amount)
    if (!Number.isFinite(amount) || amount <= 0) { actionError.value = 'Enter the balance collected.'; return }
    if (settlementDraft.value.payment_method.trim().length < 2) { actionError.value = 'Enter the payment method.'; return }
  }
  actionBusy.value = true
  actionError.value = ''
  try {
    let data
    if (key === 'release') data = await apiFetch(`/orders/${order.id}/release`, { method: 'POST', body: JSON.stringify({ reason: actionInput.value.trim() }) })
    if (key === 'settle') data = await apiFetch(`/orders/${order.id}/settle`, { method: 'POST', body: JSON.stringify({ amount: Number(settlementDraft.value.amount).toFixed(2), payment_method: settlementDraft.value.payment_method.trim(), reference: settlementDraft.value.reference.trim() || null, note: settlementDraft.value.note.trim() || null }) })
    if (key === 'tracking') data = await apiFetch(`/orders/${order.id}/tracking`, { method: 'POST', body: JSON.stringify({ tracking_number: actionInput.value.trim() }) })
    if (key === 'receive-transfer') data = await apiFetch(`/orders/${order.id}/receive-transfer`, { method: 'POST', body: JSON.stringify({ note: actionInput.value.trim() || null }) })
    if (key === 'complete') {
      const body = order.fulfillment_type === 'pickup'
        ? { pickup_code: actionInput.value.trim() }
        : { note: actionInput.value.trim() || null }
      data = await apiFetch(`/orders/${order.id}/complete`, { method: 'POST', body: JSON.stringify(body) })
    }
    if (key === 'refund') data = await apiFetch(`/orders/${order.id}/refund`, { method: 'POST' })
    if (key === 'payment-status') data = await apiFetch(`/orders/${order.id}/payment-status`)
    if (key === 'reconcile-payment') data = await apiFetch(`/orders/${order.id}/payment-reconcile`, { method: 'POST' })
    if (key === 'fulfill-payment-review') data = await apiFetch(`/orders/${order.id}/payment-review/fulfill`, { method: 'POST', body: JSON.stringify({ store_id: Number(actionInput.value), note: settlementDraft.value.note.trim() || null }) })
    if (key === 'dispatch') data = await apiFetch(`/orders/${order.id}/dispatch`, { method: 'POST', body: JSON.stringify({ store_id: Number(actionInput.value), allow_in_transit: Boolean(allowInTransit.value) }) })
    if (key === 'payment-status') showNotice(`Payment status checked: ${data.local_status || data.remote?.status || 'received'}.`)
    else if (key === 'reconcile-payment') {
      const index = orders.value.findIndex((item) => item.id === order.id)
      if (index >= 0 && data.order) orders.value[index] = data.order
      showNotice(data.status === 'reconciled' ? `${order.id} payment reconciled.` : `${order.id}: ${data.reason || data.status || 'manual review required'}.`)
    }
    else if (key === 'fulfill-payment-review') {
      const index = orders.value.findIndex((item) => item.id === order.id)
      if (index >= 0 && data.order) orders.value[index] = data.order
      showNotice(data.status === 'fulfilled' ? `${order.id} payment review resolved and stock reserved.` : `${order.id}: ${data.status || 'already resolved'}.`)
    }
    else if (key === 'refund') {
      const index = orders.value.findIndex((item) => item.id === order.id)
      if (index >= 0) orders.value[index] = { ...orders.value[index], payment_status: 'refund_pending' }
      showNotice(`Refund request submitted for ${order.id}.`)
    } else {
      const index = orders.value.findIndex((item) => item.id === order.id)
      if (index >= 0) orders.value[index] = data
      showNotice(`${order.id} updated.`)
    }
    closeOrderAction(true)
  } catch (error) {
    actionError.value = error.message
  } finally {
    actionBusy.value = false
  }
}

const productSearch = ref('')
const productCategoryFilter = ref('all')
const productCategories = computed(() => [...new Set(skus.value.map((sku) => sku.category).filter(Boolean))])
const filteredSkus = computed(() => {
  const query = productSearch.value.trim().toLowerCase()
  return skus.value.filter((sku) => {
    const matchesQuery = !query || [sku.product_name, sku.brand, sku.variant, sku.category].some((value) => String(value || '').toLowerCase().includes(query))
    return matchesQuery && (productCategoryFilter.value === 'all' || sku.category === productCategoryFilter.value)
  })
})
const productModal = ref(null)
const productDraft = ref(null)
const productBusy = ref(false)
const productError = ref('')
const isCreatingProduct = computed(() => productModal.value && productModal.value.id == null)
function blankProductDraft() {
  return {
    product_name: '',
    brand: '',
    category: 'phones',
    variant: '',
    image: '',
    price: '',
    deposit_rate: 30,
    active: true,
    initial_stock: Object.fromEntries(stores.value.filter((store) => store.active).map((store) => [store.id, 0])),
  }
}
function openProductCreator() {
  if (!canEditCatalog.value) { showNotice('Product creation requires global administrator access.'); return }
  productModal.value = { id: null }
  productDraft.value = blankProductDraft()
  productError.value = ''
}
function openProductEditor(sku) {
  if (!canEditCatalog.value) { showNotice('Product editing requires global administrator access.'); return }
  productModal.value = sku
  productDraft.value = {
    product_name: sku.product_name || '',
    brand: sku.brand || '',
    category: sku.category || '',
    variant: sku.variant || '',
    image: sku.image || '',
    price: Number(sku.price),
    deposit_rate: Number(sku.deposit_rate),
    active: Boolean(sku.active),
    initial_stock: {},
  }
  productError.value = ''
}
function closeProductEditor(force = false) {
  if (productBusy.value && !force) return
  productModal.value = null
  productDraft.value = null
  productError.value = ''
}
async function saveProduct() {
  if (!productModal.value || !productDraft.value) return
  if (!productDraft.value.product_name.trim() || !productDraft.value.brand.trim() || !productDraft.value.category.trim() || !productDraft.value.variant.trim()) { productError.value = 'Product name, brand, category and variant are required.'; return }
  if (!(Number(productDraft.value.price) > 0) || Number(productDraft.value.deposit_rate) <= 0 || Number(productDraft.value.deposit_rate) > 100) { productError.value = 'Enter a valid price and a deposit rate greater than 0 up to 100.'; return }
  productBusy.value = true
  productError.value = ''
  try {
    const payload = {
      product_name: productDraft.value.product_name.trim(),
      brand: productDraft.value.brand.trim(),
      category: productDraft.value.category.trim().toLowerCase().replaceAll(' ', '-'),
      variant: productDraft.value.variant.trim(),
      image: productDraft.value.image.trim() || (isCreatingProduct.value ? null : productModal.value.image || ''),
      price: Number(productDraft.value.price),
      deposit_rate: Number(productDraft.value.deposit_rate),
      active: Boolean(productDraft.value.active),
    }
    if (isCreatingProduct.value) {
      payload.initial_stock = Object.fromEntries(Object.entries(productDraft.value.initial_stock || {}).map(([storeId, quantity]) => [storeId, Math.max(0, Number(quantity) || 0)]))
      const created = await apiFetch('/admin/skus', { method: 'POST', body: JSON.stringify(payload) })
      skus.value = [created, ...skus.value]
      seedStockDraft()
      showNotice(`${created.product_name} created.`)
    } else {
      const updated = await apiFetch(`/admin/skus/${productModal.value.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
      const index = skus.value.findIndex((sku) => sku.id === updated.id)
      if (index >= 0) skus.value[index] = updated
      showNotice(`${updated.product_name} saved.`)
    }
    closeProductEditor(true)
  } catch (error) {
    productError.value = error.message
  } finally {
    productBusy.value = false
  }
}

// Store directory management -------------------------------------------------
const storeSearch = ref('')
const storeStatusFilter = ref('all')
const storeModal = ref(null)
const storeDraft = ref(null)
const storeBusy = ref(false)
const storeError = ref('')
const isCreatingStore = computed(() => storeModal.value && storeModal.value.id == null)
const filteredStores = computed(() => {
  const query = storeSearch.value.trim().toLowerCase()
  return stores.value.filter((store) => {
    const matchesQuery = !query || [store.name, store.address, store.phone, store.open_hours].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesStatus = storeStatusFilter.value === 'all' || (storeStatusFilter.value === 'active' ? store.active : !store.active)
    return matchesQuery && matchesStatus
  })
})
function blankStoreDraft() {
  return { name: '', address: '', phone: '', open_hours: 'Mon-Sat 09:00-18:00', active: true }
}
function openStoreEditor(store = null) {
  if (!canManageOrganisation.value) { showNotice('Store management requires global administrator access.'); return }
  storeModal.value = store || { id: null }
  storeDraft.value = store ? {
    name: store.name || '', address: store.address || '', phone: store.phone || '', open_hours: store.open_hours || '', active: Boolean(store.active),
  } : blankStoreDraft()
  storeError.value = ''
}
function closeStoreEditor(force = false) {
  if (storeBusy.value && !force) return
  storeModal.value = null
  storeDraft.value = null
  storeError.value = ''
}
async function saveStore() {
  if (!storeModal.value || !storeDraft.value) return
  const draft = storeDraft.value
  if (!draft.name.trim() || !draft.address.trim() || !draft.phone.trim() || !draft.open_hours.trim()) { storeError.value = 'Name, address, phone and opening hours are required.'; return }
  storeBusy.value = true
  storeError.value = ''
  try {
    const payload = { name: draft.name.trim(), address: draft.address.trim(), phone: draft.phone.trim(), open_hours: draft.open_hours.trim(), active: Boolean(draft.active) }
    const result = await apiFetch(isCreatingStore.value ? '/admin/stores' : `/admin/stores/${storeModal.value.id}`, { method: isCreatingStore.value ? 'POST' : 'PATCH', body: JSON.stringify(payload) })
    const index = stores.value.findIndex((store) => store.id === result.id)
    if (index >= 0) stores.value[index] = result
    else stores.value = [result, ...stores.value]
    showNotice(`${result.name} ${isCreatingStore.value ? 'created' : 'saved'}.`)
    closeStoreEditor(true)
  } catch (error) {
    storeError.value = error.message
  } finally {
    storeBusy.value = false
  }
}
async function toggleStore(store) {
  if (!canManageOrganisation.value) { showNotice('Store activation requires global administrator access.'); return }
  const nextActive = !store.active
  if (!window.confirm(`${nextActive ? 'Activate' : 'Pause'} ${store.name}?`)) return
  try {
    const updated = await apiFetch(`/admin/stores/${store.id}`, { method: 'PATCH', body: JSON.stringify({ active: nextActive }) })
    const index = stores.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) stores.value[index] = updated
    showNotice(`${updated.name} is now ${updated.active ? 'active' : 'paused'}.`)
  } catch (error) {
    showNotice(error.message)
  }
}

// Staff account management ---------------------------------------------------
const staffSearch = ref('')
const staffRoleFilter = ref('all')
const staffStatusFilter = ref('all')
const staffModal = ref(null)
const staffDraft = ref(null)
const staffBusy = ref(false)
const staffError = ref('')
const isCreatingStaff = computed(() => staffModal.value && staffModal.value.id == null)
const filteredAdminUsers = computed(() => {
  const query = staffSearch.value.trim().toLowerCase()
  return adminUsers.value.filter((user) => {
    const matchesQuery = !query || [user.name, user.username, user.role, user.store_name, storeName(user.store_id)].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesRole = staffRoleFilter.value === 'all' || user.role === staffRoleFilter.value
    const matchesStatus = staffStatusFilter.value === 'all' || (staffStatusFilter.value === 'active' ? user.active : !user.active)
    return matchesQuery && matchesRole && matchesStatus
  })
})
function blankStaffDraft() {
  return { name: '', username: '', password: '', role: 'operator', store_id: '', active: true }
}
function openStaffEditor(user = null) {
  if (!canManageOrganisation.value) { showNotice('Staff account management requires global administrator access.'); return }
  if (user?.role === 'super_admin' && admin.value?.role !== 'super_admin') { showNotice('Only a super administrator can edit this account.'); return }
  staffModal.value = user || { id: null }
  staffDraft.value = user ? {
    name: user.name || '', username: user.username || '', password: '', role: user.role || 'operator', store_id: user.store_id == null ? '' : String(user.store_id), active: Boolean(user.active),
  } : blankStaffDraft()
  staffError.value = ''
}
function closeStaffEditor(force = false) {
  if (staffBusy.value && !force) return
  staffModal.value = null
  staffDraft.value = null
  staffError.value = ''
}
function onStaffRoleChange() {
  if (staffDraft.value?.role === 'super_admin') staffDraft.value.store_id = ''
}
async function saveStaff() {
  if (!staffModal.value || !staffDraft.value) return
  const draft = staffDraft.value
  if (!draft.name.trim() || !draft.username.trim()) { staffError.value = 'Name and username are required.'; return }
  if (isCreatingStaff.value && draft.password.length < 8) { staffError.value = 'New staff passwords must be at least 8 characters.'; return }
  if (draft.role === 'operator' && !draft.store_id) { staffError.value = 'Select a store for operator accounts.'; return }
  staffBusy.value = true
  staffError.value = ''
  try {
    const payload = {
      name: draft.name.trim(), username: draft.username.trim(), role: draft.role, store_id: draft.role === 'super_admin' || !draft.store_id ? null : Number(draft.store_id), active: Boolean(draft.active),
    }
    if (draft.password.trim()) payload.password = draft.password
    const result = await apiFetch(isCreatingStaff.value ? '/admin/users' : `/admin/users/${staffModal.value.id}`, { method: isCreatingStaff.value ? 'POST' : 'PATCH', body: JSON.stringify(payload) })
    const index = adminUsers.value.findIndex((user) => user.id === result.id)
    if (index >= 0) adminUsers.value[index] = result
    else adminUsers.value = [result, ...adminUsers.value]
    showNotice(`${result.name} ${isCreatingStaff.value ? 'created' : 'saved'}.`)
    closeStaffEditor(true)
  } catch (error) {
    staffError.value = error.message
  } finally {
    staffBusy.value = false
  }
}
async function toggleStaff(user) {
  if (!canManageOrganisation.value) { showNotice('Staff activation requires global administrator access.'); return }
  if (user.role === 'super_admin' && admin.value?.role !== 'super_admin') { showNotice('Only a super administrator can change this account.'); return }
  if (Number(user.id) === Number(admin.value?.id) && user.active) { showNotice('You cannot deactivate your own account.'); return }
  const nextActive = !user.active
  if (!window.confirm(`${nextActive ? 'Activate' : 'Pause'} ${user.name}'s account?`)) return
  try {
    const updated = await apiFetch(`/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ active: nextActive }) })
    const index = adminUsers.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) adminUsers.value[index] = updated
    showNotice(`${updated.name} is now ${updated.active ? 'active' : 'paused'}.`)
  } catch (error) {
    showNotice(error.message)
  }
}
function storeName(storeId) {
  return stores.value.find((store) => Number(store.id) === Number(storeId))?.name || (storeId ? `Store #${storeId}` : 'All stores')
}
function canEditStaffUser(user) {
  return canManageOrganisation.value && (admin.value?.role === 'super_admin' || user.role !== 'super_admin')
}

const stockDraft = ref({})
const stockSaving = ref({})
const inventorySearch = ref('')
const inventoryCategoryFilter = ref('all')
const inventorySkus = computed(() => {
  const query = inventorySearch.value.trim().toLowerCase()
  return skus.value.filter((sku) => {
    const matchesQuery = !query || [sku.product_name, sku.brand, sku.variant, sku.category].some((value) => String(value || '').toLowerCase().includes(query))
    return matchesQuery && (inventoryCategoryFilter.value === 'all' || sku.category === inventoryCategoryFilter.value)
  })
})
function stockKey(skuId, storeId) { return `${skuId}:${storeId}` }
function stockValue(sku, storeId) {
  const key = stockKey(sku.id, storeId)
  return key in stockDraft.value ? stockDraft.value[key] : Number(sku.store_stock?.[storeId] || 0)
}
function seedStockDraft() {
  const next = {}
  for (const sku of skus.value) for (const store of stores.value) next[stockKey(sku.id, store.id)] = Number(sku.store_stock?.[store.id] || 0)
  stockDraft.value = next
}
async function saveStock(sku, store) {
  if (!canAccessStore(store.id)) { showNotice(`You can only edit stock for ${store.name} within your scope.`); return }
  const key = stockKey(sku.id, store.id)
  const quantity = Number(stockDraft.value[key])
  if (!Number.isInteger(quantity) || quantity < 0) { showNotice('Stock must be a whole number of 0 or more.'); return }
  stockSaving.value[key] = true
  try {
    const updated = await apiFetch(`/admin/inventory?sku_id=${encodeURIComponent(sku.id)}`, { method: 'PATCH', body: JSON.stringify({ store_id: store.id, available: quantity }) })
    const index = skus.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) skus.value[index] = updated
    showNotice(`${sku.product_name} stock updated for ${store.name}.`)
  } catch (error) {
    showNotice(error.message)
  } finally {
    stockSaving.value[key] = false
  }
}

const customerSearch = ref('')
const customerStatusFilter = ref('all')
const customerEditor = ref(null)
const customerDraft = ref(null)
const customerBusy = ref(false)
const customerError = ref('')
async function loadCustomers() {
  const data = await apiFetch('/admin/customers')
  customers.value = Array.isArray(data) ? data : []
  return customers.value
}
const filteredCustomers = computed(() => {
  const query = customerSearch.value.trim().toLowerCase()
  return customers.value.filter((customer) => {
    const matchesQuery = !query || [customer.name, customer.phone, customer.email, customer.default_address, customer.notes].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesStatus = customerStatusFilter.value === 'all' || (customerStatusFilter.value === 'active' ? customer.active !== false : customer.active === false)
    return matchesQuery && matchesStatus
  })
})
const customerOrderRows = computed(() => {
  if (!customerEditor.value) return []
  const phone = String(customerEditor.value.phone || '').replace(/\D/g, '').slice(-9)
  return orders.value.filter((order) => {
    const orderPhone = String(order.customer_phone || '').replace(/\D/g, '').slice(-9)
    return (customerEditor.value.id != null && Number(order.user_id) === Number(customerEditor.value.id)) || (phone && orderPhone === phone)
  }).sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
})
const canEditCustomers = computed(() => isGlobalAdmin.value)
function openCustomerEditor(customer) {
  customerEditor.value = customer
  customerDraft.value = {
    name: customer.name || '',
    email: customer.email || '',
    default_address: customer.default_address || '',
    notes: customer.notes || '',
    active: customer.active !== false,
  }
  customerError.value = ''
}
function closeCustomerEditor(force = false) {
  if (customerBusy.value && !force) return
  customerEditor.value = null
  customerDraft.value = null
  customerError.value = ''
}
async function saveCustomer() {
  if (!customerEditor.value || !customerDraft.value) return
  if (!canEditCustomers.value) { customerError.value = 'Customer editing requires global administrator access.'; return }
  if (!customerDraft.value.name.trim()) { customerError.value = 'Customer name is required.'; return }
  customerBusy.value = true
  customerError.value = ''
  try {
    const payload = {
      name: customerDraft.value.name.trim(),
      email: customerDraft.value.email.trim() || null,
      default_address: customerDraft.value.default_address.trim() || null,
      notes: customerDraft.value.notes.trim() || null,
      active: Boolean(customerDraft.value.active),
    }
    const updated = await apiFetch(`/admin/customers/${customerEditor.value.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
    const index = customers.value.findIndex((item) => Number(item.id) === Number(updated.id))
    if (index >= 0) customers.value[index] = updated
    customerEditor.value = updated
    showNotice(`${updated.name} saved.`)
    closeCustomerEditor(true)
  } catch (error) {
    customerError.value = error.message
  } finally {
    customerBusy.value = false
  }
}
function csvCell(value) { return `"${String(value ?? '').replaceAll('"', '""')}"` }
function downloadCsv(filename, lines) {
  const blob = new Blob([`\ufeff${lines.join('\n')}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  showNotice(`${filename} downloaded.`)
}
function exportCustomers() {
  downloadCsv('ebaphone-customers.csv', ['Name,Phone,Email,Address,Orders,Order value,Paid value,Last order,Status', ...filteredCustomers.value.map((customer) => [customer.name, customer.phone, customer.email || '', customer.default_address || '', customer.order_count || 0, Number(customer.order_value || 0).toFixed(2), Number(customer.paid_value || 0).toFixed(2), customer.last_order_at || '', customer.active === false ? 'Paused' : 'Active'].map(csvCell).join(','))])
}

const supportSearch = ref('')
const supportStatusFilter = ref('all')
const supportSelected = ref(null)
const supportReply = ref('')
const supportBusy = ref(false)
const supportError = ref('')
async function loadSupportConversations() {
  const data = await apiFetch('/admin/support/conversations')
  supportConversations.value = Array.isArray(data) ? data : []
  return supportConversations.value
}
const filteredSupportConversations = computed(() => {
  const query = supportSearch.value.trim().toLowerCase()
  return supportConversations.value.filter((conversation) => {
    const matchesQuery = !query || [conversation.id, conversation.customer_name, conversation.customer_phone, conversation.subject, conversation.last_message].some((value) => String(value || '').toLowerCase().includes(query))
    const matchesStatus = supportStatusFilter.value === 'all' || conversation.status === supportStatusFilter.value
    return matchesQuery && matchesStatus
  })
})
function upsertSupportConversation(conversation) {
  const index = supportConversations.value.findIndex((item) => item.id === conversation.id)
  if (index >= 0) supportConversations.value[index] = conversation
  else supportConversations.value.unshift(conversation)
  supportConversations.value = [...supportConversations.value].sort((a, b) => new Date(b.last_message_at) - new Date(a.last_message_at))
}
async function openSupportConversation(conversation) {
  supportBusy.value = true
  supportError.value = ''
  try {
    supportSelected.value = await apiFetch(`/admin/support/conversations/${encodeURIComponent(conversation.id)}`)
    supportReply.value = ''
  } catch (error) {
    supportError.value = error.message
  } finally {
    supportBusy.value = false
  }
}
function closeSupportConversation() {
  supportSelected.value = null
  supportReply.value = ''
  supportError.value = ''
}
async function sendSupportReply() {
  if (!supportSelected.value) return
  const message = supportReply.value.trim()
  if (!message) { supportError.value = 'Enter a reply before sending.'; return }
  supportBusy.value = true
  supportError.value = ''
  try {
    const updated = await apiFetch(`/admin/support/conversations/${encodeURIComponent(supportSelected.value.id)}/messages`, { method: 'POST', body: JSON.stringify({ message }) })
    supportSelected.value = updated
    upsertSupportConversation(updated)
    supportReply.value = ''
    showNotice('Reply sent.')
  } catch (error) {
    supportError.value = error.message
  } finally {
    supportBusy.value = false
  }
}
async function updateSupportStatus(status) {
  if (!supportSelected.value) return
  supportBusy.value = true
  supportError.value = ''
  try {
    const updated = await apiFetch(`/admin/support/conversations/${encodeURIComponent(supportSelected.value.id)}`, { method: 'PATCH', body: JSON.stringify({ status }) })
    supportSelected.value = updated
    upsertSupportConversation(updated)
    showNotice(status === 'resolved' ? 'Conversation closed.' : 'Conversation reopened.')
  } catch (error) {
    supportError.value = error.message
  } finally {
    supportBusy.value = false
  }
}
function supportStatusLabel(status) {
  return { open: 'Open', waiting_customer: 'Waiting for customer', resolved: 'Resolved' }[status] || statusLabel(status)
}
function supportSenderLabel(senderType) {
  return senderType === 'admin' ? 'Staff' : senderType === 'assistant' ? 'Assistant' : 'Customer'
}
function ghanaPhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '')
  const national = digits.startsWith('233') ? digits.slice(3) : digits.replace(/^0/, '')
  return `233${national.slice(-9)}`
}
function whatsappUrl(order) {
  const text = encodeURIComponent(`Hello ${order.customer_name || ''}, this is EBAphone regarding order ${order.id}.`)
  return `https://wa.me/${ghanaPhone(order.customer_phone)}?text=${text}`
}
async function copyText(value) {
  try { await navigator.clipboard.writeText(value); showNotice('Copied to clipboard.') } catch { showNotice('Copy is not available in this browser.') }
}

const reportStatus = ref('all')
const reportStore = ref('all')
const reportFrom = ref('')
const reportTo = ref('')
const reportRows = computed(() => orders.value.filter((order) => {
  const date = order.created_at ? new Date(order.created_at) : null
  const afterFrom = !reportFrom.value || (date && date >= new Date(`${reportFrom.value}T00:00:00`))
  const beforeTo = !reportTo.value || (date && date <= new Date(`${reportTo.value}T23:59:59`))
  return (reportStatus.value === 'all' || order.order_status === reportStatus.value) && (reportStore.value === 'all' || String(order.store_id) === String(reportStore.value)) && afterFrom && beforeTo
}))
const reportRevenue = computed(() => reportRows.value.filter((order) => ['paid', 'deposit_paid', 'paid_pending_review'].includes(order.payment_status)).reduce((sum, order) => sum + Number(order.paid_amount ?? order.deposit_amount ?? 0), 0))
const reportAverage = computed(() => reportRows.value.length ? reportRows.value.reduce((sum, order) => sum + orderTotal(order), 0) / reportRows.value.length : 0)
const reportFulfillmentRate = computed(() => reportRows.value.length
  ? Math.round(reportRows.value.filter((order) => order.order_status === 'completed').length / reportRows.value.length * 100)
  : 0)
function exportOrders() {
  downloadCsv('ebaphone-orders.csv', ['Order,Customer,Phone,Product,Quantity,Store,Payment,Status,Amount,Created', ...reportRows.value.map((order) => [order.id, order.customer_name, order.customer_phone, order.product_name, order.quantity || 1, order.store_name || order.store_id || '', order.payment_status, order.order_status, orderTotal(order).toFixed(2), order.created_at].map(csvCell).join(','))])
}

async function checkHealth() {
  health.value = { loading: true }
  try { health.value = { ...(await apiFetch('/health/ready')), checkedAt: new Date() } } catch (error) { health.value = { error: error.message, checkedAt: new Date() } }
}

async function restoreAdminSession() {
  if (!token.value) {
    sessionChecking.value = false
    return false
  }
  try {
    const verified = await apiFetch('/admin/auth/me')
    admin.value = verified
    localStorage.setItem('eba_admin_user', JSON.stringify(verified))
    return true
  } catch (error) {
    // apiFetch clears a rejected/expired token.  Keep the login screen as the
    // single recovery path and avoid rendering stale cached permissions.
    if (token.value) {
      clearAdminSession()
      loginError.value = error.message || 'Please sign in again.'
    }
    return false
  } finally {
    sessionChecking.value = false
  }
}

onMounted(async () => {
  try {
    const routePage = window.location.hash.replace(/^#\/?/, '')
    const savedPage = nav.some(([key]) => key === routePage)
      ? routePage
      : sessionStorage.getItem(PAGE_STATE_KEY)
    if (nav.some(([key]) => key === savedPage)) page.value = savedPage
  } catch { /* Session storage may be unavailable. */ }
  pageStateReady.value = true
  if (page.value) {
    try { sessionStorage.setItem(PAGE_STATE_KEY, page.value) } catch { /* Session storage may be unavailable. */ }
  }
  if (await restoreAdminSession()) {
    if (!visibleNav.value.some(([key]) => key === page.value)) page.value = 'dashboard'
    await load()
    await checkHealth()
    if (isGlobalAdmin.value) await loadAssistantConfig()
  }
})
</script>

<template>
  <div v-if="sessionChecking" class="login-page" role="status" aria-live="polite">
    <div class="session-check"><RefreshCw class="spin" /><span>Verifying secure session…</span></div>
  </div>

  <div v-else-if="!token" class="login-page">
    <div class="login-card">
      <div class="logo"><span>EBA</span>phone <small>Administration</small></div>
      <h1>Staff sign in</h1>
      <p>Secure access for administrators and store teams.</p>
      <form @submit.prevent="login">
        <label for="admin-username">Username</label>
        <input id="admin-username" v-model="username" autocomplete="username" autofocus>
        <label for="admin-password">Password</label>
        <input id="admin-password" v-model="password" type="password" autocomplete="current-password">
        <p v-if="loginError" class="login-error" role="alert">{{ loginError }}</p>
        <button :disabled="loginBusy" type="submit">{{ loginBusy ? 'Signing in…' : 'Sign in' }}</button>
      </form>
      <small>Use the staff credentials provided by your administrator.</small>
    </div>
  </div>

  <div v-else class="shell">
    <aside>
      <div class="logo"><span>EBA</span>phone <small>{{ admin?.role || 'staff' }}</small></div>
      <nav aria-label="Admin navigation">
        <button v-for="item in visibleNav" :key="item[0]" :class="{ active: page === item[0] }" @click="selectPage(item[0])"><component :is="item[2]" />{{ item[1] }}<span v-if="item[0] === 'orders' && orders.length" class="nav-count">{{ orders.length }}</span></button>
      </nav>
      <div class="sidebar-foot"><div class="admin-chip"><span>{{ admin?.name?.slice(0, 1) || 'A' }}</span><div><b>{{ admin?.name || 'Administrator' }}</b><small>{{ admin?.username || 'staff' }}</small></div></div><button class="logout" @click="logout"><LogOut />Sign out</button></div>
    </aside>

    <main>
      <header class="page-header">
        <div class="page-header-main"><button class="mobile-menu-trigger" :aria-expanded="mobileNavOpen" aria-label="Open navigation" @click="mobileNavOpen = true"><Menu /></button><div><p class="eyebrow">{{ admin?.name || 'Operations' }}</p><h1>{{ pageTitle }}</h1><small v-if="lastRefresh">Updated {{ dateLabel(lastRefresh) }}</small></div></div>
        <div class="header-actions"><span v-if="loading" class="loading-label"><RefreshCw class="spin" />Syncing</span><button class="secondary" :disabled="loading" @click="load"><RefreshCw />Refresh</button></div>
      </header>

      <div v-if="loadError" class="notice error"><AlertTriangle /><span>{{ loadError }}</span><button @click="load">Retry</button></div>
      <div v-if="notice" class="notice success" role="status"><CheckCircle2 /><span>{{ notice }}</span><button aria-label="Dismiss" @click="notice = ''"><X /></button></div>

      <template v-if="page === 'dashboard'">
        <section class="stats">
          <div class="stat-card"><span>Collected payments</span><b>{{ money(grossPayments) }}</b><small>{{ paidOrders.length }} paid order{{ paidOrders.length === 1 ? '' : 's' }}</small><WalletCards /></div>
          <div class="stat-card"><span>Total orders</span><b>{{ orders.length }}</b><small>{{ orders.filter((order) => order.payment_status === 'pending').length }} awaiting payment</small><ShoppingBag /></div>
          <div class="stat-card"><span>Fulfillment queue</span><b>{{ pendingFulfillment.length }}</b><small>Processing, shipping or store handoff</small><Truck /></div>
          <div class="stat-card"><span>Low stock positions</span><b>{{ lowStockRows.length }}</b><small>{{ totalAvailable }} units across {{ scopedStores.length }} stores</small><PackageSearch /></div>
        </section>
        <section class="quick-actions panel"><div><h2>Operational shortcuts</h2><p>Jump directly to the work that needs attention.</p></div><div class="shortcut-row"><button @click="openOrdersPage('orders', { payment: 'pending' })"><Clock3 />Review unpaid</button><button @click="openOrdersPage('fulfillment')"><Truck />Fulfillment queue</button><button @click="selectPage('inventory')"><PackageSearch />Update stock</button><button @click="selectPage('reports')"><Download />Export report</button></div></section>
        <section class="dashboard-grid">
          <div class="panel"><div class="panel-heading"><div><h2>Store operations</h2><p>Live availability by location</p></div><button class="text-button" @click="selectPage('inventory')">Manage inventory <ExternalLink /></button></div><div class="store-cards"><article v-for="entry in storeStats" :key="entry.store.id" class="store-card"><div class="store-title"><Store /><div><b>{{ entry.store.name }}</b><small>{{ entry.store.open_hours }}</small></div></div><div class="store-metrics"><span><b>{{ entry.units }}</b> units</span><span><b>{{ entry.activeSkus }}</b> SKUs</span><span :class="{ warning: entry.lowStock }"><b>{{ entry.lowStock }}</b> low</span></div><small class="muted"><MapPin />{{ entry.store.address }}</small></article><div v-if="!storeStats.length" class="empty-inline">No active stores returned by the API.</div></div></div>
          <div class="panel attention-panel"><div class="panel-heading"><div><h2>Needs attention</h2><p>Actionable exceptions</p></div><AlertTriangle /></div><button class="attention-row" @click="openOrdersPage('orders', { payment: 'pending' })"><b>{{ orders.filter((order) => order.payment_status === 'pending').length }}</b><span>Orders awaiting payment <ExternalLink /></span></button><button class="attention-row" @click="openOrdersPage('orders', { payment: 'paid_pending_review' })"><b>{{ orders.filter((order) => order.payment_status === 'paid_pending_review').length }}</b><span>Payments awaiting review <ExternalLink /></span></button><button class="attention-row" @click="openOrdersPage('fulfillment')"><b>{{ pendingFulfillment.length }}</b><span>Orders in fulfillment queue <ExternalLink /></span></button><button class="attention-row" @click="selectPage('inventory')"><b>{{ lowStockRows.length }}</b><span>Low-stock store positions <ExternalLink /></span></button></div>
        </section>
        <section class="panel"><div class="panel-heading"><div><h2>Recent orders</h2><p>Newest activity across all stores</p></div><button class="text-button" @click="selectPage('orders')">View all <ExternalLink /></button></div><div class="table-wrap"><table><thead><tr><th>Order / customer</th><th>Order total</th><th>Store</th><th>Status</th><th>Created</th></tr></thead><tbody><tr v-for="order in orders.slice(0, 8)" :key="order.id"><td><b>{{ order.product_name }}<template v-if="order.quantity > 1"> × {{ order.quantity }}</template></b><small>{{ order.id }} · {{ order.customer_name }} · {{ order.customer_phone }}</small></td><td>{{ money(orderTotal(order)) }}<small>Paid {{ money(order.paid_amount ?? 0) }} · {{ statusLabel(order.payment_status) }}</small></td><td>{{ order.store_name || 'Unassigned' }}</td><td><span :class="['status-pill', statusClass(order.order_status)]">{{ statusLabel(order.order_status) }}</span></td><td>{{ shortDate(order.created_at) }}</td></tr><tr v-if="!orders.length"><td colspan="5" class="empty-cell">No orders yet.</td></tr></tbody></table></div></section>
      </template>

      <template v-else-if="page === 'orders' || page === 'fulfillment'">
        <section class="panel data-panel"><div class="toolbar order-toolbar"><div class="search-field"><Search /><input v-model="orderSearch" placeholder="Search order, customer or phone"></div><select v-model="orderStatusFilter"><option value="all">All order statuses</option><option v-for="status in orderStatuses" :key="status" :value="status">{{ statusLabel(status) }}</option></select><select v-model="orderPaymentFilter"><option value="all">All payment statuses</option><option value="pending">Pending payment</option><option value="paid_pending_review">Payment review</option><option value="deposit_paid">Deposit paid</option><option value="paid">Paid in full</option><option value="refund_pending">Refund pending</option><option value="refunded">Refunded</option></select><select v-model="orderStoreFilter"><option value="all">All stores</option><option v-for="store in accessibleStores" :key="store.id" :value="store.id">{{ store.name }}</option></select><button class="secondary" @click="orderSearch = ''; orderStatusFilter = 'all'; orderPaymentFilter = 'all'; orderStoreFilter = 'all'">Clear</button></div><div class="table-wrap"><table class="orders-table"><thead><tr><th>Order / customer</th><th>Amounts</th><th>Payment</th><th>Fulfillment / store</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="order in (page === 'fulfillment' ? fulfillmentOrders : filteredOrders)" :key="order.id"><td><b>{{ order.product_name }}<template v-if="order.quantity > 1"> × {{ order.quantity }}</template></b><small>{{ order.id }}</small><small>{{ order.customer_name }} · {{ order.customer_phone }}</small></td><td><b>{{ money(orderTotal(order)) }}</b><small>Paid {{ money(order.paid_amount ?? 0) }} · Balance {{ money(order.balance_due ?? order.remaining_amount) }}</small></td><td><span :class="['status-pill', statusClass(order.payment_status)]">{{ statusLabel(order.payment_status) }}</span></td><td>{{ order.fulfillment_type || 'Store' }}<small>{{ order.store_name || order.shipping_address || 'Not assigned' }}</small><small v-if="order.tracking_number">Tracking: {{ order.tracking_number }}</small></td><td><span :class="['status-pill', statusClass(order.order_status)]">{{ statusLabel(order.order_status) }}</span></td><td><div class="action-list"><button v-for="action in actionsFor(order)" :key="action.key" :class="{ danger: action.danger }" :title="action.label" @click="openOrderAction(order, action.key)"><component :is="action.icon" />{{ action.label }}</button><span v-if="!actionsFor(order).length" class="muted">No action</span></div></td></tr><tr v-if="(page === 'fulfillment' ? !fulfillmentOrders.length : !filteredOrders.length)"><td colspan="6" class="empty-cell">{{ page === 'fulfillment' ? 'No orders in the fulfillment queue.' : 'No matching orders.' }}</td></tr></tbody></table></div></section>
      </template>

      <template v-else-if="page === 'catalog'">
        <section class="panel"><div class="toolbar"><div class="search-field"><Search /><input v-model="productSearch" placeholder="Search product, brand or variant"></div><select v-model="productCategoryFilter"><option value="all">All categories</option><option v-for="category in productCategories" :key="category" :value="category">{{ statusLabel(category) }}</option></select><span class="toolbar-result">{{ filteredSkus.length }} products</span><button v-if="canEditCatalog" class="primary toolbar-primary" @click="openProductCreator"><Plus />Add product</button></div><p v-if="!canEditCatalog" class="scope-note"><Boxes />Catalog details are read-only for store-scoped accounts. A global administrator can add or edit products.</p><div class="product-grid"><article v-for="sku in filteredSkus" :key="sku.id" class="product-admin-card"><img :src="sku.image" :alt="sku.product_name" @error="useProductImageFallback($event, sku.product_name)"><div class="product-content"><div class="product-meta"><span>{{ sku.brand }}</span><span :class="['category-tag', `category-${sku.category}`]">{{ statusLabel(sku.category) }}</span></div><h3>{{ sku.product_name }}</h3><p>{{ sku.variant }}</p><strong>{{ money(sku.price) }}</strong><small>{{ Number(sku.deposit_rate) }}% deposit · {{ Object.values(sku.store_stock || {}).reduce((sum, value) => sum + Number(value || 0), 0) }} units available</small><div class="product-actions"><button v-if="canEditCatalog" class="secondary" @click="openProductEditor(sku)"><Edit3 /><span>Edit product</span></button><span v-else class="readonly-label-inline" title="Product editing requires global administrator access">Read-only</span><button class="text-button" @click="inventorySearch = sku.product_name; inventoryCategoryFilter = 'all'; selectPage('inventory')"><PackageSearch /><span>Stock</span></button></div></div></article><div v-if="!filteredSkus.length" class="empty-state"><Boxes /><h2>No products found</h2><p>Try a different search or category filter.</p></div></div></section>
      </template>

      <template v-else-if="page === 'inventory'">
        <section class="panel data-panel"><div class="panel-heading"><div><h2>Multi-store stock matrix</h2><p>Edit available units per store. Locked and sold quantities remain protected by the API.</p></div><button class="secondary" @click="load"><RefreshCw />Reload stock</button></div><div class="toolbar inventory-toolbar"><div class="search-field"><Search /><input v-model="inventorySearch" placeholder="Search product, brand or variant"></div><select v-model="inventoryCategoryFilter"><option value="all">All categories</option><option v-for="category in productCategories" :key="category" :value="category">{{ statusLabel(category) }}</option></select><span class="toolbar-result">{{ inventorySkus.length }} products</span></div><p v-if="!isGlobalAdmin" class="scope-note"><Store /> <template v-if="admin?.store_id">You can edit stock only for {{ stores.find((store) => Number(store.id) === Number(admin.store_id))?.name || `store #${admin.store_id}` }}. Other store columns are read-only.</template><template v-else>Your account has no store scope, so inventory is read-only. Ask a manager to assign a store.</template></p><div class="table-wrap"><table class="inventory-table"><thead><tr><th>Product</th><th v-for="store in stores" :key="store.id"><Store />{{ store.name }}<small v-if="!canAccessStore(store.id)" class="readonly-label">Read only</small></th></tr></thead><tbody><tr v-for="sku in inventorySkus" :key="sku.id"><td><b>{{ sku.product_name }}</b><small>{{ sku.brand }} · {{ sku.variant }}</small></td><td v-for="store in stores" :key="store.id" :class="{ 'readonly-cell': !canAccessStore(store.id) }"><div class="stock-editor"><input v-model.number="stockDraft[stockKey(sku.id, store.id)]" type="number" min="0" step="1" :disabled="!canAccessStore(store.id)" :aria-label="`${sku.product_name} stock at ${store.name}`"><button :disabled="!canAccessStore(store.id) || stockSaving[stockKey(sku.id, store.id)]" title="Save stock" @click="saveStock(sku, store)"><Save /></button></div><small :class="{ 'stock-low': stockValue(sku, store.id) <= 1 }">{{ stockValue(sku, store.id) <= 1 ? 'Low stock' : 'Available' }}</small></td></tr><tr v-if="!inventorySkus.length"><td :colspan="stores.length + 1" class="empty-cell">No products to manage.</td></tr></tbody></table></div></section>
        <section class="store-cards inventory-store-cards"><article v-for="entry in storeStats" :key="entry.store.id" class="store-card"><div class="store-title"><Store /><div><b>{{ entry.store.name }}</b><small>{{ entry.store.phone }}</small></div></div><div class="store-metrics"><span><b>{{ entry.units }}</b> units</span><span><b>{{ entry.activeSkus }}</b> stocked</span><span :class="{ warning: entry.lowStock }"><b>{{ entry.lowStock }}</b> low</span></div><small class="muted"><MapPin />{{ entry.store.address }}</small></article></section>
      </template>

      <template v-else-if="page === 'finance'">
        <section class="stats finance-stats"><div class="stat-card"><span>Collected payments</span><b>{{ money(grossPayments) }}</b><small>{{ paidOrders.length }} paid orders, including review holds</small><WalletCards /></div><div class="stat-card"><span>Unpaid orders</span><b>{{ orders.filter((order) => order.payment_status === 'pending').length }}</b><small>Use payment status check after a gateway callback</small><Clock3 /></div><div class="stat-card"><span>Refund requests</span><b>{{ orders.filter((order) => order.payment_status === 'refund_pending' || order.payment_status === 'refunded').length }}</b><small>Pending or completed refunds</small><RotateCcw /></div><div class="stat-card"><span>Average order value</span><b>{{ money(orders.length ? orders.reduce((sum, order) => sum + orderTotal(order), 0) / orders.length : 0) }}</b><small>Based on order totals</small><BarChart3 /></div></section><section class="panel"><div class="panel-heading"><div><h2>Payment activity</h2><p>Refund, reconciliation and payment-status actions use the configured payment provider.</p></div><button class="secondary" @click="selectPage('reports')">Open reports <ExternalLink /></button></div><div class="table-wrap"><table><thead><tr><th>Order</th><th>Customer</th><th>Amount</th><th>Payment</th><th>Order status</th><th>Actions</th></tr></thead><tbody><tr v-for="order in orders" :key="order.id"><td><b>{{ order.id }}</b><small>{{ order.product_name }}</small></td><td>{{ order.customer_name }}<small>{{ order.customer_phone }}</small></td><td>{{ money(order.paid_amount ?? 0) }}<small>of {{ money(orderTotal(order)) }}</small></td><td><span :class="['status-pill', statusClass(order.payment_status)]">{{ statusLabel(order.payment_status) }}</span></td><td>{{ statusLabel(order.order_status) }}</td><td><div class="action-list"><button v-for="action in actionsFor(order).filter((item) => ['settle', 'refund', 'payment-status', 'reconcile-payment', 'fulfill-payment-review'].includes(item.key))" :key="action.key" :class="{ danger: action.danger }" @click="openOrderAction(order, action.key)"><component :is="action.icon" />{{ action.label }}</button><span v-if="!actionsFor(order).some((item) => ['settle', 'refund', 'payment-status', 'reconcile-payment', 'fulfill-payment-review'].includes(item.key))" class="muted">No action</span></div></td></tr><tr v-if="!orders.length"><td colspan="6" class="empty-cell">No payment activity.</td></tr></tbody></table></div></section>
      </template>

      <template v-else-if="page === 'users'">
        <section class="panel data-panel">
          <div class="toolbar customer-toolbar"><div class="search-field"><Search /><input v-model="customerSearch" placeholder="Search customer, phone, email or address"></div><select v-model="customerStatusFilter"><option value="all">All statuses</option><option value="active">Active</option><option value="inactive">Paused</option></select><span class="toolbar-result">{{ filteredCustomers.length }} customers</span><button class="secondary" @click="exportCustomers"><Download />Export CSV</button></div>
          <p v-if="!canEditCustomers" class="scope-note"><Users />Customers shown here have ordered through your store. Profile fields are read-only for store-scoped accounts.</p>
          <div class="table-wrap"><table class="customer-table"><thead><tr><th>Customer</th><th>Contact</th><th>Orders</th><th>Order value</th><th>Default address</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="customer in filteredCustomers" :key="customer.id" :class="{ 'inactive-row': customer.active === false }"><td><b>{{ customer.name }}</b><small>Customer #{{ customer.id }} · joined {{ shortDate(customer.created_at) }}</small></td><td>{{ customer.phone }}<small>{{ customer.email || 'No email saved' }}</small></td><td><b>{{ customer.order_count || 0 }}</b><small>Last {{ dateLabel(customer.last_order_at) }}</small></td><td><b>{{ money(customer.order_value) }}</b><small>{{ money(customer.paid_value) }} collected</small></td><td>{{ customer.default_address || '—' }}<small>{{ customer.stores?.join(', ') || 'No store activity' }}</small></td><td><span :class="['status-pill', customer.active === false ? 'status-cancelled' : 'status-paid']">{{ customer.active === false ? 'Paused' : 'Active' }}</span></td><td><button class="secondary compact-action" @click="openCustomerEditor(customer)"><component :is="canEditCustomers ? Edit3 : ExternalLink" />{{ canEditCustomers ? 'View / edit' : 'View details' }}</button></td></tr><tr v-if="!filteredCustomers.length"><td colspan="7" class="empty-cell">No customers match the selected filters.</td></tr></tbody></table></div>
        </section>
      </template>

      <template v-else-if="page === 'service'">
        <section class="panel support-panel">
          <div class="panel-heading management-heading"><div><h2>Support inbox</h2><p>Read customer messages, reply in the same conversation and close completed cases.</p></div><button class="secondary" :disabled="loading" @click="load"><RefreshCw />Refresh inbox</button></div>
          <div class="toolbar support-toolbar"><div class="search-field"><Search /><input v-model="supportSearch" placeholder="Search customer, phone or subject"></div><select v-model="supportStatusFilter"><option value="all">All conversations</option><option value="open">Open</option><option value="waiting_customer">Waiting for customer</option><option value="resolved">Resolved</option></select><span class="toolbar-result">{{ filteredSupportConversations.length }} conversations</span></div>
          <div class="support-inbox">
            <div class="conversation-list" aria-label="Support conversations">
              <button v-for="conversation in filteredSupportConversations" :key="conversation.id" :class="{ active: supportSelected?.id === conversation.id }" @click="openSupportConversation(conversation)"><span class="conversation-avatar">{{ conversation.customer_name?.slice(0, 1) || '?' }}</span><span class="conversation-copy"><span><b>{{ conversation.customer_name || 'Customer' }}</b><small>{{ dateLabel(conversation.last_message_at) }}</small></span><strong>{{ conversation.subject || 'General support' }}</strong><small>{{ conversation.last_message || 'Open conversation to read messages' }}</small><em :class="['status-pill', statusClass(conversation.status)]">{{ supportStatusLabel(conversation.status) }}</em></span></button>
              <div v-if="!filteredSupportConversations.length" class="empty-state compact-empty"><MessageCircle /><h2>No conversations found</h2><p>New customer messages will appear here.</p></div>
            </div>
            <section v-if="supportSelected" class="conversation-thread" aria-label="Selected support conversation">
              <header><div><p class="eyebrow">{{ supportSelected.id }}</p><h2>{{ supportSelected.customer_name }}</h2><span>{{ supportSelected.customer_phone }} · {{ supportSelected.subject }}</span></div><div class="thread-actions"><a class="secondary" :href="`tel:${supportSelected.customer_phone}`"><Phone />Call</a><button class="text-button" @click="copyText(supportSelected.customer_phone)"><Copy />Copy phone</button><button v-if="supportSelected.status === 'resolved'" class="secondary" :disabled="supportBusy" @click="updateSupportStatus('open')"><RotateCcw />Reopen</button><button v-else class="secondary" :disabled="supportBusy" @click="updateSupportStatus('resolved')"><CheckCircle2 />Close</button><button class="thread-close" aria-label="Close conversation view" @click="closeSupportConversation"><X /></button></div></header>
              <div class="message-stream"><article v-for="message in supportSelected.messages" :key="message.id" :class="['message-row', `sender-${message.sender_type}`]"><div><span>{{ supportSenderLabel(message.sender_type) }} · {{ dateLabel(message.created_at) }}</span><p>{{ message.message }}</p></div></article><div v-if="!supportSelected.messages?.length" class="empty-inline">This conversation has no messages yet.</div></div>
              <form class="support-composer" @submit.prevent="sendSupportReply"><label for="support-reply">Reply to {{ supportSelected.customer_name }}</label><textarea id="support-reply" v-model="supportReply" rows="3" maxlength="1000" :disabled="supportBusy || supportSelected.status === 'resolved'" :placeholder="supportSelected.status === 'resolved' ? 'Reopen this conversation before replying' : 'Write a clear customer reply'"></textarea><div><span>{{ supportReply.length }}/1000</span><button class="primary" type="submit" :disabled="supportBusy || supportSelected.status === 'resolved' || !supportReply.trim()"><Send />{{ supportBusy ? 'Sending…' : 'Send reply' }}</button></div><p v-if="supportError" class="form-error" role="alert">{{ supportError }}</p></form>
            </section>
            <div v-else class="conversation-placeholder"><MessageCircle /><h2>Select a conversation</h2><p>Choose a customer message from the inbox to read and reply.</p><p v-if="supportError" class="form-error" role="alert">{{ supportError }}</p></div>
          </div>
        </section>
      </template>

      <template v-else-if="page === 'reports'">
        <section class="panel"><div class="toolbar report-toolbar"><select v-model="reportStatus" aria-label="Order status"><option value="all">All order statuses</option><option v-for="status in orderStatuses" :key="status" :value="status">{{ statusLabel(status) }}</option></select><select v-model="reportStore" aria-label="Store"><option value="all">All stores</option><option v-for="store in accessibleStores" :key="store.id" :value="store.id">{{ store.name }}</option></select><label>From<input v-model="reportFrom" type="date"></label><label>To<input v-model="reportTo" type="date"></label><button class="secondary" @click="exportOrders"><Download />Export orders CSV</button></div><div class="report-summary"><div><span>Matching orders</span><b>{{ reportRows.length }}</b></div><div><span>Collected payments</span><b>{{ money(reportRevenue) }}</b></div><div><span>Average order value</span><b>{{ money(reportAverage) }}</b></div><div><span>Fulfillment rate</span><b>{{ reportFulfillmentRate }}%</b></div></div><div class="table-wrap"><table><thead><tr><th>Order</th><th>Store</th><th>Payment</th><th>Status</th><th>Total</th><th>Created</th></tr></thead><tbody><tr v-for="order in reportRows" :key="order.id"><td><b>{{ order.id }}<template v-if="order.quantity > 1"> × {{ order.quantity }}</template></b><small>{{ order.product_name }} · {{ order.customer_name }}</small></td><td>{{ order.store_name || order.store_id || '—' }}</td><td>{{ statusLabel(order.payment_status) }}</td><td>{{ statusLabel(order.order_status) }}</td><td>{{ money(orderTotal(order)) }}</td><td>{{ dateLabel(order.created_at) }}</td></tr><tr v-if="!reportRows.length"><td colspan="6" class="empty-cell">No rows match the selected filters.</td></tr></tbody></table></div></section>
      </template>

      <template v-else-if="page === 'assistant'">
        <div class="assistant-page">
          <section class="assistant-hero">
            <div class="assistant-hero-icon"><Bot /></div>
            <div class="assistant-hero-copy"><p class="eyebrow">CUSTOMER SUPPORT AUTOMATION</p><h2>Support assistant</h2><p>Answer product, store and common policy questions. Account actions and order-specific requests remain with your support team.</p></div>
            <div class="assistant-hero-status"><span :class="['assistant-state-dot', { active: assistantConfig.enabled }]"></span><b>{{ assistantConfig.enabled ? 'Assistant active' : 'Assistant paused' }}</b><small>{{ assistantConfig.usage_today || 0 }} requests today</small></div>
          </section>

          <section class="panel assistant-card">
            <div class="assistant-section-heading"><span class="assistant-step">01</span><div><h2>Connect your model</h2><p>Use an OpenAI-compatible Chat Completions endpoint. Your API key is encrypted and never shown again after saving.</p></div></div>
            <label class="assistant-enable-row"><input v-model="assistantConfig.enabled" type="checkbox"><span><b>Enable the customer-facing assistant</b><small>Customers will receive AI answers in the Support tab.</small></span><span class="assistant-switch" aria-hidden="true"></span></label>
            <div class="assistant-provider-grid">
              <label>Base URL<span class="field-hint">API root, for example https://api.openai.com/v1</span><input v-model="assistantConfig.base_url" type="url" maxlength="500" placeholder="https://api.openai.com/v1"></label>
              <label>Model name<input v-model="assistantConfig.model" maxlength="120" placeholder="gpt-4o-mini"></label>
              <label class="assistant-key-field">API key<span class="field-hint">{{ assistantConfig.api_key_configured ? 'Key saved. Enter a new key only to rotate it.' : 'Add a key to enable the assistant.' }}</span><div class="assistant-key-input"><KeyRound /><input v-model="assistantApiKey" type="password" autocomplete="new-password" placeholder="Paste your provider API key"></div></label>
              <label v-if="assistantConfig.api_key_configured" class="assistant-remove-key"><input v-model="assistantClearKey" type="checkbox"> Remove saved key</label>
            </div>
          </section>

          <section class="panel assistant-card">
            <div class="assistant-section-heading"><span class="assistant-step">02</span><div><h2>Shape the assistant</h2><p>Add your preferred tone and service guidance. Fixed safety rules stay in place.</p></div></div>
            <label class="assistant-prompt-field">Assistant guidance<textarea v-model="assistantConfig.prompt" rows="5" maxlength="8000" placeholder="For example: use a warm, concise tone and address customers by name when they share it."></textarea><span class="assistant-prompt-meta"><small>Used with live product, price, stock and store information.</small><small>{{ assistantConfig.prompt.length }}/8000</small></span></label>
          </section>

          <section class="panel assistant-card">
            <div class="assistant-section-heading"><span class="assistant-step">03</span><div><h2>Set usage limits</h2><p>Controls are enforced by the API across all sessions.</p></div></div>
            <div class="assistant-limit-section"><div class="assistant-limit-title"><b>Response settings</b><span>Control answer length and variability</span></div><div class="assistant-limits-grid">
              <label>Temperature<input v-model.number="assistantConfig.temperature" type="number" min="0" max="2" step="0.05"><small>Lower values keep answers more consistent.</small></label>
              <label>Max reply tokens<input v-model.number="assistantConfig.max_tokens" type="number" min="50" max="1000" step="50"><small>Caps the size of each model reply.</small></label>
              <label>Max message characters<input v-model.number="assistantConfig.max_input_chars" type="number" min="50" max="1000" step="50"><small>Longer messages are rejected.</small></label>
            </div></div>
            <div class="assistant-limit-section"><div class="assistant-limit-title"><b>Abuse protection</b><span>Limit repeat use and overall API spend</span></div><div class="assistant-limits-grid assistant-abuse-grid">
              <label>Conversation history<input v-model.number="assistantConfig.history_messages" type="number" min="0" max="20" step="1"><small>Prior messages sent with each question.</small></label>
              <label>Customer cooldown<input v-model.number="assistantConfig.per_user_cooldown_seconds" type="number" min="0" max="300" step="1"><small>Seconds between messages.</small></label>
              <label>Requests per customer / day<input v-model.number="assistantConfig.per_user_daily_limit" type="number" min="1" max="500" step="1"><small>Maximum for one signed-in customer.</small></label>
              <label>Global requests / day<input v-model.number="assistantConfig.global_daily_limit" type="number" min="1" max="100000" step="50"><small>Maximum across all customers.</small></label>
            </div></div>
            <div class="assistant-safety-note"><ShieldCheck /><p><b>Human support stays in control</b><span>The assistant cannot access orders or account records, issue refunds or change orders. If the model is unavailable, messages remain in the support inbox.</span></p></div>
          </section>

          <div class="assistant-feedback" aria-live="polite"><p v-if="assistantError" class="form-error" role="alert">{{ assistantError }}</p><p v-if="assistantNotice" class="health-box good" role="status"><CheckCircle2 />{{ assistantNotice }}</p></div>
          <div class="assistant-action-bar"><span><LockKeyhole />API key stays private to the server</span><div><button class="secondary" :disabled="assistantTesting || assistantBusy" @click="testAssistantConnection">{{ assistantTesting ? 'Testing…' : 'Test connection' }}</button><button class="primary" :disabled="assistantBusy || assistantTesting" @click="saveAssistantConfig"><Save />{{ assistantBusy ? 'Saving…' : 'Save settings' }}</button></div></div>
        </div>
      </template>

      <BannerManager v-else-if="page === 'banners'" :token="token" @unauthorized="handleBannerUnauthorized" />

      <template v-else-if="page === 'stores'">
        <section class="panel data-panel">
          <div class="panel-heading management-heading"><div><h2>Store directory</h2><p>Manage customer pickup locations, contact details and operating availability.</p></div><button v-if="canManageOrganisation" class="primary" @click="openStoreEditor()"><Plus />Add store</button></div>
          <div class="toolbar"><div class="search-field"><Search /><input v-model="storeSearch" placeholder="Search store, address or phone"></div><select v-model="storeStatusFilter"><option value="all">All statuses</option><option value="active">Active</option><option value="inactive">Paused</option></select><span class="toolbar-result">{{ filteredStores.length }} stores</span></div>
          <p v-if="!canManageOrganisation" class="scope-note"><Store />Store details are read-only for your account. Contact a global administrator to create, edit or pause locations.</p>
          <div class="table-wrap"><table class="management-table"><thead><tr><th>Store</th><th>Address</th><th>Phone</th><th>Opening hours</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="store in filteredStores" :key="store.id" :class="{ 'inactive-row': !store.active }"><td><b>{{ store.name }}</b><small>Store #{{ store.id }}</small></td><td>{{ store.address }}</td><td>{{ store.phone }}</td><td>{{ store.open_hours }}</td><td><span :class="['status-pill', store.active ? 'status-paid' : 'status-cancelled']">{{ store.active ? 'Active' : 'Paused' }}</span></td><td><div v-if="canManageOrganisation" class="action-list"><button @click="openStoreEditor(store)"><Edit3 />Edit</button><button :class="{ danger: store.active }" @click="toggleStore(store)"><Power />{{ store.active ? 'Pause' : 'Activate' }}</button></div><span v-else class="muted">Read only</span></td></tr><tr v-if="!filteredStores.length"><td colspan="6" class="empty-cell">No stores match the selected filters.</td></tr></tbody></table></div>
        </section>
      </template>

      <template v-else-if="page === 'staff'">
        <section class="panel data-panel">
          <div class="panel-heading management-heading"><div><h2>Staff accounts</h2><p>Assign each team member a role and the minimum store scope needed for their work.</p></div><button v-if="canManageOrganisation" class="primary" @click="openStaffEditor()"><Plus />Add staff account</button></div>
          <div class="toolbar"><div class="search-field"><Search /><input v-model="staffSearch" placeholder="Search name or username"></div><select v-model="staffRoleFilter"><option value="all">All roles</option><option value="super_admin">Super admin</option><option value="manager">Manager</option><option value="operator">Operator</option></select><select v-model="staffStatusFilter"><option value="all">All statuses</option><option value="active">Active</option><option value="inactive">Paused</option></select><span class="toolbar-result">{{ filteredAdminUsers.length }} accounts</span></div>
          <p v-if="!canManageOrganisation" class="scope-note"><UserCog />You can view your own account assignment here. Staff creation, roles and access scopes require a global administrator.</p>
          <div class="table-wrap"><table class="management-table"><thead><tr><th>Staff member</th><th>Username</th><th>Role</th><th>Store scope</th><th>Status</th><th>Actions</th></tr></thead><tbody><tr v-for="user in filteredAdminUsers" :key="user.id" :class="{ 'inactive-row': user.active === false }"><td><b>{{ user.name }}</b><small>Account #{{ user.id }}</small></td><td>{{ user.username }}</td><td><span class="category-tag">{{ statusLabel(user.role) }}</span></td><td>{{ storeName(user.store_id) }}</td><td><span :class="['status-pill', user.active === false ? 'status-cancelled' : 'status-paid']">{{ user.active === false ? 'Paused' : 'Active' }}</span></td><td><div v-if="canEditStaffUser(user)" class="action-list"><button @click="openStaffEditor(user)"><Edit3 />Edit</button><button :class="{ danger: user.active !== false }" :disabled="Number(user.id) === Number(admin?.id) && user.active !== false" :title="Number(user.id) === Number(admin?.id) ? 'You cannot deactivate your own account' : ''" @click="toggleStaff(user)"><Power />{{ user.active === false ? 'Activate' : 'Pause' }}</button></div><span v-else class="muted">{{ canManageOrganisation ? 'Super admin only' : 'Read only' }}</span></td></tr><tr v-if="!filteredAdminUsers.length"><td colspan="6" class="empty-cell">No staff accounts match the selected filters.</td></tr></tbody></table></div>
        </section>
        <section class="permission-guide"><div><b>Super admin</b><span>Full catalog, stores, staff and all-store operations.</span></div><div><b>Manager</b><span>All stores when unassigned, or one selected store when scoped.</span></div><div><b>Operator</b><span>Orders and inventory for one assigned store.</span></div></section>
      </template>

      <template v-else-if="page === 'settings'">
        <section class="settings-grid"><div class="panel"><div class="panel-heading"><div><h2>Signed-in account</h2><p>Current administrator identity and permissions</p></div><Settings /></div><dl class="detail-list"><div><dt>Name</dt><dd>{{ admin?.name || '—' }}</dd></div><div><dt>Username</dt><dd>{{ admin?.username || '—' }}</dd></div><div><dt>Role</dt><dd><span class="category-tag">{{ admin?.role || 'staff' }}</span></dd></div><div><dt>Store scope</dt><dd>{{ storeName(admin?.store_id) }}</dd></div></dl><button class="danger-button" @click="logout"><LogOut />Sign out</button></div><div class="panel"><div class="panel-heading"><div><h2>API connection</h2><p>Health check for the commerce service</p></div><CheckCircle2 :class="health?.error ? 'health-bad' : 'health-good'" /></div><div v-if="health?.loading" class="loading-block"><RefreshCw class="spin" />Checking…</div><div v-else-if="health?.error" class="health-box bad"><AlertTriangle /><span>{{ health.error }}</span></div><div v-else class="health-box good"><CheckCircle2 /><span><b>API online</b><small>{{ health?.currency || 'GHS' }} · checked {{ dateLabel(health?.checkedAt) }}</small></span></div><button class="secondary" @click="checkHealth"><RefreshCw />Run health check</button></div></section><section class="panel"><div class="panel-heading"><div><h2>Operations configuration</h2><p>Keep storefront locations and staff access current.</p></div><Settings /></div><div class="settings-shortcuts"><button class="secondary" @click="selectPage('stores')"><Store />Manage stores</button><button class="secondary" @click="selectPage('staff')"><UserCog />Manage staff accounts</button></div></section>
      </template>
    </main>

    <div v-if="mobileNavOpen" class="mobile-nav-backdrop" aria-hidden="true" @click="mobileNavOpen = false"></div>
    <aside class="mobile-nav" :class="{ open: mobileNavOpen }" aria-label="Mobile admin navigation">
      <div class="mobile-nav-header"><div class="logo"><span>EBA</span>phone <small>{{ admin?.role || 'staff' }}</small></div><button aria-label="Close navigation" @click="mobileNavOpen = false"><X /></button></div>
      <nav>
        <button v-for="item in visibleNav" :key="item[0]" :class="{ active: page === item[0] }" @click="selectPage(item[0])"><component :is="item[2]" />{{ item[1] }}<span v-if="item[0] === 'orders' && orders.length" class="nav-count">{{ orders.length }}</span></button>
      </nav>
      <button class="logout" @click="logout"><LogOut />Sign out</button>
    </aside>
  </div>

  <div v-if="orderAction" class="modal-backdrop" @click.self="closeOrderAction">
    <section ref="orderDialogRef" class="modal-card" role="dialog" aria-modal="true" aria-labelledby="order-action-title" tabindex="-1" @keydown="trapOrderDialogFocus">
      <button class="modal-close" aria-label="Close" @click="closeOrderAction"><X /></button>
      <p class="eyebrow">Order action</p>
      <h2 id="order-action-title">{{ orderAction.key === 'refund' ? 'Request refund' : orderAction.key === 'settle' ? 'Collect remaining balance' : orderAction.key === 'release' ? 'Release reservation' : orderAction.key === 'tracking' ? 'Add tracking number' : orderAction.key === 'complete' ? (orderAction.order.fulfillment_type === 'pickup' ? 'Complete pickup' : 'Mark delivered') : orderAction.key === 'dispatch' ? 'Dispatch to another store' : orderAction.key === 'receive-transfer' ? 'Confirm transfer receipt' : orderAction.key === 'reconcile-payment' ? 'Reconcile Hubtel payment' : orderAction.key === 'fulfill-payment-review' ? 'Reserve replacement stock' : 'Check payment status' }}</h2>
      <p class="modal-context">{{ orderAction.order.id }} · {{ orderAction.order.product_name }} · {{ orderAction.order.customer_name }}<template v-if="orderAction.order.pickup_code"> · Pickup code: {{ orderAction.order.pickup_code }}</template></p>
      <div v-if="orderAction.key === 'settle'" class="settlement-fields">
        <p class="modal-context">Record the exact outstanding balance collected at the store. This changes the order to fully paid and enables fulfilment.</p>
        <label>Amount (GHS)<input v-model="settlementDraft.amount" type="number" min="0.01" step="0.01" inputmode="decimal"></label>
        <label>Payment method<input v-model="settlementDraft.payment_method" placeholder="Cash at store or mobile money"></label>
        <label>Reference (optional)<input v-model="settlementDraft.reference" placeholder="Receipt or transaction reference"></label>
        <label>Note (optional)<input v-model="settlementDraft.note" placeholder="Add an internal note"></label>
      </div>
      <div v-else-if="orderAction.key === 'dispatch'" class="dispatch-fields">
        <label>Target store<select v-model="actionInput"><option disabled value="">Select a store</option><option v-for="store in accessibleStores.filter((item) => Number(item.id) !== Number(orderAction.order.store_id))" :key="store.id" :value="String(store.id)">{{ store.name }} · {{ store.address }}</option></select></label>
        <p v-if="dispatchTargetStore" class="modal-context dispatch-stock-note">{{ dispatchTargetStock }} available at {{ dispatchTargetStore.name }}. A zero-stock destination needs an explicit in-transit transfer.</p>
        <label v-if="isGlobalAdmin && dispatchTargetStore && dispatchTargetStock < Math.max(1, Number(orderAction.order.quantity || 1))" class="checkbox-label"><input v-model="allowInTransit" type="checkbox"> Create an in-transit reservation (stock will be received at the destination later)</label>
      </div>
      <div v-else-if="orderAction.key === 'fulfill-payment-review'" class="dispatch-fields">
        <p class="modal-context">The payment was verified after the original reservation expired. Choose an active store with enough stock to create a new reservation; if no store can fulfil it, request a refund instead.</p>
        <label>Reserve at store<select v-model="actionInput"><option disabled value="">Select a store</option><option v-for="store in accessibleStores.filter((item) => item.active)" :key="store.id" :value="String(store.id)">{{ store.name }} · {{ store.address }}</option></select></label>
        <p v-if="reviewTargetStore" class="modal-context dispatch-stock-note">{{ reviewTargetStock }} available at {{ reviewTargetStore.name }}. Required: {{ Math.max(1, Number(orderAction.order.quantity || 1)) }}.</p>
        <label>Review note (optional)<input v-model="settlementDraft.note" placeholder="Customer approval or stock check note"></label>
      </div>
      <label v-else-if="['release', 'tracking', 'complete', 'receive-transfer'].includes(orderAction.key)">{{ orderAction.key === 'tracking' ? 'Tracking number' : orderAction.key === 'release' ? 'Reason' : orderAction.key === 'receive-transfer' ? 'Receipt note (optional)' : orderAction.order.fulfillment_type === 'pickup' ? 'Customer pickup code' : 'Completion note (optional)' }}<input v-model="actionInput" :inputmode="orderAction.key === 'complete' && orderAction.order.fulfillment_type === 'pickup' ? 'text' : undefined" :placeholder="orderAction.key === 'tracking' ? 'e.g. DHL-12345' : orderAction.key === 'release' ? 'Why is this reservation being released?' : orderAction.key === 'receive-transfer' ? 'Condition, quantity or receiving note' : orderAction.order.fulfillment_type === 'pickup' ? 'Enter the code shown in the customer order' : 'Add an internal note'"></label>
      <p v-if="orderAction.key === 'refund'" class="warning-copy"><AlertTriangle />This sends a refund request to the configured payment provider. Confirm the payment has been verified before proceeding.</p>
      <p v-if="orderAction.key === 'payment-status'" class="modal-context">The provider status will be checked and shown here; no local order data will be changed.</p>
      <p v-if="orderAction.key === 'reconcile-payment'" class="warning-copy"><AlertTriangle />This verifies the provider amount and currency before changing the local order. Expired reservations are sent to manual review and are not silently reallocated.</p>
      <p v-if="orderAction.key === 'fulfill-payment-review'" class="warning-copy"><AlertTriangle />Only reserve stock after confirming the customer’s payment and chosen fulfilment store. The reservation will not expire automatically.</p>
      <p v-if="actionError" class="form-error" role="alert">{{ actionError }}</p>
      <div class="modal-actions">
        <button class="secondary" :disabled="actionBusy" @click="closeOrderAction">Cancel</button>
        <button class="primary" :class="{ danger: ['refund', 'release'].includes(orderAction.key) }" :disabled="actionBusy || ['dispatch', 'fulfill-payment-review'].includes(orderAction.key) && !actionInput" @click="performOrderAction">{{ actionBusy ? 'Working…' : orderAction.key === 'payment-status' ? 'Check now' : orderAction.key === 'reconcile-payment' ? 'Verify and reconcile' : orderAction.key === 'fulfill-payment-review' ? 'Reserve stock' : orderAction.key === 'dispatch' ? 'Dispatch order' : orderAction.key === 'settle' ? 'Record payment' : 'Confirm' }}</button>
      </div>
    </section>
  </div>

      <div v-if="productModal && productDraft" class="modal-backdrop" @click.self="closeProductEditor"><section class="modal-card wide-modal"><button class="modal-close" aria-label="Close" @click="closeProductEditor"><X /></button><p class="eyebrow">Product settings</p><h2>{{ isCreatingProduct ? 'Add product' : 'Edit product' }}</h2><p class="modal-context">{{ isCreatingProduct ? 'Publish a catalog item now, then fine-tune stock per store from Inventory.' : 'Update the catalog details shown on the storefront and in stock reports.' }}</p><div class="product-edit-grid"><label>Product name<input v-model="productDraft.product_name" autocomplete="off"></label><label>Brand<input v-model="productDraft.brand" autocomplete="off"></label><label>Category<input v-model="productDraft.category" placeholder="phones, audio, cases-accessories" autocomplete="off"></label><label>Variant / specification<input v-model="productDraft.variant" autocomplete="off"></label></div><label>Image URL<input v-model="productDraft.image" placeholder="Optional image URL" autocomplete="off"></label><div class="product-edit-grid"><label>Price (GHS)<input v-model.number="productDraft.price" type="number" min="0.01" step="0.01"></label><label>Deposit rate (%)<input v-model.number="productDraft.deposit_rate" type="number" min="0.01" max="100" step="0.01"></label></div><div v-if="isCreatingProduct && stores.some((store) => store.active)" class="initial-stock-fields"><b>Initial stock (optional)</b><small>Units are added to each active store. You can adjust them later in Inventory.</small><label v-for="store in stores.filter((item) => item.active)" :key="store.id">{{ store.name }}<input v-model.number="productDraft.initial_stock[store.id]" type="number" min="0" step="1"></label></div><label class="checkbox-label"><input v-model="productDraft.active" type="checkbox"> Visible in storefront</label><p v-if="productError" class="form-error" role="alert">{{ productError }}</p><div class="modal-actions"><button class="secondary" :disabled="productBusy" @click="closeProductEditor">Cancel</button><button class="primary" :disabled="productBusy" @click="saveProduct">{{ productBusy ? 'Saving…' : isCreatingProduct ? 'Create product' : 'Save product' }}</button></div></section></div>

  <div v-if="storeModal && storeDraft" class="modal-backdrop" @click.self="closeStoreEditor"><section class="modal-card"><button class="modal-close" aria-label="Close" @click="closeStoreEditor"><X /></button><p class="eyebrow">Store directory</p><h2>{{ isCreatingStore ? 'Add store' : 'Edit store' }}</h2><p class="modal-context">Keep pickup and dispatch information accurate for customers and store teams.</p><label>Store name<input v-model="storeDraft.name" autocomplete="off"></label><label>Address<input v-model="storeDraft.address" autocomplete="street-address"></label><label>Phone<input v-model="storeDraft.phone" type="tel" autocomplete="tel"></label><label>Opening hours<input v-model="storeDraft.open_hours" placeholder="Mon-Sat 09:00-18:00"></label><label class="checkbox-label"><input v-model="storeDraft.active" type="checkbox"> Available for pickup and dispatch</label><p v-if="storeError" class="form-error" role="alert">{{ storeError }}</p><div class="modal-actions"><button class="secondary" :disabled="storeBusy" @click="closeStoreEditor">Cancel</button><button class="primary" :disabled="storeBusy" @click="saveStore">{{ storeBusy ? 'Saving…' : isCreatingStore ? 'Create store' : 'Save store' }}</button></div></section></div>

  <div v-if="staffModal && staffDraft" class="modal-backdrop" @click.self="closeStaffEditor"><section class="modal-card"><button class="modal-close" aria-label="Close" @click="closeStaffEditor"><X /></button><p class="eyebrow">Access control</p><h2>{{ isCreatingStaff ? 'Add staff account' : 'Edit staff account' }}</h2><p class="modal-context">Use a unique login and assign only the store scope this person needs.</p><div class="product-edit-grid"><label>Name<input v-model="staffDraft.name" autocomplete="name"></label><label>Username<input v-model="staffDraft.username" autocomplete="username"></label></div><label>Password<span class="field-hint">{{ isCreatingStaff ? 'At least 8 characters' : 'Leave blank to keep the current password' }}</span><input v-model="staffDraft.password" type="password" :placeholder="isCreatingStaff ? 'At least 8 characters' : 'Optional password change'" autocomplete="new-password"></label><div class="product-edit-grid"><label>Role<select v-model="staffDraft.role" @change="onStaffRoleChange"><option value="operator">Operator</option><option value="manager">Manager</option><option v-if="admin?.role === 'super_admin'" value="super_admin">Super admin</option></select></label><label>Store scope<select v-model="staffDraft.store_id" :disabled="staffDraft.role === 'super_admin'"><option value="">{{ staffDraft.role === 'super_admin' ? 'All stores' : staffDraft.role === 'manager' ? 'All stores (global scope)' : 'Select a store' }}</option><option v-for="store in stores.filter((item) => item.active || String(item.id) === String(staffDraft.store_id))" :key="store.id" :value="String(store.id)">{{ store.name }}{{ store.active ? '' : ' (paused)' }}</option></select></label></div><label class="checkbox-label"><input v-model="staffDraft.active" type="checkbox"> Account can sign in</label><p v-if="staffError" class="form-error" role="alert">{{ staffError }}</p><div class="modal-actions"><button class="secondary" :disabled="staffBusy" @click="closeStaffEditor">Cancel</button><button class="primary" :disabled="staffBusy" @click="saveStaff">{{ staffBusy ? 'Saving…' : isCreatingStaff ? 'Create account' : 'Save account' }}</button></div></section></div>

  <div v-if="customerEditor && customerDraft" class="modal-backdrop" @click.self="closeCustomerEditor"><section class="modal-card wide-modal"><button class="modal-close" aria-label="Close" @click="closeCustomerEditor"><X /></button><p class="eyebrow">Customer profile</p><h2>{{ customerEditor.name }}</h2><p class="modal-context">{{ customerEditor.phone }} · {{ customerEditor.order_count || 0 }} orders · {{ money(customerEditor.order_value) }} order value</p><div class="customer-edit-grid"><label>Name<input v-model="customerDraft.name" :disabled="!canEditCustomers" autocomplete="name"></label><label>Email<input v-model="customerDraft.email" type="email" :disabled="!canEditCustomers" autocomplete="email"></label></div><label>Default delivery / pickup address<textarea v-model="customerDraft.default_address" :disabled="!canEditCustomers" rows="2" maxlength="500"></textarea></label><label>Internal notes<textarea v-model="customerDraft.notes" :disabled="!canEditCustomers" rows="3" maxlength="2000" placeholder="Preferences, delivery notes or follow-up context"></textarea></label><label class="checkbox-label"><input v-model="customerDraft.active" type="checkbox" :disabled="!canEditCustomers"> Customer account active</label><section class="customer-history-section"><div class="subheading"><b>Order history</b><span>{{ customerOrderRows.length }} orders</span></div><div class="customer-history"><div v-for="order in customerOrderRows" :key="order.id"><span><b>{{ order.product_name }}<template v-if="order.quantity > 1"> × {{ order.quantity }}</template></b><small>{{ order.id }} · {{ dateLabel(order.created_at) }} · {{ order.store_name || 'Store' }}</small></span><span><strong>{{ money(orderTotal(order)) }}</strong><em :class="['status-pill', statusClass(order.order_status)]">{{ statusLabel(order.order_status) }}</em></span></div><div v-if="!customerOrderRows.length" class="empty-inline">No orders found for this customer in your current scope.</div></div></section><p v-if="customerError" class="form-error" role="alert">{{ customerError }}</p><div class="modal-actions"><a class="secondary" :href="`tel:${customerEditor.phone}`"><Phone />Call customer</a><button class="secondary" :disabled="customerBusy" @click="closeCustomerEditor">Close</button><button v-if="canEditCustomers" class="primary" :disabled="customerBusy" @click="saveCustomer">{{ customerBusy ? 'Saving…' : 'Save customer' }}</button></div></section></div>
</template>
