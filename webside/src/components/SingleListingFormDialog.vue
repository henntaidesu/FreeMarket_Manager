<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('dialogs.singleListing.title')"
    :width="isMobile ? '94vw' : '680px'"
    class="listing-dialog"
    destroy-on-close
    @update:model-value="onVisibleChange"
  >
    <el-form
      ref="listingFormRef"
      :model="form"
      :rules="listingFormRules"
      label-width="112px"
      label-position="right"
      class="listing-dialog-form"
      scroll-to-error
    >
      <el-form-item :label="t('dialogs.singleListing.linkedInventory')" prop="inventory_ids" required>
        <span v-if="form.inventory_ids?.length" class="listing-inv-count"
          >{{ t('dialogs.singleListing.selectedInventoryCount', { count: form.inventory_ids.length }) }}</span
        >
        <span v-else class="listing-inv-count listing-inv-count--warn">{{ t('dialogs.singleListing.noLinkedInventory') }}</span>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.productImage')" prop="image" class="listing-form-item--images" required>
        <div class="listing-image-box">
          <div v-if="form.listing_image_urls?.length > 1" class="listing-image-reorder-hint">
            {{ t('dialogs.singleListing.dragReorderHint') }}
          </div>
          <div class="listing-images-thumbs">
            <template v-if="form.listing_image_urls?.length">
              <div
                v-for="(imgUrl, idx) in form.listing_image_urls"
                :key="`${idx}-${imgUrl}`"
                class="listing-thumb-block"
                :class="{
                  'listing-thumb-block--draggable': form.listing_image_urls.length > 1,
                  'listing-thumb-block--drag-active': listingImageDragFrom === idx,
                  'listing-thumb-block--drop-hover':
                    listingImageDropHoverIndex === idx && listingImageDragFrom >= 0 && listingImageDragFrom !== idx
                }"
                :draggable="form.listing_image_urls.length > 1"
                :title="t('dialogs.singleListing.dragReorderTitle')"
                @dragstart="onListingImageDragStart(idx, $event)"
                @dragend="onListingImageDragEnd"
                @dragover.prevent="onListingImageDragOver(idx, $event)"
                @dragleave="onListingImageDragLeave(idx, $event)"
                @drop.prevent="onListingImageDrop(idx)"
              >
                <div class="listing-thumb-head">
                  <el-icon class="listing-thumb-drag-icon"><Rank /></el-icon>
                  <span class="listing-thumb-label">{{ t('dialogs.singleListing.imageIndex', { index: idx + 1 }) }}</span>
                </div>
                <el-image
                  :src="imgUrl"
                  fit="cover"
                  class="listing-image-preview"
                  :preview-src-list="listingImagePreviewList"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :initial-index="idx"
                />
              </div>
            </template>
            <div v-else class="listing-thumb-block">
              <span class="listing-thumb-label">{{ t('dialogs.singleListing.productImageLabel') }}</span>
              <div class="listing-image-empty">{{ t('dialogs.singleListing.noImage') }}</div>
            </div>
          </div>
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.listingTitle')" prop="listing_title" class="listing-form-item--name" required>
        <div class="listing-field-full">
          <el-input
            v-model="form.listing_title"
            class="listing-name-input"
            :placeholder="t('dialogs.singleListing.listingTitlePlaceholder')"
            clearable
          />
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.productDescription')" prop="description" class="listing-form-item--desc" required>
        <div class="listing-field-full listing-desc-with-footer">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="4"
            :maxlength="
              managementNumberLine
                ? descriptionBodyMaxLength > 0
                  ? descriptionBodyMaxLength
                  : undefined
                : 1000
            "
            show-word-limit
            :placeholder="t('dialogs.singleListing.productDescriptionPlaceholder')"
          />
          <div
            v-if="managementNumberLine"
            class="listing-mgmt-footer"
            :title="t('dialogs.singleListing.mgmtFooterTitle')"
          >
            {{ managementNumberLine }}
          </div>
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.productType')" prop="category_mapping_id" required>
        <el-cascader
          v-model="form.category_mapping_path"
          :options="categoryTypeCascaderOptions"
          :props="categoryTypeCascaderProps"
          :show-all-levels="false"
          filterable
          :placeholder="t('dialogs.singleListing.productTypePlaceholder')"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleCategoryTypeChange"
        />
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.productStatus')" prop="status" required>
        <el-select v-model="form.status" :placeholder="t('dialogs.singleListing.productStatusPlaceholder')" style="width: 100%">
          <el-option v-for="s in listingStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.listingAccount')" prop="mercari_account_id" required>
        <el-select
          v-model="form.mercari_account_id"
          :placeholder="t('dialogs.singleListing.listingAccountPlaceholder')"
          style="width: 100%"
          filterable
          :loading="mercariAccountsLoading"
        >
          <el-option
            v-for="a in mercariAccountOptionsSorted"
            :key="a.id"
            :label="mercariAccountOptionLabel(a)"
            :value="a.id"
            :disabled="a.status === 'disabled'"
          />
        </el-select>
      </el-form-item>
      <!-- 雅虎恒为出品者負担（送料込み），无此选项 -->
      <el-form-item v-if="!isYahoo" :label="t('dialogs.singleListing.shippingPayer')" prop="shipping_payer" required>
        <el-select v-model="form.shipping_payer" :placeholder="t('dialogs.singleListing.shippingPayerPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.shippingMethod')" prop="shipping_method" required>
        <el-select v-model="form.shipping_method" :placeholder="t('dialogs.singleListing.shippingMethodPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.shippingFrom')" prop="shipping_from" required>
        <el-cascader
          v-model="form.shipping_from_path"
          :options="shippingFromCascaderOptions"
          :props="shippingFromCascaderProps"
          :show-all-levels="false"
          filterable
          :placeholder="t('dialogs.singleListing.shippingFromPlaceholder')"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleShippingFromChange"
        />
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.shippingDays')" prop="shipping_days" required>
        <el-select v-model="form.shipping_days" :placeholder="t('dialogs.singleListing.shippingDaysPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <!-- 雅虎只有定价即购，没有拍卖 -->
      <el-form-item v-if="!isYahoo" :label="t('dialogs.singleListing.saleType')" prop="sale_type" required>
        <div class="listing-compact-row">
          <el-select
            v-model="form.sale_type"
            :placeholder="t('dialogs.singleListing.saleTypePlaceholder')"
            class="listing-compact-control"
            @change="onSaleTypeChange"
          >
            <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item
        v-if="form.sale_type === 'auction'"
        :label="t('dialogs.singleListing.auctionDuration')"
        prop="auction_duration"
        required
      >
        <el-select v-model="form.auction_duration" :placeholder="t('dialogs.singleListing.auctionDurationPlaceholder')" style="width: 100%">
          <el-option :label="t('dialogs.singleListing.auctionDurationNormal')" value="normal" />
          <el-option :label="t('dialogs.singleListing.auctionDuration3Hours')" value="3hours" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.singleListing.unitPrice')" prop="price" class="listing-form-item--price" required>
        <div class="listing-compact-row">
          <el-input
            v-model="listingPriceEdit"
            :placeholder="t('dialogs.singleListing.unitPricePlaceholder')"
            class="listing-price-input listing-compact-control"
            inputmode="numeric"
            @blur="applyListingPriceToForm"
          />
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="submitStub">{{ t('common.submit') }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { Rank } from '@element-plus/icons-vue'
import { shopAccountApi } from '@/api/index.js'
import { encodeMgmtIds, stripTrailingMgmtBlock } from '@/utils/mgmtIdCipher.js'
import { useListingPlatform } from '@/composables/useListingPlatform.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  categoryMappings: { type: Array, default: () => [] },
  initialData: { type: Object, default: null },
  /** 系统页保存的出品默认值（与表单字段对应）；库存 seed 优先 */
  listingDefaults: { type: Object, default: null },
  isMobile: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const listingFormRef = ref()
const form = ref(getDefaultForm())
/** 商品单价：纯文本整数，blur / 提交前写回 form.price */
const listingPriceEdit = ref('0')

const listingFormRules = computed(() => ({
  inventory_ids: [
    {
      type: 'array',
      required: true,
      min: 1,
      message: t('dialogs.singleListing.ruleInventoryRequired'),
      trigger: 'change'
    }
  ],
  image: [
    {
      validator: (_, val, cb) => {
        const urls = form.value.listing_image_urls || []
        if (urls.length > 0 && String(urls[0] ?? '').trim()) {
          cb()
          return
        }
        if (String(val ?? '').trim()) {
          cb()
          return
        }
        cb(new Error(t('dialogs.singleListing.ruleImageRequired')))
      },
      trigger: 'change'
    }
  ],
  listing_title: [
    {
      validator: (_, val, cb) => {
        if (!String(val ?? '').trim()) cb(new Error(t('dialogs.singleListing.ruleTitleRequired')))
        else cb()
      },
      trigger: 'blur'
    }
  ],
  price: [
    {
      validator: (_, val, cb) => {
        const n = Number(val)
        if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) {
          cb(new Error(t('dialogs.singleListing.rulePriceRequired')))
          return
        }
        cb()
      },
      trigger: ['blur', 'change']
    }
  ],
  auction_duration: [
    {
      validator: (_, val, cb) => {
        if (form.value.sale_type !== 'auction') {
          cb()
          return
        }
        if (val !== 'normal' && val !== '3hours') {
          cb(new Error(t('dialogs.singleListing.ruleAuctionDurationRequired')))
          return
        }
        cb()
      },
      trigger: 'change'
    }
  ],
  description: [
    {
      validator: (_, val, cb) => {
        if (!String(val ?? '').trim()) cb(new Error(t('dialogs.singleListing.ruleDescriptionRequired')))
        else cb()
      },
      trigger: 'blur'
    }
  ],
  category_mapping_id: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error(t('dialogs.singleListing.ruleProductTypeRequired')))
        else cb()
      },
      trigger: 'change'
    }
  ],
  status: [{ required: true, message: t('dialogs.singleListing.ruleStatusRequired'), trigger: 'change' }],
  mercari_account_id: [
    {
      required: true,
      message: t('dialogs.singleListing.ruleAccountRequired'),
      trigger: 'change'
    }
  ],
  shipping_payer: [{ required: true, message: t('dialogs.singleListing.ruleShippingPayerRequired'), trigger: 'change' }],
  shipping_method: [{ required: true, message: t('dialogs.singleListing.ruleShippingMethodRequired'), trigger: 'change' }],
  shipping_from: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error(t('dialogs.singleListing.ruleShippingFromRequired')))
        else cb()
      },
      trigger: 'change'
    }
  ],
  shipping_days: [{ required: true, message: t('dialogs.singleListing.ruleShippingDaysRequired'), trigger: 'change' }],
  sale_type: [{ required: true, message: t('dialogs.singleListing.ruleSaleTypeRequired'), trigger: 'change' }]
}))

