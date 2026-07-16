<template>
  <div>
    <!-- DeepSeek AI 配置 -->
    <el-card shadow="never" class="sysconf-card" v-loading="loading">
      <template #header>
        <div class="card-title">{{ t('systemConfig.deepseekSection') }}</div>
      </template>
      <el-form label-width="120px" class="sysconf-form" @submit.prevent>
        <el-form-item :label="t('systemConfig.apiKey')">
          <el-input v-model="form.api_key" type="password" show-password clearable />
        </el-form-item>
        <el-form-item :label="t('systemConfig.model')">
          <el-input v-model="form.model" clearable />
        </el-form-item>
        <el-form-item :label="t('systemConfig.baseUrl')">
          <el-input v-model="form.base_url" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">
            {{ t('systemConfig.save') }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 出品默认值 -->
    <el-card shadow="never" class="sysconf-card listing-def-card" v-loading="listingDefLoading">
      <template #header>
        <div class="card-title">{{ t('system.listingDefaults') }}</div>
      </template>
      <el-form label-width="132px" class="listing-def-form">
        <el-form-item :label="t('system.defaultShippingFrom')">
          <el-cascader
            v-model="listingDefForm.shipping_from_path"
            :options="shippingFromCascaderOptions"
            :props="shippingFromCascaderProps"
            :show-all-levels="false"
            filterable
            clearable
            :placeholder="t('system.shippingFromPlaceholder')"
            style="width: 100%; max-width: 520px"
            popper-class="product-type-cascader-popper"
            @change="onShippingFromChange"
          />
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingMethod')">
          <el-select
            v-model="listingDefForm.shipping_method"
            clearable
            :placeholder="t('system.shippingMethodPlaceholder')"
            style="width: 100%; max-width: 360px"
          >
            <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingPayer')">
          <el-select v-model="listingDefForm.shipping_payer" clearable style="width: 100%; max-width: 360px">
            <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingDays')">
          <el-select v-model="listingDefForm.shipping_days" clearable style="width: 100%; max-width: 280px">
            <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultCondition')">
          <el-select v-model="listingDefForm.condition" clearable :placeholder="t('system.autoListingDefaultPlaceholder')" style="width: 100%; max-width: 280px">
            <el-option v-for="s in conditionOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultSaleType')">
          <el-select v-model="listingDefForm.sale_type" clearable :placeholder="t('system.autoListingDefaultPlaceholder')" style="width: 100%; max-width: 280px">
            <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultListingAccount')">
          <el-select
            v-model="listingDefForm.mercari_account_id"
            clearable
            filterable
            :placeholder="t('system.listingAccountPlaceholder')"
            style="width: 100%; max-width: 420px"
            :loading="mercariAccountsLoading"
          >
            <el-option
              v-for="a in mercariAccountOptions"
              :key="a.id"
              :label="mercariAccountOptionLabel(a)"
              :value="a.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="listingDefSaving" @click="saveListingDefaults">{{ t('system.saveListingDefaults') }}</el-button>
          <el-button :loading="listingDefLoading" @click="loadListingDefaults">{{ t('system.reload') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { configApi, mercariAccountApi } from '@/api/index.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const { t } = useI18n()

// ===== DeepSeek AI 配置 =====
const loading = ref(false)
const saving = ref(false)
const form = reactive({
  api_key: '',
  model: '',
  base_url: '',
})

async function load() {
  loading.value = true
  try {
    const res = await configApi.getDeepseekConfig()
    form.api_key = res?.api_key || ''
    form.model = res?.model || ''
    form.base_url = res?.base_url || ''
  } catch {
    ElMessage.error(t('systemConfig.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await configApi.putDeepseekConfig({
      api_key: form.api_key,
      model: form.model,
      base_url: form.base_url,
    })
    form.api_key = res?.api_key || ''
    form.model = res?.model || ''
    form.base_url = res?.base_url || ''
    ElMessage.success(t('systemConfig.saveSuccess'))
  } finally {
    saving.value = false
  }
}

// ===== 出品默认值 =====
const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false
}

const shippingFromCascaderOptions = computed(() =>
  JP_REGION_OPTIONS.map((r) => ({
    value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
    label: r.label,
    children: r.areaIds
      .map((aid) => {
        const a = MERCARI_AREAS.find((x) => x.id === aid)
        return a ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name } : null
      })
      .filter(Boolean)
  }))
)

const shippingPayerOptions = computed(() => [
  { label: t('system.shippingPayerSeller'), value: 'seller' },
  { label: t('system.shippingPayerBuyer'), value: 'buyer' }
])
const shippingMethodOptions = computed(() => [
  { label: t('system.shippingMethodUndecided'), value: 'undecided' },
  { label: 'らくらくメルカリ便', value: 'rakuraku' },
  { label: 'ゆうゆうメルカリ便', value: 'yuuyu' },
  { label: t('system.shippingMethodRegularMail'), value: 'regular_mail' }
])
const shippingDaysOptions = computed(() => [
  { label: t('system.shippingDays12'), value: '1_2_days' },
  { label: t('system.shippingDays23'), value: '2_3_days' },
  { label: t('system.shippingDays47'), value: '4_7_days' }
])
// 自动出品兜底默认：商品状态 / 售卖类型
const conditionOptions = computed(() => [
  { label: t('system.conditionNewUnused'), value: 'new_unused' },
  { label: t('system.conditionAlmostUnused'), value: 'almost_unused' },
  { label: t('system.conditionGood'), value: 'good' },
  { label: t('system.conditionFair'), value: 'fair' },
  { label: t('system.conditionUsed'), value: 'used' }
])
const saleTypeOptions = computed(() => [
  { label: t('system.saleTypeInstantBuy'), value: 'instant_buy' },
  { label: t('system.saleTypeAuction'), value: 'auction' }
])

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [`${SHIPPING_FROM_REGION_PREFIX}${regionId}`, `${SHIPPING_FROM_AREA_PREFIX}${areaId}`]
}

