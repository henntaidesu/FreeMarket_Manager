<template>
  <!-- 一组「同条码 + 同归属人」的商品：选一对一 / 一对多，给每件定款式与品相，
       款式 × 品相相同的几件直接新开一个管理番号（填新商品名称 + 勾选组合图片），不选主商品。 -->
  <div class="bg-card">
    <div class="bg-head">
      <span class="bg-mono bg-code">{{ group.barcode }}</span>
      <span class="bg-muted">{{ t('barcodeHistory.owner') }}：{{ group.owner_user_name || '—' }}</span>
      <el-radio-group v-model="mode" size="small" class="bg-mode">
        <el-radio-button value="single" :disabled="group.others_multi">{{ t('barcodeHistory.modeSingle') }}</el-radio-button>
        <el-radio-button value="multi">{{ t('barcodeHistory.modeMulti') }}</el-radio-button>
      </el-radio-group>
      <span class="bg-muted">{{ mode === 'single' ? t('barcodeHistory.modeSingleTip') : t('barcodeHistory.modeMultiTip') }}</span>
    </div>

    <el-table :data="group.items" size="small" border>
      <el-table-column :label="t('barcodeHistory.images')" min-width="150">
        <template #default="{ row }">
          <div class="bg-imgs">
            <el-image
              v-for="(img, idx) in row.images"
              :key="img"
              :src="thumb(img)"
              :preview-src-list="row.images"
              :initial-index="idx"
              fit="cover"
              class="bg-img"
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
      <el-table-column :label="t('barcodeHistory.itemName')" min-width="150" show-overflow-tooltip prop="name" />
      <el-table-column :label="t('barcodeHistory.counts')" width="96" align="center">
        <template #default="{ row }">
          <div class="bg-small">{{ t('barcodeHistory.quantity') }} {{ row.quantity }}</div>
          <div class="bg-small">{{ t('barcodeHistory.onSale') }} {{ row.on_sale_quantity }} · {{ t('barcodeHistory.pendingOut') }} {{ row.pending_outbound_qty }}</div>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'multi'" :label="t('barcodeHistory.variant')" width="150">
        <template #default="{ row }">
          <el-select v-model="plan[row.id].variant_no" size="small" :placeholder="t('barcodeHistory.pickVariant')">
            <el-option v-for="o in variantOptions" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.grade')" width="110">
        <template #default="{ row }">
          <el-select v-model="plan[row.id].grade" size="small" clearable :placeholder="t('barcodeHistory.gradeUnset')">
            <el-option v-for="g in GRADES" :key="g" :value="g" :label="t(`barcodeHistory.grade${g}`)" />
          </el-select>
        </template>
      </el-table-column>
    </el-table>

    <!-- 归类结果预览：每个款式 × 品相一件商品；两件以上的要合并 -->
    <div class="bg-section">{{ t('barcodeHistory.resultTitle', { n: buckets.length }) }}</div>
    <div v-for="b in buckets" :key="b.key" class="bg-bucket" :class="{ 'bg-bucket--merge': b.ids.length > 1 }">
      <div class="bg-bucket-head">
        <span class="bg-mono bg-code">{{ b.code }}</span>
        <el-tag v-if="b.ids.length > 1" type="warning" size="small" effect="light">
          {{ t('barcodeHistory.willMerge', { n: b.ids.length }) }}
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
                {{ bucketState[b.key].images.indexOf(img) + 1 }}
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

function thumb(path) {
  return String(path).startsWith('/imges/')
    ? `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=120`
    : path
}

const byId = computed(() => Object.fromEntries(props.group.items.map((it) => [it.id, it])))

function itemLabel(id) {
  const it = byId.value[id]
  return it ? `${it.mgmt_code || it.id} ${it.name || ''}`.trim() : String(id)
}

function reset() {
  mode.value = props.group.multi ? 'multi' : 'single'
  for (const k of Object.keys(plan)) delete plan[k]
  for (const it of props.group.items) plan[it.id] = { variant_no: it.variant_no ?? null, grade: it.grade || null }
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

const buckets = computed(() => {
  const map = new Map()
  for (const it of props.group.items) {
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

// 每个合并组新开一个管理番号：名称与图片默认取组里最新那件（列表按番号倒序，ids[0]），人可改
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
            list: merges.map((b) => `${b.code}（${b.ids.length}）`).join('、')
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
      items: props.group.items.map((it) => ({
        id: it.id,
        variant_no: mode.value === 'multi' ? plan[it.id].variant_no : null,
        grade: plan[it.id].grade || null
      })),
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
        ? t('barcodeHistory.classifyDoneMerged', { list: merged.map((m) => `${m.code} → #${m.new_id}`).join('、') })
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
</style>
