<template>
  <el-config-provider :locale="elementLocale">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { ElConfigProvider } from 'element-plus'
import { elementLocale } from '@/i18n'
</script>

<style>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root.dark {
  color-scheme: dark;
}

/* ===== 视口高度单位：一律用 var(--app-vh)，不要直接写 vh =====
   移动端（iPad / 手机）浏览器的地址栏、工具栏会遮住视口底部，而 1vh 取的是
   「工具栏全部收起」时的大视口，比实际可见区域高——按 100vh 定高的页面因此
   总比屏幕高出一截，必须往下拉才能看全；各家浏览器工具栏高度不同，多出来的
   那一截也不一样，这就是「不同浏览器打开高度不一样」的原因。
   dvh 取的是当前实际可见高度，浏览器自己会随工具栏显隐更新，天然自适应。
   不支持 dvh 的旧浏览器落回 vh，行为与改动前一致。 */
:root {
  --app-vh: 1vh;
}

@supports (height: 1dvh) {
  :root {
    --app-vh: 1dvh;
  }
}

/* 与暗色主题对齐：避免统计卡片、表格卡片出现浅色底 / 白屏 loading */
html.dark {
  --el-bg-color: #0b1220;
  --el-bg-color-page: #0b1220;
  --el-fill-color-blank: #131c2f;
  --el-fill-color-light: #18233a;
  --el-mask-color: rgba(11, 18, 32, 0.78);
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  background: #0b1220;
  color: #e5e7eb;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-thumb {
  background: #3a4456;
  border-radius: 3px;
}
::-webkit-scrollbar-track {
  background: transparent;
}

.page-title {
  color: #e6edf7 !important;
}

.el-card,
.el-dialog,
.el-table,
.el-input__wrapper,
.el-select__wrapper,
.el-textarea__inner {
  border-color: #2a3446 !important;
}

.el-card {
  background: #131c2f !important;
  color: #e6edf7;
}

.el-card__header {
  background: #161f33 !important;
  border-bottom: 1px solid #28354a !important;
  color: #e6edf7 !important;
}

.el-card__body {
  background: transparent !important;
  color: #e6edf7;
}

.el-loading-mask {
  background-color: var(--el-mask-color) !important;
}

.el-loading-mask .el-loading-spinner .path {
  stroke: #8fb8ff;
}

.el-table {
  --el-table-header-bg-color: #18233a;
  --el-table-tr-bg-color: #131c2f;
  --el-table-row-hover-bg-color: #1b2942;
  --el-table-border-color: #28354a;
  color: #d6deea;
}

.el-dialog {
  --el-dialog-bg-color: #131c2f;
}

.el-input,
.el-select,
.el-date-editor.el-input__wrapper,
.el-date-editor.el-input {
  width: 180px !important;
}

.el-range-editor.el-input__wrapper,
.el-date-editor--daterange {
  width: 180px !important;
  min-width: 180px !important;
}
</style>
