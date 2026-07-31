<template>
  <el-container class="layout-container" direction="horizontal" :class="{ 'layout--mobile': isMobile }">
    <!-- 手机：遮罩 / 菜单按钮挂到 body，避免父级 transform 导致 fixed 失效、被内容盖住 -->
    <Teleport to="body">
      <div
        v-if="isMobile && mobileDrawerOpen"
        class="layout-mobile-mask"
        @click="mobileDrawerOpen = false"
      />
    </Teleport>
    <Teleport to="body">
      <button
        v-if="isMobile && !mobileDrawerOpen"
        type="button"
        class="layout-mobile-fab"
        :aria-label="t('layout.openMenu')"
        aria-expanded="false"
        @click="mobileDrawerOpen = true"
      >
        <el-icon :size="22"><Menu /></el-icon>
      </button>
    </Teleport>

    <!-- 主侧边栏（一级菜单） -->
    <Teleport to="body" :disabled="!isMobile">
      <el-aside
        width="220px"
        class="sidebar"
        :class="{
          'sidebar--mobile': isMobile,
          'sidebar--drawer-open': isMobile && mobileDrawerOpen,
        }"
      >
      <div class="sidebar-inner">
        <div class="logo-area">
          <img
            class="logo-image"
            src="/static/logo.svg"
            :alt="t('layout.logoText')"
          />
          <span class="logo-text">{{ t('layout.logoText') }}</span>
          <el-button
            v-if="isMobile"
            text
            class="sidebar-close-btn"
            @click="mobileDrawerOpen = false"
          >
            <el-icon :size="18"><Close /></el-icon>
          </el-button>
        </div>
        <div class="sidebar-menu-wrap">
          <el-menu
            :default-active="activePrimary"
            :collapse="false"
            background-color="#001529"
            text-color="#a6adb4"
            active-text-color="#ffffff"
            @select="onPrimarySelect"
          >
            <el-menu-item
              v-for="item in menuItems"
              :key="item.path"
              :index="item.path"
              :class="{ 'has-children': !!item.children }"
            >
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>
                <!-- 备忘录移到二级后，未处理数量在收起状态下也要看得见，所以徽标挂到「系统管理」上 -->
                <span
                  v-if="item.path === '/system' && memoUnread > 0"
                  class="menu-title menu-title--badge"
                >
                  {{ t(item.titleKey) }}
                  <span class="memo-badge">{{ memoUnread > 99 ? '99+' : memoUnread }}</span>
                </span>
                <span v-else class="menu-title">{{ t(item.titleKey) }}</span>
                <el-icon
                  v-if="item.children"
                  class="menu-arrow"
                  :class="{ 'menu-arrow--open': secondaryOpen && activeWithChildren === item.path }"
                >
                  <ArrowRight />
                </el-icon>
              </template>
            </el-menu-item>
          </el-menu>
        </div>
        <div class="sidebar-footer">
          <div class="sidebar-lang-row">
            <el-icon :size="14" color="#9ba8bf"><Promotion /></el-icon>
            <el-select
              v-model="locale"
              size="small"
              class="sidebar-lang-select"
              @change="onLocaleChange"
            >
              <el-option
                v-for="lang in localeOptions"
                :key="lang.value"
                :label="lang.label"
                :value="lang.value"
              />
            </el-select>
          </div>
          <div class="sidebar-footer-row">
            <div class="sidebar-footer-user" :title="userName">{{ userName }}</div>
            <el-button class="sidebar-logout-btn" type="danger" plain size="small" @click="handleLogout">
              {{ t('layout.logoutBtn') }}
            </el-button>
          </div>
        </div>
      </div>
    </el-aside>
    </Teleport>

    <!-- 二级侧边栏（位于一级右侧；选中后自动收缩） -->
    <transition name="slide-secondary">
      <el-aside
        v-if="secondaryOpen && currentSecondaryItems.length > 0"
        width="200px"
        class="secondary-sidebar"
      >
        <div class="secondary-header">
          <span class="secondary-title">{{ activePrimaryTitle }}</span>
          <el-button text class="secondary-close" @click="closeSecondary">
            <el-icon :size="16"><Close /></el-icon>
          </el-button>
        </div>
        <div class="secondary-menu-wrap">
          <el-menu
            :default-active="$route.path"
            background-color="#0e1830"
            text-color="#a6adb4"
            active-text-color="#ffffff"
            @select="onSecondarySelect"
          >
            <el-menu-item-group
              v-for="g in currentSecondaryGroups"
              :key="g.key"
              :title="t(g.key)"
            >
              <el-menu-item v-for="c in g.items" :key="c.path" :index="c.path">
                <el-icon><component :is="c.icon" /></el-icon>
                <template #title>
                  <span
                    v-if="c.path === '/system/memos' && memoUnread > 0"
                    class="menu-title menu-title--badge"
                  >
                    {{ t(c.titleKey) }}
                    <span class="memo-badge">{{ memoUnread > 99 ? '99+' : memoUnread }}</span>
                  </span>
                  <span v-else class="menu-title">{{ t(c.titleKey) }}</span>
                </template>
              </el-menu-item>
            </el-menu-item-group>
          </el-menu>
        </div>
      </el-aside>
    </transition>

    <el-main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Menu, Close, ArrowRight, Promotion } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { memosApi } from '@/api/index.js'

