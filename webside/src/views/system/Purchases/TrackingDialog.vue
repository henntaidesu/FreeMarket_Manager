<!--
  配送履历弹窗：点运单号打开，后端直连黑猫 / 邮局的公开查询页取回履历。

  表格与卡片两个视图、以及详情弹窗里的运单号，点下去开的都是这一个弹窗——
  取数与展示只写一遍。取数由父级（script.js 的 openTracking）负责，这里只管展示，
  因为「点哪一行」这件事只有父级知道。
-->
<template>
  <el-dialog
    :model-value="visible"
    :title="t('purchases.trackingTitle')"
    width="560px"
    top="8vh"
    append-to-body
    @update:model-value="$emit('update:visible', $event)"
  >
    <div v-loading="loading" class="trk">
      <template v-if="trace">
        <div class="trk-head">
          <div class="trk-no">{{ trace.tracking_no || '-' }}</div>
          <el-tag size="small" effect="plain">{{ trace.carrier_name || '-' }}</el-tag>
          <el-tag v-if="trace.item_kind" size="small" effect="plain">{{ trace.item_kind }}</el-tag>
          <el-tag v-if="cached" size="small" type="info" effect="plain">
            {{ t('purchases.trackingCached') }}
          </el-tag>
          <el-button size="small" :loading="loading" @click="$emit('refresh')">
            {{ t('purchases.trackingRefresh') }}
          </el-button>
        </div>

        <div v-if="trace.status" class="trk-status">{{ trace.status }}</div>
        <div v-if="trace.summary" class="trk-summary">{{ trace.summary }}</div>
        <!-- 承运公司说「查不到」与我们「解析不出」是两回事，都原样转述，不改写成通用错误 -->
        <el-alert
          v-if="trace.message"
          :title="trace.message"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

        <!-- 履历按承运公司页面的顺序（旧 → 新）原样排，不重排也不补节点 -->
        <ol v-if="(trace.events || []).length" class="trk-list">
          <li v-for="(e, i) in trace.events" :key="i" class="trk-item">
            <span class="trk-dot" :class="{ 'is-last': i === trace.events.length - 1 }"></span>
            <div class="trk-body">
              <div class="trk-row">
                <span class="trk-state">{{ e.status || '-' }}</span>
                <span class="trk-at">{{ e.at_text || '' }}</span>
              </div>
              <div v-if="e.location || e.area" class="trk-place">
                {{ [e.location, e.area].filter(Boolean).join(' / ') }}
              </div>
              <div v-if="e.detail" class="trk-detail">{{ e.detail }}</div>
            </div>
          </li>
        </ol>
        <el-empty v-else-if="!loading" :description="t('purchases.trackingEmpty')" :image-size="60" />

        <div class="trk-foot">
          <span v-if="trace.fetched_at" class="trk-fetched">
            {{ t('purchases.trackingFetchedAt') }}: {{ formatUnixSecLocal(trace.fetched_at) }}
          </span>
          <a v-if="trace.url" :href="trace.url" target="_blank" rel="noopener">
            {{ t('purchases.trackingOpenSite') }}
          </a>
        </div>
      </template>
      <el-empty v-else-if="!loading" :description="error || t('purchases.trackingEmpty')" :image-size="60" />
    </div>
  </el-dialog>
</template>

<script>
import { defineComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'

export default defineComponent({
  name: 'PurchaseTrackingDialog',
  props: {
    visible: { type: Boolean, default: false },
    trace: { type: Object, default: null },
    loading: { type: Boolean, default: false },
    cached: { type: Boolean, default: false },
    error: { type: String, default: '' },
  },
  emits: ['update:visible', 'refresh'],
  setup() {
    const { t } = useI18n()
    return { t, formatUnixSecLocal }
  },
})
</script>

<style scoped>
.trk { min-height: 120px; }
.trk-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.trk-no { font-size: 16px; font-weight: 600; letter-spacing: .5px; }
.trk-head .el-button { margin-left: auto; }
.trk-status { font-size: 15px; font-weight: 600; color: var(--el-color-primary); }
.trk-summary { font-size: 13px; color: var(--el-text-color-regular); margin-top: 2px; }
.trk-list { list-style: none; margin: 14px 0 0; padding: 0 0 0 6px; }
.trk-item { position: relative; padding: 0 0 16px 20px; border-left: 2px solid var(--el-border-color-lighter); }
.trk-item:last-child { border-left-color: transparent; padding-bottom: 0; }
.trk-dot {
  position: absolute; left: -6px; top: 4px; width: 10px; height: 10px; border-radius: 50%;
  background: var(--el-color-info-light-5);
}
.trk-dot.is-last { background: var(--el-color-primary); }
.trk-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.trk-state { font-size: 14px; font-weight: 600; }
.trk-at { font-size: 12px; color: var(--el-text-color-secondary); }
.trk-place { font-size: 12px; color: var(--el-text-color-regular); margin-top: 2px; }
.trk-detail { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.trk-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter);
  font-size: 12px; color: var(--el-text-color-secondary);
}
.trk-foot a { color: var(--el-color-primary); }
</style>
