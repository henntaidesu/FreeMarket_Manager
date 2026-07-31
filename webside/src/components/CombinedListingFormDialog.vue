<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('dialogs.combinedListing.title')"
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
      <el-form-item :label="t('dialogs.combinedListing.linkedInventory')" prop="inventory_ids" required>
        <span v-if="form.inventory_ids?.length" class="listing-inv-count"
          >{{ t('dialogs.combinedListing.selectedInventoryCount', { count: form.inventory_ids.length }) }}</span
        >
        <span v-else class="listing-inv-count listing-inv-count--warn">{{ t('dialogs.combinedListing.noLinkedInventory') }}</span>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.productImages')" prop="combined_listing_images" class="listing-form-item--images" required>
        <div class="listing-field-full listing-combined-images-wrap">
          <div v-if="!combinedPreviewImages.length" class="listing-combined-empty">{{ t('dialogs.combinedListing.noImageData') }}</div>
          <div v-else class="listing-combined-gallery">
            <div
              v-for="(block, idx) in combinedPreviewImages"
              :key="`${block.inventory_id ?? idx}-${idx}`"
              class="listing-combined-card"
            >
              <div class="listing-combined-card-title">{{ t('dialogs.combinedListing.itemCardTitle', { index: idx + 1, mgmtId: block.inventory_id ?? '—' }) }}</div>
              <div class="listing-images-thumbs listing-images-thumbs--combined">
                <div class="listing-thumb-block">
                  <span class="listing-thumb-label">{{ t('dialogs.combinedListing.front') }}</span>
                  <el-image
                    v-if="block.front"
                    :src="block.front"
                    fit="cover"
                    class="listing-image-preview listing-image-preview--combined"
                    :preview-src-list="pairPreviewList(block)"
                    :hide-on-click-modal="true"
                    :preview-teleported="true"
                    :initial-index="0"
                  />
                  <div v-else class="listing-image-empty listing-image-empty--combined">{{ t('dialogs.combinedListing.none') }}</div>
                </div>
                <div v-if="block.back" class="listing-thumb-block">
                  <span class="listing-thumb-label">{{ t('dialogs.combinedListing.back') }}</span>
                  <el-image
                    :src="block.back"
                    fit="cover"
                    class="listing-image-preview listing-image-preview--combined"
                    :preview-src-list="pairPreviewList(block)"
                    :hide-on-click-modal="true"
                    :preview-teleported="true"
                    :initial-index="pairPreviewList(block).length > 1 ? 1 : 0"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.listingTitle')" prop="listing_title" class="listing-form-item--name" required>
        <div class="listing-field-full">
          <el-input
            v-model="form.listing_title"
            class="listing-name-input"
            :placeholder="t('dialogs.combinedListing.listingTitlePlaceholder')"
            clearable
          />
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.descriptionLabel')" prop="description" class="listing-form-item--desc" required>
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
            :placeholder="t('dialogs.combinedListing.descriptionPlaceholder')"
          />
          <div
            v-if="managementNumberLine"
            class="listing-mgmt-footer"
            :title="t('dialogs.combinedListing.mgmtFooterTooltip')"
          >
            {{ managementNumberLine }}
          </div>
        </div>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.productType')" prop="category_mapping_id" required>
        <el-select
          v-model="form.category_mapping_id"
          filterable
          clearable
          :placeholder="t('dialogs.combinedListing.productTypePlaceholder')"
          style="width: 100%"
        >
          <el-option
            v-for="opt in categoryTypeCascaderOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.productStatus')" prop="status" required>
        <el-select v-model="form.status" :placeholder="t('dialogs.combinedListing.productStatusPlaceholder')" style="width: 100%">
          <el-option v-for="s in listingStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.listingAccount')" prop="mercari_account_id" required>
        <el-select
          v-model="form.mercari_account_id"
          :placeholder="t('dialogs.combinedListing.listingAccountPlaceholder')"
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
      <el-form-item v-if="!isYahoo" :label="t('dialogs.combinedListing.shippingPayer')" prop="shipping_payer" required>
        <el-select v-model="form.shipping_payer" :placeholder="t('dialogs.combinedListing.shippingPayerPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.shippingMethod')" prop="shipping_method" required>
        <el-select v-model="form.shipping_method" :placeholder="t('dialogs.combinedListing.shippingMethodPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.shippingFrom')" prop="shipping_from" required>
        <el-cascader
          v-model="form.shipping_from_path"
          :options="shippingFromCascaderOptions"
          :props="shippingFromCascaderProps"
          :show-all-levels="false"
          filterable
          :placeholder="t('dialogs.combinedListing.shippingFromPlaceholder')"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleShippingFromChange"
        />
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.shippingDays')" prop="shipping_days" required>
        <el-select v-model="form.shipping_days" :placeholder="t('dialogs.combinedListing.shippingDaysPlaceholder')" style="width: 100%">
          <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <!-- 雅虎只有定价即购，没有拍卖 -->
      <el-form-item v-if="!isYahoo" :label="t('dialogs.combinedListing.saleType')" prop="sale_type" required>
        <div class="listing-compact-row">
          <el-select
            v-model="form.sale_type"
            :placeholder="t('dialogs.combinedListing.saleTypePlaceholder')"
            class="listing-compact-control"
            @change="onSaleTypeChange"
          >
            <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item
        v-if="form.sale_type === 'auction'"
        :label="t('dialogs.combinedListing.auctionDuration')"
        prop="auction_duration"
        required
      >
        <el-select v-model="form.auction_duration" :placeholder="t('dialogs.combinedListing.auctionDurationPlaceholder')" style="width: 100%">
          <el-option :label="t('dialogs.combinedListing.auctionDurationNormal')" value="normal" />
          <el-option :label="t('dialogs.combinedListing.auctionDuration3hours')" value="3hours" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('dialogs.combinedListing.unitPrice')" prop="price" class="listing-form-item--price" required>
        <div class="listing-compact-row">
          <el-input
            v-model="listingPriceEdit"
            :placeholder="t('dialogs.combinedListing.unitPricePlaceholder')"
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
        <el-button type="primary" @click="submitStub">{{ t('common.save') }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { shopAccountApi } from '@/api/index.js'
import { encodeMgmtIds, stripTrailingMgmtBlock } from '@/utils/mgmtIdCipher.js'
import { useListingPlatform } from '@/composables/useListingPlatform.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const { t } = useI18n()

const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  categoryMappings: { type: Array, default: () => [] },
  initialData: { type: Object, default: null },
  listingDefaults: { type: Object, default: null },
  isMobile: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const listingFormRef = ref()
const form = ref(getDefaultForm())
/** 组合出品：各库存条目的正/背面图（仅展示，不参与提交） */
const combinedPreviewImages = ref([])
/** 商品单价：纯文本整数，blur / 提交前写回 form.price */
const listingPriceEdit = ref('0')

const listingFormRules = computed(() => ({
  inventory_ids: [
    {
      type: 'array',
      required: true,
      min: 1,
      message: t('dialogs.combinedListing.ruleInventoryRequired'),
      trigger: 'change'
    }
  ],
  combined_listing_images: [
    {
      validator: (_, __, cb) => {
        const imgs = combinedPreviewImages.value
        if (!imgs.length) {
          cb(new Error(t('dialogs.combinedListing.ruleNoImages')))
          return
        }
        if (imgs.some((b) => !String(b?.front || '').trim())) {
          cb(new Error(t('dialogs.combinedListing.ruleEachNeedsFront')))
          return
        }
        cb()
      },
      trigger: 'change'
    }
  ],
  listing_title: [
    {
      validator: (_, val, cb) => {
        if (!String(val ?? '').trim()) cb(new Error(t('dialogs.combinedListing.ruleListingTitleRequired')))
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
          cb(new Error(t('dialogs.combinedListing.rulePriceInvalid')))
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
          cb(new Error(t('dialogs.combinedListing.ruleAuctionDurationRequired')))
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
        if (!String(val ?? '').trim()) cb(new Error(t('dialogs.combinedListing.ruleDescriptionRequired')))
        else cb()
      },
      trigger: 'blur'
    }
  ],
  category_mapping_id: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error(t('dialogs.combinedListing.ruleProductTypeRequired')))
        else cb()
      },
      trigger: 'change'
    }
  ],
  status: [{ required: true, message: t('dialogs.combinedListing.ruleStatusRequired'), trigger: 'change' }],
  mercari_account_id: [
    {
      required: true,
      message: t('dialogs.combinedListing.ruleAccountRequired'),
      trigger: 'change'
    }
  ],
  shipping_payer: [{ required: true, message: t('dialogs.combinedListing.ruleShippingPayerRequired'), trigger: 'change' }],
  shipping_method: [{ required: true, message: t('dialogs.combinedListing.ruleShippingMethodRequired'), trigger: 'change' }],
  shipping_from: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error(t('dialogs.combinedListing.ruleShippingFromRequired')))
        else cb()
      },
      trigger: 'change'
    }
  ],
  shipping_days: [{ required: true, message: t('dialogs.combinedListing.ruleShippingDaysRequired'), trigger: 'change' }],
  sale_type: [{ required: true, message: t('dialogs.combinedListing.ruleSaleTypeRequired'), trigger: 'change' }]
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

