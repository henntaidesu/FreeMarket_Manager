<template>
  <!-- 同条码、同归属人的商品：人工归类（一对一 / 一对多、款式、品相），款式 × 品相相同的合并为
       一个新管理番号（旧番号由新商品继承）。组由后端按当前数据现算，处理完即消失。 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('barcodeHistory.mergeTitle')"
    width="min(1080px, 96vw)"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="reload"
  >
    <div class="bm-tip">{{ t('barcodeHistory.mergeTip') }}</div>
    <div v-loading="loading" class="bm-list">
      <el-empty v-if="!loading && !groups.length" :description="t('barcodeHistory.mergeEmpty')" />
      <BarcodeGroupCard
        v-for="g in groups"
        :key="`${g.barcode}|${g.owner_user_id ?? 0}`"
        :group="g"
        @open-item="openItem"
        @done="onDone"
      />
    </div>
    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      small
      class="bm-pager"
      @current-change="load"
    />
    <BarcodeItemDetailDialog v-model="detailVisible" :inventory-id="detailId" />
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import BarcodeGroupCard from './BarcodeGroupCard.vue'
import BarcodeItemDetailDialog from './BarcodeItemDetailDialog.vue'
import { configApi } from '@/api/index.js'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'changed'])
const { t } = useI18n()

const groups = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const detailVisible = ref(false)
const detailId = ref(null)

async function load() {
  loading.value = true
  try {
    const res = await configApi.listBarcodeMergeGroups({ page: page.value, page_size: pageSize })
    groups.value = Array.isArray(res?.groups) ? res.groups : []
    total.value = Number(res?.total) || 0
    if (!groups.value.length && page.value > 1) {
      page.value -= 1
      await load()
    }
  } catch {
    groups.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

async function onDone(status) {
  emit('changed', status)
  await load()
}

/** 在当页弹出商品库存详情，不跳库存管理（待合并列表保持原样，看完接着处理） */
function openItem(id) {
  detailId.value = id
  detailVisible.value = true
}
</script>

<style scoped>
.bm-tip {
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
}
.bm-list { min-height: 120px; }
.bm-pager { margin-top: 10px; justify-content: flex-end; }
</style>