const router = useRouter()
const route = useRoute()
const { t, locale } = useI18n()

const localeOptions = computed(() => SUPPORTED_LOCALES.map(code => ({
  value: code,
  label: t(`lang.${code}`),
})))

function onLocaleChange(val) {
  setLocale(val)
}

const isMobile = ref(false)
/** 仅手机端：抽屉侧栏是否打开；电脑端忽略 */
const mobileDrawerOpen = ref(false)

/** 二级菜单是否展开 */
const secondaryOpen = ref(false)
/** 当前正在展开二级面板的一级菜单 path（仅对带 children 的一级有意义） */
const activeWithChildren = ref(null)

/** 备忘录未处理数量（接收方=当前用户且未读），用于一级菜单红色徽标 */
const memoUnread = ref(0)
let memoTimer = null

async function refreshMemoUnread() {
  try {
    const r = await memosApi.unreadCount()
    memoUnread.value = r?.unread || 0
  } catch {
    // 静默：未登录或请求失败时不打扰
  }
}

/** 与库存页等一致：(max-width: 768px) */
let mqMobile = null

function syncMobileFromMedia() {
  if (typeof window === 'undefined' || !mqMobile) return
  const next = mqMobile.matches
  isMobile.value = next
  if (!next) {
    mobileDrawerOpen.value = false
  }
}

onMounted(() => {
  mqMobile = window.matchMedia('(max-width: 768px)')
  syncMobileFromMedia()
  mqMobile.addEventListener('change', syncMobileFromMedia)
  refreshMemoUnread()
  // 周期刷新未处理数量，及时反映其他用户新发来的备忘录
  memoTimer = setInterval(refreshMemoUnread, 30000)
})
onUnmounted(() => {
  mqMobile?.removeEventListener('change', syncMobileFromMedia)
  if (memoTimer) clearInterval(memoTimer)
})

const userName = computed(() => {
  try {
    const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
    return u.display_name || u.username || t('layout.user')
  } catch {
    return t('layout.user')
  }
})

const menuItems = [
  { path: '/dashboard', titleKey: 'layout.menu.dashboard', icon: 'Odometer' },
  { path: '/inventory', titleKey: 'layout.menu.inventory', icon: 'Goods' },
  { path: '/orders', titleKey: 'layout.menu.orders', icon: 'Tickets' },
  { path: '/on-sale-items', titleKey: 'layout.menu.onSaleItems', icon: 'ShoppingBag' },
  { path: '/todos', titleKey: 'layout.menu.todos', icon: 'Check' },
  { path: '/notifications', titleKey: 'layout.menu.notifications', icon: 'Bell' },
  { path: '/shop-accounts', titleKey: 'layout.menu.shopAccounts', icon: 'User' },
  { path: '/tasks', titleKey: 'layout.menu.tasks', icon: 'Loading' },
  {
    path: '/system',
    titleKey: 'layout.menu.system',
    icon: 'Setting',
    // 保持扁平（activePrimary / watch 都按 path 直接查），分组只靠 group 字段，
    // 由 currentSecondaryGroups 按相邻同组折叠出分组标题
    children: [
      { path: '/system/transactions', titleKey: 'layout.menu.transactions', icon: 'List', group: 'layout.menuGroup.records' },
      { path: '/system/settlement', titleKey: 'layout.menu.settlement', icon: 'Coin', group: 'layout.menuGroup.records' },

      { path: '/system/cost-records', titleKey: 'layout.menu.costRecords', icon: 'Money', group: 'layout.menuGroup.packaging' },
      { path: '/system/cost-expenses', titleKey: 'layout.menu.costExpenses', icon: 'Wallet', group: 'layout.menuGroup.packaging' },

      { path: '/system/warehouses', titleKey: 'layout.menu.warehouses', icon: 'OfficeBuilding', group: 'layout.menuGroup.masterData' },
      { path: '/system/categories', titleKey: 'layout.menu.categories', icon: 'Collection', group: 'layout.menuGroup.masterData' },
      { path: '/system/product-type-category-mappings', titleKey: 'layout.menu.productTypeMappings', icon: 'Connection', group: 'layout.menuGroup.masterData' },

      { path: '/system/talk-scripts', titleKey: 'layout.menu.talkScripts', icon: 'ChatLineRound', group: 'layout.menuGroup.collaboration' },
      { path: '/system/memos', titleKey: 'layout.menu.memos', icon: 'ChatDotRound', group: 'layout.menuGroup.collaboration' },

      { path: '/system/config', titleKey: 'layout.menu.systemConfig', icon: 'Tools', group: 'layout.menuGroup.maintenance' },
      { path: '/system/system-logs', titleKey: 'layout.menu.systemLogs', icon: 'Document', group: 'layout.menuGroup.maintenance' }
    ]
  }
]