function pairPreviewList(block) {
  return [block?.front, block?.back].filter((u) => u && String(u).trim())
}

/** 所选库存 id 的末行暗号（-=~<> 五进制），保存时拼在说明最底部 */
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

/** 商品类型是扁平列表（映射表一行一个类型），下拉直接用类型名 */
const categoryTypeCascaderOptions = computed(() => {
  const options = []
  for (const m of (props.categoryMappings || [])) {
    const mappingId = String(m?.mapping_id ?? '').trim()
    const typeName = String(m?.product_type ?? '').trim()
    if (!mappingId || !typeName) continue
    options.push({ value: mappingId, label: typeName })
  }
  options.sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
  return options
})

const listingStatusOptions = computed(() => [
  { label: t('dialogs.combinedListing.statusNewUnused'), value: 'new_unused' },
  { label: t('dialogs.combinedListing.statusAlmostUnused'), value: 'almost_unused' },
  { label: t('dialogs.combinedListing.statusGood'), value: 'good' },
  { label: t('dialogs.combinedListing.statusFair'), value: 'fair' },
  { label: t('dialogs.combinedListing.statusUsed'), value: 'used' }
])
const shippingPayerOptions = computed(() => [
  { label: t('dialogs.combinedListing.payerSeller'), value: 'seller' },
  { label: t('dialogs.combinedListing.payerBuyer'), value: 'buyer' }
])
// 雅虎账号：只有おてがる配送两家承运商，且没有快递费负担/販売形式（见 useListingPlatform）
const { isYahoo, yahooShippingMethodOptions } = useListingPlatform(mercariAccountOptions, form)
const shippingMethodOptions = computed(() => isYahoo.value
  ? yahooShippingMethodOptions.value
  : [
      { label: t('dialogs.combinedListing.methodUndecided'), value: 'undecided' },
      { label: t('dialogs.combinedListing.methodRakuraku'), value: 'rakuraku' },
      { label: t('dialogs.combinedListing.methodYuuyu'), value: 'yuuyu' },
      { label: t('dialogs.combinedListing.methodRegularMail'), value: 'regular_mail' }
    ])
