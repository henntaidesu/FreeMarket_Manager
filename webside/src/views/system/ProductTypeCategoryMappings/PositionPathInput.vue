<!--
  分类点选路径录入：一排「第 N 项」输入框，长度即层级数。
  出品自动化在该平台的分类弹层里，按这个数组逐级点第 N 个条目。
  空格子在提交时被滤掉（见 script.js 的 cleanPositions），所以预设几个空位不影响落库；
  清空某一格即等于去掉该级，不另设删除按钮。
-->
<template>
  <div class="pos-path">
    <div v-for="(pos, idx) in levels" :key="idx" class="pos-path__item">
      <span class="pos-path__idx">{{ idx + 1 }}</span>
      <el-input
        :model-value="pos"
        inputmode="numeric"
        class="pos-path__input"
        @update:model-value="(v) => setLevel(idx, v)"
      />
    </div>
    <el-button circle :icon="Plus" class="pos-path__add" @click="addLevel" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'

// 只保证「正整数」，不设上限：分类某一层可能有几十项，
// 卡上限会让合法位置填不进去。填错了出品时会报「位置 N 超出范围（当前层共 M 项）」。
const POSITION_MIN = 1
/** 默认铺满 5 级，够绝大多数分类；更深的用 + 继续加 */
const MIN_LEVELS = 5

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

/** 编辑期允许空串（正在删改中），提交时由调用方过滤 */
const levels = computed(() => {
  const list = (Array.isArray(props.modelValue) ? props.modelValue : []).map((v) =>
    v === null || v === undefined || v === '' ? '' : String(v),
  )
  while (list.length < MIN_LEVELS) list.push('')
  return list
})

function clamp(raw) {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (!digits) return ''
  const n = parseInt(digits, 10)
  if (Number.isNaN(n)) return ''
  return String(Math.max(POSITION_MIN, n))
}

function push(next) {
  emit('update:modelValue', next)
}

function setLevel(idx, value) {
  const next = [...levels.value]
  next[idx] = clamp(value)
  push(next)
}

function addLevel() {
  push([...levels.value, ''])
}
</script>

<style scoped>
.pos-path { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.pos-path__item { display: flex; align-items: center; gap: 2px; }
.pos-path__idx {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  min-width: 12px;
  text-align: right;
}
/* el-input 自带 width:100%，在 flex 里会被撑开——固定成两位数的宽度。
   字号/高度跟随「商品类型」输入框（Element Plus default size），故不设 size="small" */
.pos-path__input { flex: 0 0 54px; width: 54px; }
.pos-path__input :deep(.el-input__wrapper) { padding: 0 6px; }
.pos-path__input :deep(.el-input__inner) { text-align: center; }
.pos-path__add { margin-left: 2px; }
</style>