function onSaleTypeChange() {
  if (form.value.sale_type !== 'auction') {
    form.value.auction_duration = 'normal'
    nextTick(() => {
      listingFormRef.value?.clearValidate?.(['auction_duration'])
    })
  }
}

function syncListingPriceFromForm() {
  listingPriceEdit.value = String(Math.round(Number(form.value.price ?? 0)))
}

function applyListingPriceToForm() {
  const raw = String(listingPriceEdit.value ?? '').trim()
  const n = parseInt(raw, 10)
  const v = Number.isNaN(n) ? 0 : Math.max(0, Math.min(999999999, n))
  form.value.price = v
  listingPriceEdit.value = String(v)
}

const MAX_LISTING_DIALOG_IMAGES = 20

function normalizeListingImageUrlList(arr) {
  if (!Array.isArray(arr)) return []
  return arr
    .map((u) => String(u || '').trim())
    .filter(Boolean)
    .slice(0, MAX_LISTING_DIALOG_IMAGES)
}

const listingImagePreviewList = computed(() => {
  const from = normalizeListingImageUrlList(form.value.listing_image_urls)
  if (from.length) return from
  return [form.value.image, form.value.image_back].filter((u) => u && String(u).trim())
})

/** 商品图拖拽排序（HTML5 DnD，拖动手柄行触发） */
const listingImageDragFrom = ref(-1)
const listingImageDropHoverIndex = ref(-1)

