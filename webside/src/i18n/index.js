import { createI18n } from 'vue-i18n'
import { ref, computed } from 'vue'
import zhCN from './locales/zh-CN.js'
import ja from './locales/ja.js'
import en from './locales/en.js'

import elZhCn from 'element-plus/es/locale/lang/zh-cn'
import elJa from 'element-plus/es/locale/lang/ja'
import elEn from 'element-plus/es/locale/lang/en'

export const SUPPORTED_LOCALES = ['zh-CN', 'ja', 'en']
export const LOCALE_STORAGE_KEY = 'app_locale'

export const elementLocales = {
  'zh-CN': elZhCn,
  ja: elJa,
  en: elEn,
}

function detectInitialLocale() {
  try {
    const saved = localStorage.getItem(LOCALE_STORAGE_KEY)
    if (saved && SUPPORTED_LOCALES.includes(saved)) return saved
  } catch {}
  const nav = (typeof navigator !== 'undefined' && navigator.language) || ''
  const lower = String(nav).toLowerCase()
  if (lower.startsWith('zh')) return 'zh-CN'
  if (lower.startsWith('ja')) return 'ja'
  if (lower.startsWith('en')) return 'en'
  return 'zh-CN'
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

function deepMerge(target, source) {
  for (const key in source) {
    if (!Object.prototype.hasOwnProperty.call(source, key)) continue
    const sv = source[key]
    if (isPlainObject(sv)) {
      target[key] = isPlainObject(target[key]) ? target[key] : {}
      deepMerge(target[key], sv)
    } else {
      target[key] = sv
    }
  }
  return target
}

const messages = {
  'zh-CN': { ...zhCN },
  ja: { ...ja },
  en: { ...en },
}

// 自动合并各视图目录下的 i18n.js
// 约定: views/**/i18n.js 默认导出 { 'zh-CN': {...}, ja: {...}, en: {...} }
const viewLocaleModules = import.meta.glob('../views/**/i18n.js', { eager: true })
for (const path in viewLocaleModules) {
  const mod = viewLocaleModules[path]?.default || viewLocaleModules[path]
  if (!mod || typeof mod !== 'object') continue
  for (const locale of SUPPORTED_LOCALES) {
    if (mod[locale]) deepMerge(messages[locale], mod[locale])
  }
}

const initialLocale = detectInitialLocale()

const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: initialLocale,
  fallbackLocale: 'zh-CN',
  messages,
  missingWarn: false,
  fallbackWarn: false,
})

export default i18n

export const currentLocale = ref(initialLocale)

/** 文档语言 + 标签页标题跟随语言（index.html 里的 title 只在应用启动前生效） */
function syncDocumentMeta(locale) {
  try {
    document.documentElement.setAttribute('lang', locale)
    document.title = i18n.global.t('layout.logoText')
  } catch {}
}

export function setLocale(locale) {
  if (!SUPPORTED_LOCALES.includes(locale)) return
  i18n.global.locale.value = locale
  currentLocale.value = locale
  try { localStorage.setItem(LOCALE_STORAGE_KEY, locale) } catch {}
  syncDocumentMeta(locale)
}

export const elementLocale = computed(() => elementLocales[currentLocale.value] || elZhCn)

syncDocumentMeta(initialLocale)
