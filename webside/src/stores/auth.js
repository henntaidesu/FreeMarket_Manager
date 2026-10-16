import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { authApi } from '@/api/auth.js'
import { PAGE_KEYS, PAGE_PATHS, pageKeyOf } from '@/constants/menu.js'

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('auth_user') || 'null')
  } catch {
    return null
  }
}

/**
 * 当前登录用户与页面权限（系统角色）。
 *
 * `pages` 为 null/undefined = 不限制（管理员、未分配角色的用户、以及本功能上线前
 * 存下的老 auth_user）。权限真正的强制点在后端 `require_page`；这里只决定菜单与路由，
 * 让人别点进一个满屏 403 的页面。
 */
export const useAuthStore = defineStore('auth', () => {
  const user = ref(readStoredUser())
  /** 本次打开页面后是否已向后端核对过一次（路由守卫首跳会等它） */
  const verified = ref(false)

  const isAdmin = computed(() => Boolean(user.value?.is_admin))
  const pages = computed(() => (Array.isArray(user.value?.pages) ? user.value.pages : null))

  /** path 或页面 key 均可；不在页面清单里的路由（隐藏页等）不受角色控制 */
  function canAccess(pathOrKey) {
    const key = pageKeyOf(pathOrKey)
    if (!PAGE_KEYS.has(key)) return true
    return pages.value === null || pages.value.includes(key)
  }

  /** 按菜单顺序第一个有权限的页面；一个都没有时去 /no-access */
  function firstAllowedPath() {
    return PAGE_PATHS.find((p) => canAccess(p)) || '/no-access'
  }

  function setUser(u) {
    user.value = u || null
    if (u) localStorage.setItem('auth_user', JSON.stringify(u))
    else localStorage.removeItem('auth_user')
  }

  /** 向后端重拉当前用户（角色改了无需重新登录）。失败保留现有数据，401 由拦截器处理。 */
  async function refresh() {
    if (!localStorage.getItem('auth_token')) return user.value
    try {
      setUser(await authApi.me())
    } catch {
      // 静默：网络抖动时沿用本地数据
    } finally {
      verified.value = true
    }
    return user.value
  }

  function clear() {
    setUser(null)
    verified.value = false
  }

  return { user, verified, isAdmin, pages, canAccess, firstAllowedPath, setUser, refresh, clear }
})