function onListingImageDragStart(idx, e) {
  if (!form.value.listing_image_urls || form.value.listing_image_urls.length < 2) {
    e.preventDefault()
    return
  }
  listingImageDragFrom.value = idx
  try {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(idx))
  } catch (_) {
    /* ignore */
  }
}

function onListingImageDragEnd() {
  listingImageDragFrom.value = -1
  listingImageDropHoverIndex.value = -1
}

function onListingImageDragOver(idx, e) {
  if (listingImageDragFrom.value < 0) return
  e.dataTransfer.dropEffect = 'move'
  listingImageDropHoverIndex.value = idx
}

function onListingImageDragLeave(idx, e) {
  if (listingImageDropHoverIndex.value !== idx) return
  const next = e.relatedTarget
  if (next && typeof next.closest === 'function' && e.currentTarget?.contains(next)) return
  listingImageDropHoverIndex.value = -1
}

function reorderListingImageUrls(from, to) {
  const raw = normalizeListingImageUrlList(form.value.listing_image_urls)
  if (raw.length < 2 || from === to || from < 0 || to < 0 || from >= raw.length || to >= raw.length) return
  const arr = [...raw]
  const [item] = arr.splice(from, 1)
  arr.splice(to, 0, item)
  form.value.listing_image_urls = arr
  form.value.image = arr[0] || ''
  form.value.image_back = arr[1] || ''
  nextTick(() => listingFormRef.value?.validateField?.('image'))
}

