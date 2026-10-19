<template>
  <!-- 条码冲突提示：同一条码（含各款式 条码-N）已用在别的商品上时，三选一——
       新款式：本商品记成下一个款式号（盲盒不同款等，各自独立、不会被合并；一对一条码随之转为一对多）；
       同款不同品相：沿用所选商品的款式号，本商品另选品相（S/A/J，各自一组图片）；
       同一商品：跳转到选中的原商品（新建的草稿丢弃）。 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('inventory.dupPromptTitle')"
    width="min(560px, 96vw)"
    append-to-body
    @update:model-value="(v) => { if (!v) emit('cancel') }"
  >
    <p class="dp-lead">{{ t('inventory.dupPromptLead', { code: family.code }) }}</p>
    <el-radio-group v-model="targetId" class="dp-list">
      <el-radio v-for="it in family.items" :key="it.id" :value="it.id" class="dp-item">
        <img v-if="it.image" :src="thumb(it.image)" class="dp-thumb" alt="" />
        <span class="dp-text">
          <span class="dp-mono">#{{ it.mgmt_code || it.id }}</span>
          {{ it.name || '-' }}
          <span class="dp-muted">· {{ it.barcode_code || it.product_barcode }}<template v-if="!it.grade"> · {{ t('inventory.gradeUnset') }}</template><template v-if="it.owner_user_name"> · {{ it.owner_user_name }}</template></span>
        </span>
      </el-radio>
    </el-radio-group>
    <p class="dp-question">{{ t('inventory.dupPromptQuestion') }}</p>
    <template #footer>
      <el-button @click="emit('cancel')">{{ t('common.cancel') }}</el-button>
      <el-button type="warning" plain :disabled="!targetId" @click="emit('jump', targetId)">
        {{ t('inventory.dupPromptNo') }}
      </el-button>
      <el-button type="success" plain :disabled="!targetId" @click="emit('grade', targetId)">
        {{ t('inventory.dupPromptGrade') }}
      </el-button>
      <el-button type="primary" @click="emit('multi', family.next_variant)">
        {{ t('inventory.dupPromptYes', { code: `${family.code}-${family.next_variant}` }) }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** /inventory/barcode-family 的返回：{ code, items, multi, next_variant } */
  family: { type: Object, default: () => ({ code: '', items: [], next_variant: 1 }) },
  /** 默认选中的跳转目标（同归属人的优先） */
  defaultTargetId: { type: [Number, String], default: null }
})
const emit = defineEmits(['multi', 'jump', 'grade', 'cancel'])
const { t } = useI18n()

const targetId = ref(null)
watch(
  () => props.modelValue,
  (v) => { if (v) targetId.value = props.defaultTargetId ?? props.family.items?.[0]?.id ?? null }
)

function thumb(path) {
  return String(path).startsWith('/imges/')
    ? `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=120`
    : path
}
</script>

<style scoped>
.dp-lead, .dp-question { margin: 0 0 10px; font-size: 13px; }
.dp-question { margin: 12px 0 0; font-weight: 600; }
.dp-list { display: flex; flex-direction: column; align-items: stretch; gap: 6px; max-height: 300px; overflow: auto; }
.dp-item { height: auto; margin-right: 0; padding: 4px 6px; border-radius: 6px; white-space: normal; }
.dp-item :deep(.el-radio__label) { display: flex; align-items: center; gap: 8px; }
.dp-thumb { width: 40px; height: 40px; object-fit: cover; border-radius: 4px; flex: none; }
.dp-text { line-height: 1.4; }
.dp-mono { font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; }
.dp-muted { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