/** 当前路由所属的一级菜单 path（用于一级 active 高亮） */
const activePrimary = computed(() => {
  for (const item of menuItems) {
    if (item.children) {
      if (item.children.some(c => c.path === route.path)) return item.path
      if (item.path === route.path) return item.path
    } else if (item.path === route.path) {
      return item.path
    }
  }
  return route.path
})

/** 当前展开的二级菜单项列表 */
const currentSecondaryItems = computed(() => {
  if (!activeWithChildren.value) return []
  const found = menuItems.find(m => m.path === activeWithChildren.value)
  return found?.children || []
})

/** 二级菜单按 group 折叠成 [{ key, items }]，相邻同组合并 */
const currentSecondaryGroups = computed(() => {
  const groups = []
  for (const item of currentSecondaryItems.value) {
    const last = groups[groups.length - 1]
    if (last && last.key === item.group) last.items.push(item)
    else groups.push({ key: item.group, items: [item] })
  }
  return groups
})

const activePrimaryTitle = computed(() => {
  const found = menuItems.find(m => m.path === activeWithChildren.value)
  return found ? t(found.titleKey) : ''
})

function onPrimarySelect(path) {
  const item = menuItems.find(m => m.path === path)
  if (!item) return

  if (item.children) {
    // 一级带 children：切换二级面板展开状态，不跳路由
    if (activeWithChildren.value === path) {
      secondaryOpen.value = !secondaryOpen.value
    } else {
      activeWithChildren.value = path
      secondaryOpen.value = true
    }
  } else {
    // 普通一级菜单：关闭二级，跳转
    secondaryOpen.value = false
    activeWithChildren.value = null
    if (route.path !== path) router.push(path)
    if (isMobile.value) mobileDrawerOpen.value = false
  }
}

function onSecondarySelect(path) {
  if (route.path !== path) router.push(path)
  // 选中二级后自动收缩
  secondaryOpen.value = false
  if (isMobile.value) mobileDrawerOpen.value = false
}

function closeSecondary() {
  secondaryOpen.value = false
}

/** 直接通过 URL 进入二级页时：高亮一级 + 初始化 activeWithChildren（但不展开二级面板） */
watch(
  () => route.path,
  (p) => {
    const owner = menuItems.find(item => item.children && item.children.some(c => c.path === p))
    if (owner) {
      activeWithChildren.value = owner.path
    }
    // 切换路由时刷新未处理数量（例如在 /system/memos 处理完返回其它页）
    refreshMemoUnread()
  },
  { immediate: true }
)