function onListingImageDrop(to) {
  const from = listingImageDragFrom.value
  listingImageDragFrom.value = -1
  listingImageDropHoverIndex.value = -1
  if (from < 0 || from === to) return
  reorderListingImageUrls(from, to)
}

/** 所选库存 id 的末行暗号（-=~<> 五进制），保存时拼在说明最底部，无「管理番号：」前缀 */
const managementNumberLine = computed(() => {
  const ids = (form.value.inventory_ids || [])
    .map((id) => Number(id))
    .filter((x) => Number.isFinite(x) && x > 0)
  if (!ids.length) return ''
  return encodeMgmtIds(ids)
})

/** 可编辑说明字数上限：总长 1000，为底部固定行预留字符 */
const descriptionBodyMaxLength = computed(() => {
  const foot = managementNumberLine.value
  if (!foot) return 1000
  const reserved = foot.length + 2
  return Math.max(0, 1000 - reserved)
})
const mercariAccountOptions = ref([])
const mercariAccountsLoading = ref(false)

const categoryTypeCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

/** 发货地两级级联：一级=日本地域，二级=都道府県（叶子值=AREA:<id>） */
const shippingFromCascaderOptions = computed(() => {
  return JP_REGION_OPTIONS.map((r) => ({
    value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
    label: r.label,
    children: r.areaIds
      .map((aid) => {
        const a = MERCARI_AREAS.find((x) => x.id === aid)
        return a
          ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name }
          : null
      })
      .filter(Boolean)
  }))
})

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [
    `${SHIPPING_FROM_REGION_PREFIX}${regionId}`,
    `${SHIPPING_FROM_AREA_PREFIX}${areaId}`
  ]
}

function ensureNode(children, value, label) {
  let node = children.find((item) => item.value === value)
  if (!node) {
    node = { value, label, children: [] }
    children.push(node)
  }
  return node
}