const shippingDaysOptions = computed(() => [
  { label: t('dialogs.combinedListing.days1to2'), value: '1_2_days' },
  { label: t('dialogs.combinedListing.days2to3'), value: '2_3_days' },
  { label: t('dialogs.combinedListing.days4to7'), value: '4_7_days' }
])
const saleTypeOptions = computed(() => [
  { label: t('dialogs.combinedListing.saleInstant'), value: 'instant_buy' },
  { label: t('dialogs.combinedListing.saleAuction'), value: 'auction' }
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
  const tail = sid ? ` · ${t('dialogs.combinedListing.sellerLabel', { id: sid })}` : ''
  const inactive = a?.status === 'disabled' ? t('dialogs.combinedListing.inactiveSuffix') : ''
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
    const areaFromSeed = normalizeShippingFromSeed(seed.shipping_from)
    const areaFromCfg = normalizeShippingFromSeed(cfg.shipping_from_area_id)
    const areaId = areaFromSeed || areaFromCfg || ''
    const accId = seed.mercari_account_id != null ? Number(seed.mercari_account_id) : null
    const cfgMid = cfg.mercari_account_id != null ? Number(cfg.mercari_account_id) : null
    const seedPrice = seed.price != null ? Math.round(Number(seed.price)) : 0
    const priceVal = Number.isFinite(seedPrice) && seedPrice >= 0 ? seedPrice : 0
    combinedPreviewImages.value = Array.isArray(seed.combined_images) ? seed.combined_images : []
    form.value = {
      ...getDefaultForm(),
      image: '',
      image_back: '',
      listing_title: seed.listing_title || seed.name || '',
      category_mapping_id: seedMappingId,
      description: '',
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
    image: '',
    image_back: '',
    listing_title: '',
    category_mapping_id: null,
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
    price: 0,
    /** 仅占位，供「商品图片」表单项校验（实际读 combinedPreviewImages） */
    combined_listing_images: ''
  }
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
/** 商品名 / 商品说明 / 单价 */
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
  flex-direction: row;
  align-items: flex-start;
  width: 100%;
}
.listing-images-thumbs {
  display: flex;
  flex-direction: row;
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
.listing-combined-images-wrap {
  width: 100%;
}
.listing-combined-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  max-height: 280px;
  overflow-y: auto;
  padding: 2px 0;
}
.listing-combined-card {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 10px;
  background: rgba(0, 0, 0, 0.12);
}
.listing-combined-card-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}
.listing-images-thumbs--combined {
  flex-wrap: nowrap;
}
.listing-image-preview--combined,
.listing-image-empty--combined {
  width: 80px;
  height: 80px;
  border-radius: 6px;
}
.listing-image-empty--combined {
  font-size: 11px;
}
.listing-combined-empty {
  font-size: 13px;
  color: #8ea0bf;
  padding: 12px 0;
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
