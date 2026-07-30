import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

/** 雅虎（Yahoo!フリマ）只有「おてがる配送」的两家承运商，复用煤炉侧的字段值存库 */
export const YAHOO_SHIPPING_METHODS = ['rakuraku', 'yuuyu']
/** 雅虎默认承运商：日本郵便（出品页自身的默认值） */
export const YAHOO_DEFAULT_SHIPPING_METHOD = 'yuuyu'
/** 煤炉的「未定」发货地（area_id=99）雅虎不支持——雅虎必须选具体都道府県 */
export const MERCARI_UNDECIDED_AREA_ID = '99'

/**
 * 出品表单里的平台差异（煤炉 / 雅虎），供单件与组合出品弹框共用。
 *
 * 雅虎相对煤炉少了三样：
 * - 快递费负担：Yahoo!フリマ 恒为出品者負担（送料込み），字段隐藏；
 * - 販売形式：只有定价即购，没有拍卖，字段隐藏；
 * - 配送方法：只有おてがる配送（ヤマト運輸 / 日本郵便）两项。
 *
 * 选中雅虎账号时把表单里雅虎不支持的取值收敛回合法值，避免提交后在自动化里才失败。
 *
 * @param {import('vue').Ref<Array>} accounts 账号列表（含 platform 字段）
 * @param {import('vue').Ref<Object>} form    出品表单
 */
export function useListingPlatform(accounts, form) {
  const { t } = useI18n()

  const selectedAccount = computed(() => {
    const id = form.value?.mercari_account_id
    if (id === null || id === undefined || id === '') return null
    const list = Array.isArray(accounts.value) ? accounts.value : []
    return list.find((a) => Number(a?.id) === Number(id)) || null
  })

  const isYahoo = computed(() => (selectedAccount.value?.platform || 'mercari') === 'yahoo')

  const yahooShippingMethodOptions = computed(() => [
    { label: t('dialogs.listingPlatform.yahooShippingYamato'), value: 'rakuraku' },
    { label: t('dialogs.listingPlatform.yahooShippingJapanPost'), value: 'yuuyu' },
  ])

  // 切到雅虎账号时收敛不支持的取值（拍卖 → 即购；未定/普通邮件 → 日本郵便）
  watch(isYahoo, (yahoo) => {
    if (!yahoo || !form.value) return
    if (form.value.sale_type && form.value.sale_type !== 'instant_buy') {
      form.value.sale_type = 'instant_buy'
    }
    if (!YAHOO_SHIPPING_METHODS.includes(form.value.shipping_method)) {
      form.value.shipping_method = YAHOO_DEFAULT_SHIPPING_METHOD
    }
  })

  return { selectedAccount, isYahoo, yahooShippingMethodOptions }
}
