<script setup>
import { onMounted, ref } from 'vue'

const props = defineProps({ token: String })
const emit = defineEmits(['unauthorized'])
const items = ref([])
const loading = ref(true)
const loadError = ref('')
const saved = ref('')
const saveError = ref(false)
const saving = ref({})

async function responseData(response) {
  const type = response.headers.get('content-type') || ''
  return type.includes('application/json') ? response.json() : response.text()
}

function errorMessage(data, fallback) {
  if (typeof data === 'string') return data || fallback
  return data?.detail || data?.message || fallback
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/admin/banners', { headers: { Authorization: `Bearer ${props.token}` } })
    const data = await responseData(response)
    if (response.status === 401) {
      emit('unauthorized')
      return
    }
    if (!response.ok) throw new Error(errorMessage(data, `Unable to load banners (${response.status})`))
    items.value = Array.isArray(data) ? data : []
  } catch (error) {
    loadError.value = error.message || 'Unable to load banners.'
  } finally {
    loading.value = false
  }
}

async function save(item) {
  saving.value[item.id] = true
  saved.value = ''
  saveError.value = false
  try {
    const response = await fetch(`/api/admin/banners/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${props.token}` },
      body: JSON.stringify(item),
    })
    const data = await responseData(response)
    if (response.status === 401) {
      emit('unauthorized')
      return
    }
    if (!response.ok) throw new Error(errorMessage(data, `Save failed (${response.status})`))
    Object.assign(item, data)
    saved.value = `Banner ${item.id} saved`
  } catch (error) {
    saveError.value = true
    saved.value = error.message || 'Save failed'
  } finally {
    saving.value[item.id] = false
    window.setTimeout(() => { saved.value = '' }, 2400)
  }
}

onMounted(load)
</script>

<template>
  <section class="banner-admin">
    <div v-if="saved" :class="['saved', { error: saveError }]" role="status" aria-live="polite">{{ saved }}</div>
    <div v-if="loading" class="banner-state">Loading banners…</div>
    <div v-else-if="loadError" class="banner-state error"><span>{{ loadError }}</span><button @click="load">Retry</button></div>
    <template v-else>
      <article v-for="item in items" :key="item.id">
        <div class="banner-preview"><p>Slide {{ item.sort_order }}</p><h2>{{ item.title }}</h2><span>{{ item.subtitle }}</span></div>
        <div class="banner-form"><label>Title<input v-model="item.title"></label><label>Supporting text<textarea v-model="item.subtitle"></textarea></label><label>Image URL<input v-model="item.image" placeholder="Optional image URL"></label><div><label>Order<input v-model.number="item.sort_order" type="number"></label><label class="toggle"><input v-model="item.active" type="checkbox"> Active</label></div><button :disabled="saving[item.id]" @click="save(item)">{{ saving[item.id] ? 'Saving…' : 'Save changes' }}</button></div>
      </article>
    </template>
    <div v-if="!loading && !loadError && !items.length" class="banner-state">No banners are configured.</div>
  </section>
</template>

<style scoped>.banner-admin{display:grid;gap:18px}.banner-admin article{display:grid;grid-template-columns:1fr 1fr;background:#fff;border:1px solid #ddd}.banner-preview{background:#181818;color:#fff;padding:28px;min-height:210px}.banner-preview p{color:#e23a2e;text-transform:uppercase;font-size:10px;font-weight:700}.banner-preview h2{font:800 28px Manrope;margin:20px 0 10px}.banner-preview span{color:#bbb}.banner-form{padding:22px}.banner-form label{display:block;font-size:11px;font-weight:700;margin-bottom:11px}.banner-form input,.banner-form textarea{display:block;width:100%;padding:10px;border:1px solid #ddd;margin-top:5px}.banner-form textarea{min-height:68px}.banner-form>div{display:grid;grid-template-columns:100px 1fr;gap:20px}.toggle{display:flex!important;align-items:center;gap:8px;margin-top:20px}.toggle input{width:auto;margin:0}.banner-form button{border:0;background:#e23a2e;color:#fff;padding:11px 16px}.banner-form button:disabled{cursor:not-allowed;opacity:.6}.saved{position:fixed;right:25px;top:20px;background:#287a3c;color:#fff;padding:10px 14px;z-index:10}.saved.error{background:#a52e25}.banner-state{display:flex;align-items:center;justify-content:center;gap:12px;min-height:180px;padding:28px;background:#fff;border:1px solid #ddd;color:#777;font-size:13px}.banner-state.error{color:#a52e25;background:#fff7f5}.banner-state button{border:1px solid #d7d7d1;background:#fff;padding:8px 11px;border-radius:5px}@media(max-width:800px){.banner-admin article{grid-template-columns:1fr}.banner-preview{min-height:160px}.saved{right:14px;top:14px}}</style>
