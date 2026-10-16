<template>
  <div class="no-access">
    <el-result icon="warning" :title="t('noAccess.title')" :sub-title="t('noAccess.desc')" />
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<style scoped>
.no-access {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 16px;
}
</style>
