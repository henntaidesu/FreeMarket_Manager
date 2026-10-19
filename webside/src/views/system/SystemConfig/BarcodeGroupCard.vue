<template>
  <!-- 一组「同条码 + 同归属人」的商品：选一对一 / 一对多，给每件定款式与品相，
       款式 × 品相相同的几件并进其中管理番号最新的那件（确认名称 + 勾选组合图片），不新开管理番号。 -->
  <div class="bg-card">
    <div class="bg-head">
      <span class="bg-mono bg-code">{{ group.barcode }}</span>
      <span class="bg-muted">{{ t('barcodeHistory.owner') }}：{{ group.owner_user_name || '—' }}</span>
      <el-radio-group v-model="mode" size="small" class="bg-mode">
        <el-radio-button value="single" :disabled="group.others_multi">{{ t('barcodeHistory.modeSingle') }}</el-radio-button>
        <el-radio-button value="multi">{{ t('barcodeHistory.modeMulti') }}</el-radio-button>
      </el-radio-group>
      <span class="bg-muted">{{ mode === 'single' ? t('barcodeHistory.modeSingleTip') : t('barcodeHistory.modeMultiTip') }}</span>
      <span class="bg-muted bg-count">{{ t('barcodeHistory.selectedCount', { n: includedItems.length, total: group.items.length }) }}</span>
    </div>

    <el-table :data="group.items" size="small" border :row-class-name="rowClass">
      <el-table-column width="56" align="center">
        <template #header>
          <el-checkbox
            :model-value="includedItems.length === group.items.length"
            :indeterminate="includedItems.length > 0 && includedItems.length < group.items.length"
            @change="setAll"
          />
        </template>
        <template #default="{ row }">
          <el-checkbox v-model="plan[row.id].on" />
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.mainImage')" width="92" align="center">
        <template #default="{ row }">
          <el-image
            v-if="row.images.length"
            :src="thumb(row.images[0], 240)"
            :preview-src-list="row.images"
            fit="cover"
            class="bg-main"
            :class="{ 'bg-img--borrowed': borrowedImages(row).includes(row.images[0]) }"
            preview-teleported
            hide-on-click-modal
          />
          <span v-else class="bg-small">{{ t('barcodeHistory.noImages') }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.otherImages')" min-width="120">
        <template #default="{ row }">
          <div class="bg-imgs">
            <el-image
              v-for="(img, idx) in row.images.slice(1)"
              :key="img"
              :src="thumb(img)"
              :preview-src-list="row.images"
              :initial-index="idx + 1"
              fit="cover"
              class="bg-img"
              :class="{ 'bg-img--borrowed': borrowedImages(row).includes(img) }"
              preview-teleported
              hide-on-click-modal
            />
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.mgmtNo')" width="110" align="center">
        <template #default="{ row }">
          <el-button link type="primary" class="bg-mono" @click="emit('open-item', row.id)">{{ row.mgmt_code || row.id }}</el-button>
          <div v-if="row.mgmt_code !== String(row.id)" class="bg-small">#{{ row.id }}</div>
          <div v-if="row.merged_from_ids.length" class="bg-small">
            {{ t('barcodeHistory.inheritedIds', { ids: row.merged_from_ids.join(', ') }) }}
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.itemName')" min-width="190">
        <template #default="{ row }">
          <div class="bg-name-text">{{ row.name || '-' }}</div>
          <el-tag v-if="row.same_set_ids?.length" type="info" size="small" effect="light" class="bg-flag">
            {{ t('barcodeHistory.sameSetFlag', { ids: idsLabel(row.same_set_ids) }) }}
          </el-tag>
          <template v-if="row.borrowed?.length">
            <el-tag type="danger" size="small" effect="light" class="bg-flag">
              {{ t('barcodeHistory.borrowedFlag', { ids: idsLabel(borrowPeers(row)) }) }}
            </el-tag>
            <div class="bg-flag-actions">
              <el-button link type="danger" size="small" :loading="flagBusy === row.id" @click="markBorrowed(row)">
                {{ t('barcodeHistory.notThisBarcode') }}
              </el-button>
              <el-button link type="primary" size="small" :loading="flagBusy === row.id" @click="confirmBarcode(row)">
                {{ t('barcodeHistory.barcodeCorrect') }}
              </el-button>
            </div>
          </template>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.counts')" width="96" align="center">
        <template #default="{ row }">
          <div class="bg-small">{{ t('barcodeHistory.quantity') }} {{ row.quantity }}</div>
          <div class="bg-small">{{ t('barcodeHistory.onSale') }} {{ row.on_sale_quantity }} · {{ t('barcodeHistory.pendingOut') }} {{ row.pending_outbound_qty }}</div>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'multi'" :label="t('barcodeHistory.variant')" width="150">
        <template #default="{ row }">
          <el-select
            v-model="plan[row.id].variant_no"
            size="small"
            :disabled="!plan[row.id].on"
            :placeholder="t('barcodeHistory.pickVariant')"
          >
            <el-option v-for="o in variantOptions" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.grade')" width="110">
        <template #default="{ row }">
          <el-select
            v-model="plan[row.id].grade"
            size="small"
            clearable
            :disabled="!plan[row.id].on"
            :placeholder="t('barcodeHistory.gradeUnset')"
          >
            <el-option v-for="g in GRADES" :key="g" :value="g" :label="t(`barcodeHistory.grade${g}`)" />
          </el-select>
        </template>
      </el-table-column>
    </el-table>

    <!-- 归类结果预览：每个款式 × 品相一件商品；两件以上的要合并 -->
    <div class="bg-section">{{ t('barcodeHistory.resultTitle', { n: buckets.length }) }}</div>
    <div v-for="b in buckets" :key="b.key" class="bg-bucket" :class="{ 'bg-bucket--merge': b.ids.length > 1 }">
      <div class="bg-bucket-head">
        <el-image
          v-if="bucketMainImage(b)"
          :src="thumb(bucketMainImage(b), 240)"
          :preview-src-list="bucketImages(b)"
          fit="cover"
          class="bg-main bg-main--sm"
          preview-teleported
          hide-on-click-modal
        />
        <span v-else class="bg-main bg-main--sm bg-main--empty">{{ t('barcodeHistory.noImages') }}</span>
        <span class="bg-mono bg-code">{{ b.code }}</span>
        <el-tag v-if="b.ids.length > 1" type="warning" size="small" effect="light">
          {{ t('barcodeHistory.willMerge', { n: b.ids.length, code: itemLabel(b.ids[0]).split(' ')[0] }) }}
        </el-tag>
        <el-tag v-else size="small" effect="plain">{{ t('barcodeHistory.keepAsIs') }}</el-tag>
        <span v-if="b.missing" class="bg-warn">{{ t('barcodeHistory.pickVariantFirst') }}</span>
        <span v-if="b.blocker" class="bg-warn">{{ t('barcodeHistory.blocked', { reason: b.blocker }) }}</span>
      </div>
      <template v-if="b.ids.length > 1 && !b.missing">
        <div class="bg-small">{{ t('barcodeHistory.mergeFrom', { list: b.ids.map(itemLabel).join('、') }) }}</div>
        <div class="bg-row">
          <span class="bg-label">{{ t('barcodeHistory.newName') }}</span>
          <el-input
            v-model="bucketState[b.key].name"
            size="small"
            maxlength="255"
            clearable
            class="bg-name"
            :placeholder="t('barcodeHistory.newNamePlaceholder')"
          />
        </div>
        <div class="bg-row bg-row--top">
          <span class="bg-label">{{ t('barcodeHistory.pickImages', { n: bucketState[b.key].images.length }) }}</span>
          <div class="bg-pool">
            <div
              v-for="img in b.pool"
              :key="img"
              class="bg-pick"
              :class="{ 'is-on': bucketState[b.key].images.includes(img) }"
              role="button"
              tabindex="0"
              @click="toggleImage(b.key, img)"
              @keydown.enter.prevent="toggleImage(b.key, img)"
            >
              <img :src="thumb(img)" alt="" />
              <span v-if="bucketState[b.key].images.includes(img)" class="bg-pick-no">
                {{ bucketState[b.key].images.indexOf(img) === 0 ? t('barcodeHistory.mainImage') : bucketState[b.key].images.indexOf(img) + 1 }}
              </span>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="bg-small">{{ b.ids.map(itemLabel).join('、') }}</div>
    </div>

    <div class="bg-actions">
      <el-button size="small" @click="reset">{{ t('barcodeHistory.resetPlan') }}</el-button>
      <el-button size="small" type="primary" :loading="busy" :disabled="!canSubmit" @click="submit">
        {{ t('barcodeHistory.confirmClassify', { m: mergeBuckets.length }) }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { configApi } from '@/api/index.js'

const props = defineProps({ group: { type: Object, required: true } })
const emit = defineEmits(['done', 'open-item'])
const { t } = useI18n()
const GRADES = ['S', 'A', 'J']

const mode = ref('single')
const plan = reactive({})
const bucketState = reactive({})
const busy = ref(false)
const flagBusy = ref(null)

/** 管理番号列表（同组的显示管理编号，其他归属人名下的显示 #id） */
function idsLabel(ids) {
  return (ids || []).map((id) => byId.value[id]?.mgmt_code || `#${id}`).join('、')
}

function borrowPeers(row) {
  return [...new Set((row.borrowed || []).flatMap((b) => b.peers))]
}

function borrowedImages(row) {
  return (row.borrowed || []).map((b) => b.image)
}

/** 条码不属于此商品：清空条码（图片保留），这件随即离开本组 */
async function markBorrowed(row) {
  try {
    await ElMessageBox.confirm(
      t('barcodeHistory.notThisBarcodeConfirm', { code: row.mgmt_code || row.id, barcode: props.group.barcode }),
      t('barcodeHistory.notThisBarcode'),
      { type: 'warning' }
    )
  } catch {
    return
  }
  flagBusy.value = row.id
  try {
    const res = await configApi.markBarcodeBorrowed(row.id)
    ElMessage.success(t('barcodeHistory.notThisBarcodeDone'))
    emit('done', res?.status)
  } catch {
    // http 拦截器已提示错误
  } finally {
    flagBusy.value = null
  }
}

/** 条码正确（系列共用条码等）：以后不再提示借用 */
async function confirmBarcode(row) {
  flagBusy.value = row.id
  try {
    const res = await configApi.confirmBarcode(row.id)
    ElMessage.success(t('barcodeHistory.barcodeCorrectDone'))
    emit('done', res?.status)
  } catch {
    // http 拦截器已提示错误
  } finally {
    flagBusy.value = null
  }
}

function thumb(path, size = 120) {
  return String(path).startsWith('/imges/')
    ? `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=${size}`
    : path
}

/** 归类结果里这件商品的图：合并组 = 人勾选的组合（第 1 张即新商品主图），单件 = 它自己的图 */
function bucketImages(b) {
  if (b.ids.length > 1 && !b.missing) return bucketState[b.key]?.images || []
  return byId.value[b.ids[0]]?.images || []
}

function bucketMainImage(b) {
  return bucketImages(b)[0] || ''
}

const byId = computed(() => Object.fromEntries(props.group.items.map((it) => [it.id, it])))

function itemLabel(id) {
  const it = byId.value[id]
  return it ? `${it.mgmt_code || it.id} ${it.name || ''}`.trim() : String(id)
}

function reset() {
  mode.value = props.group.multi ? 'multi' : 'single'
  for (const k of Object.keys(plan)) delete plan[k]
  for (const it of props.group.items) plan[it.id] = { on: true, variant_no: it.variant_no ?? null, grade: it.grade || null }
  for (const k of Object.keys(bucketState)) delete bucketState[k]
}
watch(() => props.group, reset, { immediate: true })

/** 款式下拉：本条码已有的款式（带样品名）+ 当前归类里用到的 + 一个「新款式」 */
const variantOptions = computed(() => {
  const named = Object.fromEntries((props.group.variants || []).map((v) => [v.variant_no, v.name]))
  const used = Object.values(plan).map((p) => Number(p.variant_no)).filter((n) => n > 0)
  const max = Math.max(0, ...Object.keys(named).map(Number), ...used)
  const opts = []
  for (let n = 1; n <= max; n++) {
    opts.push({ value: n, label: named[n] ? `${t('barcodeHistory.variantN', { n })} · ${named[n]}` : t('barcodeHistory.variantN', { n }) })
  }
  opts.push({ value: max + 1, label: t('barcodeHistory.newVariant', { n: max + 1 }) })
  return opts
})

/** 勾选参与本次归类的商品；未勾选的原样不动、留在待合并里 */
const includedItems = computed(() => props.group.items.filter((it) => plan[it.id]?.on))

function setAll(val) {
  for (const it of props.group.items) if (plan[it.id]) plan[it.id].on = !!val
}

function rowClass({ row }) {
  return plan[row.id]?.on ? '' : 'bg-row-off'
}

const buckets = computed(() => {
  const map = new Map()
  for (const it of includedItems.value) {
    const p = plan[it.id] || {}
    const v = mode.value === 'multi' ? (p.variant_no ?? null) : null
    const g = p.grade || null
    const missing = mode.value === 'multi' && v == null
    const key = missing ? `missing:${it.id}` : `${v ?? ''}|${g ?? ''}`
    if (!map.has(key)) {
      const code = props.group.barcode + (v != null ? `-${v}` : '') + (g ? `-${g}` : '')
      map.set(key, { key, code, ids: [], missing, variant_no: v, grade: g })
    }
    map.get(key).ids.push(it.id)
  }
  return [...map.values()].map((b) => ({
    ...b,
    pool: [...new Set(b.ids.flatMap((id) => byId.value[id]?.images || []))],
    blocker: b.ids.length > 1 ? b.ids.map((id) => byId.value[id]?.blocker).find(Boolean) || '' : ''
  }))
})

const mergeBuckets = computed(() => buckets.value.filter((b) => b.ids.length > 1 && !b.missing))

// 合并到组里管理番号最新的那件（列表按番号倒序，ids[0]）：名称与图片默认取它自己的，人可改
watch(
  mergeBuckets,
  (list) => {
    for (const b of list) {
      const st = bucketState[b.key]
      if (!st) {
        const newest = byId.value[b.ids[0]]
        bucketState[b.key] = { name: newest?.name || '', images: [...(newest?.images || [])] }
      } else {
        st.images = st.images.filter((img) => b.pool.includes(img))
      }
    }
  },
  { immediate: true }
)

function toggleImage(key, img) {
  const list = bucketState[key].images
  const i = list.indexOf(img)
  if (i >= 0) list.splice(i, 1)
  else list.push(img)
}

const canSubmit = computed(() => {
  if (!includedItems.value.length) return false
  if (buckets.value.some((b) => b.missing)) return false
  return mergeBuckets.value.every(
    (b) => !b.blocker && bucketState[b.key]?.images.length > 0 && String(bucketState[b.key]?.name || '').trim()
  )
})

async function submit() {
  const merges = mergeBuckets.value
  try {
    await ElMessageBox.confirm(
      merges.length
        ? t('barcodeHistory.classifyConfirmMerge', {
            list: merges.map((b) => `${b.code}（${b.ids.length} → #${b.ids[0]}）`).join('、')
          })
        : t('barcodeHistory.classifyConfirmPlain'),
      t('barcodeHistory.classifyConfirmTitle'),
      { type: 'warning' }
    )
  } catch {
    return
  }
  busy.value = true
  try {
    const res = await configApi.classifyBarcodeGroup({
      barcode: props.group.barcode,
      owner_user_id: props.group.owner_user_id ?? null,
      mode: mode.value,
      items: includedItems.value.map((it) => ({
        id: it.id,
        variant_no: mode.value === 'multi' ? plan[it.id].variant_no : null,
        grade: plan[it.id].grade || null
      })),
      exclude_ids: props.group.items.filter((it) => !plan[it.id]?.on).map((it) => it.id),
      buckets: merges.map((b) => ({
        variant_no: b.variant_no,
        grade: b.grade,
        name: String(bucketState[b.key].name || '').trim(),
        images: bucketState[b.key].images
      }))
    })
    const merged = res?.merged || []
    ElMessage.success(
      merged.length
        ? t('barcodeHistory.classifyDoneMerged', { list: merged.map((m) => `${m.code} → #${m.target_id}`).join('、') })
        : t('barcodeHistory.classifyDone')
    )
    emit('done', res?.status)
  } catch {
    // http 拦截器已提示错误
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.bg-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 14px;
}
.bg-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.bg-code { font-weight: 600; }
.bg-mono { font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-variant-numeric: tabular-nums; }
.bg-muted { font-size: 12px; color: var(--el-text-color-secondary); }
.bg-small { font-size: 11px; line-height: 1.3; color: var(--el-text-color-secondary); }
.bg-warn { font-size: 12px; color: var(--el-color-warning); }
.bg-imgs { display: flex; flex-wrap: wrap; gap: 4px; }
.bg-img { width: 40px; height: 40px; border-radius: 4px; }
.bg-img--borrowed { outline: 2px solid var(--el-color-danger); outline-offset: 1px; }
.bg-name-text { line-height: 1.4; margin-bottom: 4px; }
.bg-flag { margin: 2px 4px 2px 0; white-space: normal; height: auto; line-height: 1.4; padding: 2px 6px; }
.bg-flag-actions { display: flex; flex-wrap: wrap; gap: 4px; }
.bg-main { width: 72px; height: 72px; border-radius: 6px; display: block; }
.bg-main--sm { width: 56px; height: 56px; flex: none; }
.bg-main--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}
.bg-section { margin: 12px 0 6px; font-size: 13px; font-weight: 600; }
.bg-bucket {
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
}
.bg-bucket--merge { border-style: solid; border-color: var(--el-color-warning-light-5); }
.bg-bucket-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; }
.bg-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 6px; }
.bg-row--top { align-items: flex-start; }
.bg-label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 84px; }
.bg-pool { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }
.bg-name { max-width: 420px; flex: 1; }
.bg-pick {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 6px;
  border: 2px solid transparent;
  overflow: hidden;
  cursor: pointer;
  opacity: 0.45;
}
.bg-pick img { width: 100%; height: 100%; object-fit: cover; display: block; }
.bg-pick.is-on { border-color: var(--el-color-primary); opacity: 1; }
.bg-pick-no {
  position: absolute;
  top: 2px;
  left: 2px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: 9px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}
.bg-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.bg-count { margin-left: auto; }
:deep(.bg-row-off) td { opacity: 0.45; }
:deep(.bg-row-off) td:first-child { opacity: 1; }
</style>
