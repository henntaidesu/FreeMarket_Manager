import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/** 全局唯一的视图偏好键。原来五个列表页各存各的（mercari.<page>.viewMode），
 *  改成全局开关后合并成这一个——旧键不再读写，留在 localStorage 里也无害。 */
const STORAGE_KEY = 'mercari.viewMode'

function readPreference() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'card' ? 'card' : 'table'
  } catch {
    return 'table'
  }
}

/**
 * 列表页「表格 / 卡片」视图偏好，库存 / 订单 / 在售商品 / 待办 / 通知 五页共用一份。
 *
 * 切换入口只有侧边栏底部那一个，页面内不再各自摆开关。各页只读 ``isCardView``；
 * 需要在切换时重新拉数据的页面（四个带滚动窗口的列表）自己 watch ``mode``——
 * 各页切换后的收尾动作并不相同（收起内联编辑、收起展开行、重置页码），
 * 塞进 store 只会让 store 知道太多页面细节。
 */
export const useViewModeStore = defineStore('viewMode', () => {
  const mode = ref(readPreference())
  const isCardView = computed(() => mode.value === 'card')

  function setMode(next) {
    const v = next === 'card' ? 'card' : 'table'
    if (v === mode.value) return
    mode.value = v
    try {
      localStorage.setItem(STORAGE_KEY, v)
    } catch {
      /* 隐私模式下写不进去，本次会话内仍然生效 */
    }
  }

  return { mode, isCardView, setMode }
})
