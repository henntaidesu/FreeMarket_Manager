import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { shopAccountApi } from '@/api'

const STORAGE_KEY = 'mercari.selected_account_id'

function readPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw == null || raw === '') return null
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

function writePersisted(id) {
  try {
    if (id == null || id === '') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  } catch { /* ignore quota / disabled storage */ }
}

export const useMercariAccountStore = defineStore('mercariAccount', () => {
  const selectedId = ref(readPersisted())
  const accounts = ref([])
  const loading = ref(false)
  const loaded = ref(false)

  const activeAccounts = computed(() =>
    accounts.value.filter((a) => a.status === 'active')
  )

  const selectedAccount = computed(() =>
    accounts.value.find((a) => a.id === selectedId.value) || null
  )

  const selectedAccountName = computed(() =>
    selectedAccount.value?.account_name || ''
  )

  function setSelected(id) {
    const v = id == null || id === '' ? null : Number(id)
    selectedId.value = Number.isFinite(v) && v > 0 ? v : null
    writePersisted(selectedId.value)
  }

  async function ensureLoaded(opts = {}) {
    const { force = false } = opts
    if (loaded.value && !force) return accounts.value
    if (loading.value) return accounts.value
    loading.value = true
    try {
      const res = await shopAccountApi.list({ page: 1, page_size: 200 })
      accounts.value = Array.isArray(res?.items) ? res.items : []
      loaded.value = true
      // 若 localStorage 中的 selectedId 引用了已删除/禁用的账号，则回退到首个 active
      const hit = accounts.value.find((a) => a.id === selectedId.value)
      if (!hit && activeAccounts.value.length > 0) {
        setSelected(activeAccounts.value[0].id)
      } else if (selectedId.value == null && activeAccounts.value.length > 0) {
        setSelected(activeAccounts.value[0].id)
      }
    } finally {
      loading.value = false
    }
    return accounts.value
  }

  // 跨标签同步：当其它标签写入 localStorage 时，更新本标签 selectedId
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', (e) => {
      if (e.key !== STORAGE_KEY) return
      const next = e.newValue == null || e.newValue === ''
        ? null
        : Number(e.newValue)
      const safe = Number.isFinite(next) && next > 0 ? next : null
      if (safe !== selectedId.value) selectedId.value = safe
    })
  }

  return {
    selectedId,
    accounts,
    loading,
    loaded,
    activeAccounts,
    selectedAccount,
    selectedAccountName,
    setSelected,
    ensureLoaded,
  }
})