function mercariAccountOptionLabel(a) {
  const name = (a?.account_name || '').trim() || `ID ${a?.id}`
  const sid = String(a?.seller_id || '').trim()
  const tail = sid ? ` · ${t('system.seller')} ${sid}` : ''
  const inactive = a?.status === 'disabled' ? `（${t('system.inactive')}）` : ''
  return `${name}${tail}${inactive}`
}

const listingDefForm = reactive({
  shipping_from_path: [],
  shipping_method: null,
  shipping_payer: null,
  shipping_days: null,
  mercari_account_id: null,
  // 自动出品兜底默认（库存不存这两个字段）
  condition: null,
  sale_type: null
})

const listingDefLoading = ref(false)
const listingDefSaving = ref(false)
const mercariAccountOptions = ref([])
const mercariAccountsLoading = ref(false)

function onShippingFromChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    listingDefForm.shipping_from_path = []
  }
}

async function fetchMercariAccounts() {
  mercariAccountsLoading.value = true
  try {
    const res = await mercariAccountApi.list({ page: 1, page_size: 500 })
    mercariAccountOptions.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    mercariAccountOptions.value = []
  } finally {
    mercariAccountsLoading.value = false
  }
}

function pathToAreaId(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) return null
  const id = String(picked).slice(SHIPPING_FROM_AREA_PREFIX.length).trim()
  return id || null
}

async function loadListingDefaults() {
  listingDefLoading.value = true
  try {
    await fetchMercariAccounts()
    const d = await configApi.getListingDefaults()
    const area = normalizeShippingFromSeed(d?.shipping_from_area_id)
    listingDefForm.shipping_from_path = buildShippingFromPath(area)
    listingDefForm.shipping_method = d?.shipping_method ?? null
    listingDefForm.shipping_payer = d?.shipping_payer ?? null
    listingDefForm.shipping_days = d?.shipping_days ?? null
    listingDefForm.condition = d?.condition ?? null
    listingDefForm.sale_type = d?.sale_type ?? null
    listingDefForm.mercari_account_id =
      d?.mercari_account_id != null && Number.isFinite(Number(d.mercari_account_id)) && Number(d.mercari_account_id) > 0
        ? Number(d.mercari_account_id)
        : null
  } catch {
    /* 拦截器已提示 */
  } finally {
    listingDefLoading.value = false
  }
}

async function saveListingDefaults() {
  listingDefSaving.value = true
  try {
    const areaId = pathToAreaId(listingDefForm.shipping_from_path)
    await configApi.putListingDefaults({
      shipping_from_area_id: areaId,
      shipping_method: listingDefForm.shipping_method,
      shipping_payer: listingDefForm.shipping_payer,
      shipping_days: listingDefForm.shipping_days,
      condition: listingDefForm.condition,
      sale_type: listingDefForm.sale_type,
      mercari_account_id: listingDefForm.mercari_account_id
    })
    ElMessage.success(t('system.listingDefaultsSaved'))
    await loadListingDefaults()
  } catch {
    /* 拦截器 */
  } finally {
    listingDefSaving.value = false
  }
}

onMounted(() => {
  load()
  loadListingDefaults()
})
</script>

<style scoped>
.sysconf-card {
  max-width: 720px;
}
.listing-def-card {
  margin-top: 16px;
}
.card-title {
  font-weight: 600;
}
.sysconf-form {
  max-width: 640px;
}
</style>