const categoryTypeTreeMeta = computed(() => {
  const roots = []
  const idToPath = new Map()
  for (const m of (props.categoryMappings || [])) {
    const mappingId = String(m?.mapping_id ?? '').trim()
    const typeName = String(m?.product_type ?? '').trim()
    if (!mappingId || !typeName) continue
    const l1 = String(m?.category_level1 ?? '').trim() || t('dialogs.singleListing.uncategorized')
    const l2 = String(m?.category_level2 ?? '').trim()
    const l3 = String(m?.category_level3 ?? '').trim()
    const l1Val = `L1:${l1}`
    const l1Node = ensureNode(roots, l1Val, l1)
    const l1Path = [l1Val]

    if (!l2) {
      l1Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
      idToPath.set(mappingId, [...l1Path, `PT:${mappingId}`])
      continue
    }
    const l2Val = `L2:${l1}__${l2}`
    const l2Node = ensureNode(l1Node.children, l2Val, l2)
    const l2Path = [...l1Path, l2Val]
    if (!l3) {
      l2Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
      idToPath.set(mappingId, [...l2Path, `PT:${mappingId}`])
      continue
    }
    const l3Val = `L3:${l1}__${l2}__${l3}`
    const l3Node = ensureNode(l2Node.children, l3Val, l3)
    const l3Path = [...l2Path, l3Val]
    l3Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
    idToPath.set(mappingId, [...l3Path, `PT:${mappingId}`])
  }
  return { roots, idToPath }
})

const categoryTypeCascaderOptions = computed(() => categoryTypeTreeMeta.value.roots)

const listingStatusOptions = computed(() => [
  { label: t('dialogs.singleListing.statusNewUnused'), value: 'new_unused' },
  { label: t('dialogs.singleListing.statusAlmostUnused'), value: 'almost_unused' },
  { label: t('dialogs.singleListing.statusGood'), value: 'good' },
  { label: t('dialogs.singleListing.statusFair'), value: 'fair' },
  { label: t('dialogs.singleListing.statusUsed'), value: 'used' }
])
const shippingPayerOptions = computed(() => [
  { label: t('dialogs.singleListing.shippingPayerSeller'), value: 'seller' },
  { label: t('dialogs.singleListing.shippingPayerBuyer'), value: 'buyer' }
])
// 雅虎账号：只有おてがる配送两家承运商，且没有快递费负担/販売形式（见 useListingPlatform）
const { isYahoo, yahooShippingMethodOptions } = useListingPlatform(mercariAccountOptions, form)
const shippingMethodOptions = computed(() => isYahoo.value
  ? yahooShippingMethodOptions.value
  : [
      { label: t('dialogs.singleListing.shippingMethodUndecided'), value: 'undecided' },
      { label: t('dialogs.singleListing.shippingMethodRakuraku'), value: 'rakuraku' },
      { label: t('dialogs.singleListing.shippingMethodYuuyu'), value: 'yuuyu' },
      { label: t('dialogs.singleListing.shippingMethodRegularMail'), value: 'regular_mail' }
    ])
const shippingDaysOptions = computed(() => [
  { label: t('dialogs.singleListing.shippingDays1_2'), value: '1_2_days' },
  { label: t('dialogs.singleListing.shippingDays2_3'), value: '2_3_days' },
  { label: t('dialogs.singleListing.shippingDays4_7'), value: '4_7_days' }
])
const saleTypeOptions = computed(() => [
  { label: t('dialogs.singleListing.saleTypeInstantBuy'), value: 'instant_buy' },
  { label: t('dialogs.singleListing.saleTypeAuction'), value: 'auction' }
])

// 停用账号(status==='disabled')底置，其余保持原有顺序（sort 稳定，组内顺序不变）
const mercariAccountOptionsSorted = computed(() => {
  const list = Array.isArray(mercariAccountOptions.value) ? mercariAccountOptions.value : []
  return [...list].sort(
    (a, b) => (a?.status === 'disabled' ? 1 : 0) - (b?.status === 'disabled' ? 1 : 0)
  )
})

function mercariAccountOptionLabel(a) {
  const name = (a?.account_name || '').trim() || `ID ${a?.id}`
  const sid = String(a?.seller_id || '').trim()
  const tail = sid ? ` · ${t('dialogs.singleListing.sellerLabel')} ${sid}` : ''
  const inactive = a?.status === 'disabled' ? t('dialogs.singleListing.inactiveSuffix') : ''
  return `${name}${tail}${inactive}`
}