const handleLogout = async () => {
  await ElMessageBox.confirm(t('layout.logoutConfirm'), t('common.tip'), {
    type: 'warning',
    confirmButtonText: t('layout.logoutBtn'),
    cancelButtonText: t('common.cancel'),
  })
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  router.replace('/login')
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  background: #0f1728;
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 二级侧边栏：位于主侧边栏右侧，深色稍浅，with 200px */
.secondary-sidebar {
  background: #0e1830;
  border-left: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.secondary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  color: #b8c4d0;
  font-size: 14px;
  font-weight: 600;
}

.secondary-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.secondary-close {
  color: #a6adb4 !important;
  padding: 4px !important;
  flex-shrink: 0;
}

.secondary-menu-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 二级菜单分组标题：深色侧栏里 Element 默认的浅灰太浅，且组间需要留白 */
.secondary-menu-wrap :deep(.el-menu-item-group__title) {
  padding: 14px 16px 4px;
  color: #6b7a90;
  font-size: 12px;
  line-height: 1.2;
  letter-spacing: 0.5px;
}

.secondary-menu-wrap :deep(.el-menu-item-group:first-child .el-menu-item-group__title) {
  padding-top: 8px;
}

/* 二级菜单滑入/滑出动画 */
.slide-secondary-enter-active,
.slide-secondary-leave-active {
  transition: width 0.22s cubic-bezier(0.32, 0.72, 0, 1), opacity 0.18s ease;
}
.slide-secondary-enter-from,
.slide-secondary-leave-to {
  width: 0 !important;
  opacity: 0;
}

/* 手机：抽屉侧栏从左侧滑入 */
.sidebar--mobile {
  position: fixed !important;
  left: 0;
  top: 0;
  bottom: 0;
  width: min(220px, 85vw) !important;
  max-width: 220px;
  z-index: 5010;
  transform: translate3d(-100%, 0, 0);
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
  box-shadow: none;
  will-change: transform;
}

.sidebar--mobile.sidebar--drawer-open {
  transform: translate3d(0, 0, 0);
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.45);
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.sidebar-menu-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 12px 14px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-lang-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.sidebar-lang-select {
  flex: 1;
  width: auto !important;
}

.sidebar-lang-select :deep(.el-select__wrapper) {
  background: #131c2f !important;
}

.sidebar-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
}

.sidebar-footer-user {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #9ba8bf;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-logout-btn {
  flex-shrink: 0;
  margin: 0 !important;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: nowrap;
  overflow: hidden;
}

.logo-image {
  width: 40px;
  height: 40px;
  object-fit: contain;
  flex-shrink: 0;
}

.logo-text {
  flex: 1;
  min-width: 0;
  color: #b8c4d0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
  overflow: hidden;
  /* 侧栏 220px 放不下一行「FreeMarket Manager」，允许折成两行 */
  white-space: normal;
  line-height: 1.15;
}

.sidebar-close-btn {
  flex-shrink: 0;
  color: #a6adb4 !important;
  padding: 4px !important;
  margin-left: auto;
}

:deep(.el-menu) {
  border-right: none;
}

:deep(.el-menu-item.is-active) {
  background-color: #1890ff !important;
  border-radius: 6px;
  margin: 2px 8px;
  width: calc(100% - 16px);
}

:deep(.el-menu-item) {
  border-radius: 6px;
  margin: 2px 8px;
  width: calc(100% - 16px);
}

/* 一级菜单中带 children 的项：在 title 右侧显示箭头 */
:deep(.el-menu-item.has-children .el-tooltip__trigger),
:deep(.el-menu-item.has-children) {
  position: relative;
}

.menu-title {
  flex: 1;
  min-width: 0;
}

/* 备忘录未处理徽标：红色圆圈显示在菜单文字右侧（一级「系统管理」+ 二级「备忘录」） */
.menu-title--badge {
  flex: 0 0 auto;
  position: relative;
  overflow: visible;
}
.memo-badge {
  position: absolute;
  top: 50%;
  right: -30px;
  transform: translateY(-50%);
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  box-sizing: border-box;
  border-radius: 9px;
  background: #f56c6c;
  color: #fff;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  white-space: nowrap;
  pointer-events: none;
}

.menu-arrow {
  margin-left: auto;
  font-size: 12px;
  transition: transform 0.2s ease;
  color: #9ba8bf;
}

.menu-arrow--open {
  transform: rotate(90deg);
}

.main-content {
  flex: 1;
  overflow-y: auto;
  background: #0b1220;
  padding: 20px;
  min-width: 0;
}

@media (max-width: 767px) {
  .main-content {
    padding: 12px;
    padding-top: 56px;
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

<!-- Teleport 到 body，不能用 scoped，单独挂类名 -->
<style>
.layout-mobile-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 5000;
}
.layout-mobile-fab {
  position: fixed;
  left: max(12px, env(safe-area-inset-left, 0px));
  top: max(12px, env(safe-area-inset-top, 0px));
  z-index: 5020;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #121b2e;
  border: 1px solid #253149;
  color: #ecf2ff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.45);
  padding: 0;
}
.layout-mobile-fab:active {
  opacity: 0.92;
}
</style>
