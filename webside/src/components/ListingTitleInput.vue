<template>
  <!-- 出品标题输入框 + 关联词下拉（词表在 /system/title-keywords 配置）。
       其余属性（maxlength / show-word-limit / clearable…）原样透传给内部 el-input。 -->
  <div ref="rootRef" class="listing-title-input">
    <el-autocomplete
      :model-value="modelValue"
      value-key="term"
      :fetch-suggestions="fetchSuggestions"
      :trigger-on-focus="false"
      :debounce="120"
      fit-input-width
      popper-class="listing-title-input__popper"
      v-bind="$attrs"
      @update:model-value="onInput"
      @select="onSelect"
    >
      <template #default="{ item }">
        <div class="listing-title-input__item">
          <span class="listing-title-input__term">{{ item.term }}</span>
          <span class="listing-title-input__kw">{{ item.keyword }}</span>
        </div>
      </template>
    </el-autocomplete>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { titleKeywordApi } from '@/api/index.js'
import { loadTitleKeywords, matchTitleKeywords } from '@/utils/titleKeywords.js'

defineOptions({ inheritAttrs: false })

const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])

const rootRef = ref(null)
// 最近一次取候选时的文本与光标位置：选中时 el-autocomplete 会先把整框改成候选词，
// 替换必须基于这份快照，而不是此刻的 modelValue
let snapshot = { value: '', caret: 0 }

function inputEl() {
  return rootRef.value?.querySelector('input') || null
}

function onInput(v) {
  emit('update:modelValue', v)
}

async function fetchSuggestions(query, cb) {
  const value = String(query ?? '')
  const el = inputEl()
  const caret = el && document.activeElement === el && el.selectionStart != null ? el.selectionStart : value.length
  snapshot = { value, caret }
  const rows = await loadTitleKeywords()
  cb(matchTitleKeywords(rows, value.slice(0, caret)))
}

function onSelect(item) {
  const { value, caret } = snapshot
  const start = Math.max(0, caret - (item.matchLen || 0))
  const next = value.slice(0, start) + item.term + value.slice(caret)
  emit('update:modelValue', next)
  const pos = start + item.term.length
  nextTick(() => {
    const el = inputEl()
    if (el) {
      el.focus()
      el.setSelectionRange(pos, pos)
    }
  })
  titleKeywordApi.markUsed(item.id).catch(() => {})
}
</script>

<style scoped>
.listing-title-input,
.listing-title-input :deep(.el-autocomplete) {
  width: 100%;
}
</style>

<style>
.listing-title-input__popper .listing-title-input__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.listing-title-input__popper .listing-title-input__term {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.listing-title-input__popper .listing-title-input__kw {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