async function fetchMercariAccounts() {
  mercariAccountsLoading.value = true
  try {
    const res = await shopAccountApi.list({ page: 1, page_size: 500 })
    mercariAccountOptions.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    mercariAccountOptions.value = []
  } finally {
    mercariAccountsLoading.value = false
  }
}

function pickListingStr(seedVal, cfgVal, fallback) {
  const a = seedVal != null && String(seedVal).trim() ? String(seedVal).trim() : ''
  if (a) return a
  const b = cfgVal != null && String(cfgVal).trim() ? String(cfgVal).trim() : ''
  if (b) return b
  return fallback
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    fetchMercariAccounts()
    const seed = props.initialData || {}
    const cfg = props.listingDefaults || {}
    const seedMappingId = seed.category_mapping_id != null ? String(seed.category_mapping_id) : null
    const seedPath = seedMappingId
      ? (categoryTypeTreeMeta.value.idToPath.get(seedMappingId) || [])
      : []
    const areaFromSeed = normalizeShippingFromSeed(seed.shipping_from)
    const areaFromCfg = normalizeShippingFromSeed(cfg.shipping_from_area_id)
    const areaId = areaFromSeed || areaFromCfg || ''
    const accId = seed.mercari_account_id != null ? Number(seed.mercari_account_id) : null
    const cfgMid = cfg.mercari_account_id != null ? Number(cfg.mercari_account_id) : null
    const seedPrice = seed.price != null ? Math.round(Number(seed.price)) : 0
    const priceVal = Number.isFinite(seedPrice) && seedPrice >= 0 ? seedPrice : 0
    const seedUrls = normalizeListingImageUrlList(seed.listing_image_urls)
    const fallbackPair = [seed.image, seed.image_back]
      .map((u) => String(u || '').trim())
      .filter(Boolean)
    const listingUrls = seedUrls.length ? seedUrls : normalizeListingImageUrlList(fallbackPair)
    form.value = {
      ...getDefaultForm(),
      image: listingUrls[0] || '',
      image_back: listingUrls[1] || '',
      listing_image_urls: listingUrls,
      listing_title: seed.listing_title || seed.name || '',
      category_mapping_id: seedMappingId,
      category_mapping_path: seedPath,
      description: stripTrailingMgmtBlock(seed.description || ''),
      price: priceVal,
      shipping_from: areaId,
      shipping_from_path: buildShippingFromPath(areaId),
      inventory_ids: Array.isArray(seed.inventory_ids)
        ? seed.inventory_ids.map((x) => Number(x)).filter((x) => Number.isFinite(x))
        : [],
      mercari_account_id:
        Number.isFinite(accId) && accId > 0
          ? accId
          : Number.isFinite(cfgMid) && cfgMid > 0
            ? cfgMid
            : null,
      shipping_payer: pickListingStr(seed.shipping_payer, cfg.shipping_payer, 'seller'),
      shipping_method: pickListingStr(seed.shipping_method, cfg.shipping_method, 'undecided'),
      shipping_days: pickListingStr(seed.shipping_days, cfg.shipping_days, '2_3_days')
    }
    syncListingPriceFromForm()
  }
)

function getDefaultForm() {
  return {
    /** mercari_accounts.id，用于指定以哪一账号出品 */
    mercari_account_id: null,
    /** 与库存一致的全部商品图 URL，提交自动化时写入 image_urls */
    listing_image_urls: [],
    image: '',
    image_back: '',
    listing_title: '',
    category_mapping_id: null,
    category_mapping_path: [],
    status: 'new_unused',
    description: '',
    shipping_payer: 'seller',
    shipping_method: 'undecided',
    /** Mercari areas[].id，与煤炉 API 发货地一致 */
    shipping_from: '',
    /** el-cascader 的路径值：[REGION:xxx, AREA:xxx] */
    shipping_from_path: [],
    shipping_days: '2_3_days',
    sale_type: 'instant_buy',
    auction_duration: 'normal',
    inventory_ids: [],
    price: 0
  }
}

function handleCategoryTypeChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('PT:')) {
    form.value.category_mapping_id = null
    return
  }
  form.value.category_mapping_id = String(picked).slice(3)
}

function handleShippingFromChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    form.value.shipping_from = ''
    return
  }
  form.value.shipping_from = String(picked).slice(SHIPPING_FROM_AREA_PREFIX.length)
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

async function submitStub() {
  applyListingPriceToForm()
  const elForm = listingFormRef.value
  if (!elForm) return
  try {
    await elForm.validate()
  } catch {
    return
  }
  const foot = managementNumberLine.value
  let body = String(form.value.description || '').trimEnd()
  if (foot) {
    const maxBody = Math.max(0, 1000 - foot.length - 2)
    if (body.length > maxBody) body = body.slice(0, maxBody)
  }
  const fullDescription = foot ? (body ? `${body}\n\n${foot}` : foot) : body
  emit('saved', { ...form.value, description: fullDescription })
  onVisibleChange(false)
}
</script>

<style scoped>
.listing-dialog-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.listing-form-item--images :deep(.el-form-item__content) {
  line-height: normal;
}
/** 商品名 / 商品说明 / 单价：右侧内容区与内部输入同宽 */
.listing-form-item--name :deep(.el-form-item__content),
.listing-form-item--desc :deep(.el-form-item__content),
.listing-form-item--price :deep(.el-form-item__content) {
  flex: 1 1 auto;
  min-width: 0;
  max-width: none;
}
.listing-field-full {
  display: block;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.listing-field-full :deep(.el-input) {
  width: 100% !important;
  max-width: none !important;
}
.listing-field-full :deep(.el-input__wrapper) {
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box;
}
.listing-field-full :deep(.el-textarea) {
  width: 100% !important;
  max-width: none !important;
}
.listing-field-full :deep(.el-textarea__inner) {
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box;
}
.listing-desc-with-footer :deep(.el-textarea__inner) {
  border-radius: 4px 4px 0 0;
}
.listing-mgmt-footer {
  margin-top: -1px;
  padding: 8px 11px;
  font-size: 13px;
  color: #a8b4ce;
  background: rgba(26, 35, 54, 0.95);
  border: 1px solid var(--el-border-color);
  border-top: none;
  border-radius: 0 0 4px 4px;
  line-height: 1.5;
}
.listing-image-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
}
.listing-image-reorder-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-bottom: 4px;
}
.listing-thumb-block--draggable {
  cursor: grab;
}
.listing-thumb-block--draggable:active {
  cursor: grabbing;
}
.listing-thumb-block--drag-active {
  opacity: 0.55;
}
.listing-thumb-block--drop-hover {
  outline: 2px dashed var(--el-color-primary);
  outline-offset: 3px;
  border-radius: 8px;
}
.listing-thumb-head {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 6px;
}
.listing-thumb-drag-icon {
  font-size: 14px;
  color: #909399;
}
.listing-thumb-block--draggable :deep(.el-image img),
.listing-thumb-block--draggable :deep(.el-image__inner) {
  -webkit-user-drag: none;
  user-select: none;
}
.listing-images-thumbs {
  display: flex;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 14px;
  flex-shrink: 0;
}
.listing-thumb-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.listing-thumb-label {
  font-size: 12px;
  color: #909399;
  line-height: 1;
}
.listing-image-preview {
  width: 96px;
  height: 96px;
  border-radius: 6px;
}
.listing-image-empty {
  width: 96px;
  height: 96px;
  border: 1px dashed #5a6b88;
  border-radius: 6px;
  color: #8ea0bf;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.listing-compact-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 220px;
  max-width: 100%;
}
.listing-compact-control {
  width: 100%;
}
.listing-auction-duration-control {
  width: 110px;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.listing-inv-count {
  font-size: 13px;
  color: #606266;
}
.listing-inv-count--warn {
  color: var(--el-color-danger);
}
/** 商品名单行输入不展示字数统计（避免与 maxlength 等组合时出现计数） */
.listing-field-full .listing-name-input :deep(.el-input__count) {
  display: none;
}
.listing-field-full .listing-price-input :deep(.el-input__count) {
  display: none;
}
</style>
