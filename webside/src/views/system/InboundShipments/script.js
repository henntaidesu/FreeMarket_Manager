import { defineComponent, ref, computed, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { inboundShipmentApi, inventoryApi, warehouseApi } from '@/api/index.js'
import { useBarcodeScanner } from '@/composables/useBarcodeScanner.js'
import { parseWarehouseQr } from '@/utils/warehouseQr.js'

/**
 * 快递入库：商品从国内邮寄到日本，按快递单管理「在途 → 到岸扫码上架」。业务口径见后端 src/inbound_shipments。
 *
 * 扫码入库（扫码枪 / 手动输入）的状态机：
 *   idle        —— 等扫商品条码。命中且有建议货架 → 立刻入库 1 件并大字显示货架号；
 *                  没有建议货架 → need-shelf；一码多品 → pick。
 *   need-shelf  —— 等扫货架码，扫到即把这件入库到该货架。
 *   pick        —— 一码多品，点选是哪一件。
 * 任何时候扫货架码且上一条入库记录还在 → 把上一条改投到新货架（货架满了的情况）。
 * 建议货架按商品记（后端取该商品最近一条入库记录的货架），所以改投一次后它以后都进新货架。
 */
export default defineComponent({
  setup() {
    const { t } = useI18n()

    // ---------- 列表 ----------
    const list = ref([])
    const total = ref(0)
    const statusCounts = ref({})
    const loading = ref(false)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({ status: '', keyword: '' })
    const STATUS_LIST = ['draft', 'shipped', 'arrived', 'closed']
    const statusTag = { draft: 'info', shipped: 'warning', arrived: 'primary', closed: 'success' }

    async function load() {
      loading.value = true
      try {
        const params = { page: page.value, page_size: pageSize.value }
        if (filters.value.status) params.status = filters.value.status
        if (filters.value.keyword) params.keyword = filters.value.keyword
        const res = await inboundShipmentApi.list(params)
        list.value = res.items || []
        total.value = res.total || 0
        statusCounts.value = res.status_counts || {}
      } finally {
        loading.value = false
      }
    }

    function search() {
      page.value = 1
      load()
    }

    function thumbUrl(src, size = 120) {
      if (!src || !src.startsWith('/imges/')) return src
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(src)}&size=${size}`
    }

    // ---------- 详情（装箱 / 编辑） ----------
    const detailVisible = ref(false)
    const detail = ref(null)
    const header = ref({ tracking_no: '', carrier: '', remark: '' })
    const busy = ref(false)
    const addPickId = ref(null)
    const addQty = ref(1)
    const addOptions = ref([])
    const addSearching = ref(false)

    function applyDetail(d) {
      detail.value = d
      header.value = { tracking_no: d.tracking_no || '', carrier: d.carrier || '', remark: d.remark || '' }
    }

    async function openDetail(id) {
      applyDetail(await inboundShipmentApi.get(id))
      addPickId.value = null
      addQty.value = 1
      addOptions.value = []
      detailVisible.value = true
    }

    async function createShipment() {
      const d = await inboundShipmentApi.create({})
      applyDetail(d)
      addOptions.value = []
      detailVisible.value = true
      load()
    }

    async function saveHeader() {
      if (!detail.value) return
      applyDetail(await inboundShipmentApi.update(detail.value.id, header.value))
      ElMessage.success(t('inbound.saved'))
      load()
    }

    async function searchInventory(keyword) {
      const kw = String(keyword || '').trim()
      if (!kw) {
        addOptions.value = []
        return
      }
      addSearching.value = true
      try {
        const res = await inventoryApi.list({ keyword: kw, page: 1, page_size: 20 })
        addOptions.value = (res.items || []).filter((it) => Number(it.is_combined || 0) !== 1)
      } finally {
        addSearching.value = false
      }
    }

    function lineOf(inventoryId) {
      return (detail.value?.lines || []).find((l) => Number(l.inventory_id) === Number(inventoryId))
    }

    async function setLineQty(inventoryId, qty) {
      applyDetail(await inboundShipmentApi.setLine(detail.value.id, inventoryId, qty))
      load()
    }

    async function addLine() {
      if (!addPickId.value || !(addQty.value > 0)) return
      const cur = lineOf(addPickId.value)
      await setLineQty(addPickId.value, (cur ? cur.qty_shipped : 0) + addQty.value)
      addPickId.value = null
      addQty.value = 1
    }

    /** 装箱中扫商品条码：装箱数 +1（一码多品时放进下拉让人选） */
    async function addByBarcode(code) {
      const family = await inventoryApi.barcodeFamily(code)
      const items = family?.items || []
      if (!items.length) {
        beep(false)
        ElMessage.warning(t('inbound.codeUnknown', { code }))
      } else if (items.length === 1) {
        const cur = lineOf(items[0].id)
        await setLineQty(items[0].id, (cur ? cur.qty_shipped : 0) + 1)
        beep(true)
      } else {
        addOptions.value = items
        addPickId.value = null
        ElMessage.info(t('inbound.pickVariant'))
      }
    }

    async function runAction(fn, okKey) {
      busy.value = true
      try {
        const d = await fn(detail.value.id)
        if (d && d.id) applyDetail(d)
        if (okKey) ElMessage.success(t(okKey))
        load()
        return d
      } finally {
        busy.value = false
      }
    }

    async function shipShipment() {
      await ElMessageBox.confirm(t('inbound.shipConfirm', { n: totalShipped.value }), t('inbound.ship'), { type: 'warning' })
      await runAction(inboundShipmentApi.ship, 'inbound.shipped')
    }

    async function unshipShipment() {
      await ElMessageBox.confirm(t('inbound.unshipConfirm'), t('inbound.unship'), { type: 'warning' })
      await runAction(inboundShipmentApi.unship, 'inbound.unshipped')
    }

    const arriveShipment = () => runAction(inboundShipmentApi.arrive, 'inbound.arrivedOk')

    async function closeShipment() {
      const pending = (detail.value?.lines || []).filter((l) => l.qty_pending > 0)
      const msg = pending.length
        ? t('inbound.closeConfirmLost', {
            items: pending.map((l) => `${l.name || l.mgmt_code} × ${l.transit_quantity}`).join('、')
          })
        : t('inbound.closeConfirm')
      await ElMessageBox.confirm(msg, t('inbound.close'), { type: 'warning' })
      await runAction(inboundShipmentApi.close, 'inbound.closedOk')
      scanVisible.value = false
    }

    async function deleteShipment() {
      await ElMessageBox.confirm(t('inbound.deleteConfirm'), t('common.delete'), { type: 'warning' })
      await inboundShipmentApi.remove(detail.value.id)
      detailVisible.value = false
      load()
    }

    const totalShipped = computed(() => (detail.value?.lines || []).reduce((s, l) => s + l.qty_shipped, 0))
    const totalReceived = computed(() => (detail.value?.lines || []).reduce((s, l) => s + l.qty_received, 0))

    // ---------- 扫码入库 ----------
    const scanVisible = ref(false)
    const scanState = ref('idle')
    const scanPending = ref(null)
    const scanCandidates = ref([])
    const scanLast = ref(null)
    const scanError = ref('')
    const scanQty = ref(1)
    const scanInput = ref('')
    const scanInputRef = ref(null)
    const receipts = ref([])
    const warehouses = ref([])
    let scanQueue = Promise.resolve()

    const scanLines = computed(() => detail.value?.lines || [])

    function shelfText(shelf) {
      if (!shelf) return ''
      return [shelf.warehouse, shelf.label].filter(Boolean).join(' / ')
    }

    async function loadReceipts() {
      if (!detail.value) return
      const res = await inboundShipmentApi.receipts(detail.value.id, 20)
      receipts.value = res.items || []
    }

    async function openScan(id) {
      applyDetail(await inboundShipmentApi.get(id))
      if (!['shipped', 'arrived'].includes(detail.value.status)) {
        ElMessage.warning(t('inbound.notReceivable'))
        return
      }
      scanState.value = 'idle'
      scanPending.value = null
      scanCandidates.value = []
      scanLast.value = null
      scanError.value = ''
      scanQty.value = 1
      detailVisible.value = false
      scanVisible.value = true
      loadReceipts()
      focusScanInput()
    }

    function focusScanInput() {
      nextTick(() => scanInputRef.value?.focus())
    }

    function fail(msg) {
      scanError.value = msg
      beep(false)
    }

    async function receiveLine(line, warehouseId) {
      const qty = Math.max(1, Math.min(Number(scanQty.value) || 1, line.qty_pending))
      try {
        const res = await inboundShipmentApi.receive(detail.value.id, {
          inventory_id: line.inventory_id,
          warehouse_id: warehouseId,
          quantity: qty
        })
        scanLast.value = {
          receipt_id: res.receipt_id,
          inventory_id: line.inventory_id,
          name: line.name,
          image: line.image,
          quantity: res.quantity,
          shelf: shelfText(res.shelf),
          received: res.line.qty_received,
          shipped: res.line.qty_shipped,
          moved: false
        }
        scanError.value = ''
        scanState.value = 'idle'
        scanPending.value = null
        scanQty.value = 1
        beep(true)
        applyDetail(await inboundShipmentApi.get(detail.value.id))
        loadReceipts()
        load()
        if (res.closed) ElMessage.success(t('inbound.autoClosed'))
      } catch (e) {
        fail(e?.response?.data?.detail || e?.message || t('inbound.receiveFailed'))
      }
    }

    /** 选定了是哪一行：有建议货架直接入库，否则等货架码 */
    async function pickLine(line) {
      if (line.qty_pending <= 0) {
        fail(t('inbound.lineDone', { name: line.name }))
        scanState.value = 'idle'
        return
      }
      scanCandidates.value = []
      if (line.suggested_shelf) {
        await receiveLine(line, line.suggested_shelf.id)
      } else {
        scanPending.value = line
        scanState.value = 'need-shelf'
        scanError.value = ''
      }
    }

    async function handleShelfCode(wid) {
      if (scanState.value === 'need-shelf' && scanPending.value) {
        await receiveLine(scanPending.value, wid)
        return
      }
      if (scanState.value === 'pick') {
        fail(t('inbound.finishPickFirst'))
        return
      }
      if (!scanLast.value) {
        fail(t('inbound.scanProductFirst'))
        return
      }
      // 货架满了：上一条改投到新货架
      try {
        const res = await inboundShipmentApi.relocate(scanLast.value.receipt_id, wid)
        scanLast.value = { ...scanLast.value, shelf: shelfText(res.shelf), moved: res.moved || scanLast.value.moved }
        scanError.value = ''
        beep(true)
        loadReceipts()
      } catch (e) {
        fail(e?.response?.data?.detail || e?.message || t('inbound.relocateFailed'))
      }
    }

    async function handleProductCode(code) {
      if (scanState.value !== 'idle') {
        fail(t(scanState.value === 'need-shelf' ? 'inbound.needShelfFirst' : 'inbound.finishPickFirst'))
        return
      }
      let res
      try {
        res = await inboundShipmentApi.match(detail.value.id, code)
      } catch (e) {
        fail(e?.response?.data?.detail || t('inbound.receiveFailed'))
        return
      }
      const lines = res.lines || []
      if (!lines.length) {
        if (!res.known) fail(t('inbound.codeUnknown', { code }))
        else if (res.elsewhere?.length) {
          fail(t('inbound.codeElsewhere', {
            code,
            no: res.elsewhere.map((s) => s.tracking_no || `#${s.id}`).join('、')
          }))
        } else fail(t('inbound.codeNotInShipment', { code }))
        return
      }
      const open = lines.filter((l) => l.qty_pending > 0)
      if (open.length === 1) return pickLine(open[0])
      if (!open.length) return fail(t('inbound.lineDone', { name: lines[0].name }))
      scanCandidates.value = open
      scanState.value = 'pick'
      scanError.value = ''
    }

    function processScanCode(code) {
      scanQueue = scanQueue.then(() => {
        const wid = parseWarehouseQr(code)
        return wid != null ? handleShelfCode(wid) : handleProductCode(code)
      }).catch(() => {})
      return scanQueue
    }

    function submitScanInput() {
      const code = String(scanInput.value || '').trim()
      scanInput.value = ''
      if (code) processScanCode(code)
    }

    function cancelPending() {
      scanState.value = 'idle'
      scanPending.value = null
      scanCandidates.value = []
      scanError.value = ''
      focusScanInput()
    }

    /** 手动改投：选一个货架号（扫码枪不在手边时用） */
    async function relocateTo(wid) {
      if (wid) await handleShelfCode(wid)
    }

    const shelfOptions = computed(() =>
      (warehouses.value || [])
        .filter((w) => (w.node_type ? w.node_type === 'shelf_no' : String(w.name || '').trim() !== ''))
        .map((w) => ({
          id: w.id,
          label: [w.warehouse, w.shelf_name, w.name].map((s) => String(s || '').trim()).filter(Boolean).join(' / ')
        }))
    )

    // ---------- 扫码枪路由：哪个界面开着就交给谁 ----------
    async function onScannerCode(code, focusedEl) {
      if (focusedEl) {
        // 扫进了 [data-scanner-capture] 的输入框：字符已经进了框里。数量框失焦会把它提交成数量，
        // 提交后再改回原值；手动输入框直接清空（条码由这里处理，不再走它自己的回车）
        const keepQty = scanQty.value
        focusedEl.blur()
        scanQty.value = keepQty
        scanInput.value = ''
      }
      if (scanVisible.value) return processScanCode(code)
      if (detailVisible.value) {
        if (detail.value?.status === 'draft' && parseWarehouseQr(code) == null) return addByBarcode(code)
        return
      }
      // 列表页扫面单：直接打开那个快递单的扫码入库
      const res = await inboundShipmentApi.lookup(code)
      const items = (res.items || []).filter((s) => ['shipped', 'arrived'].includes(s.status))
      if (items.length) return openScan(items[0].id)
      ElMessage.warning(t('inbound.trackingNotFound', { code }))
    }
    useBarcodeScanner(onScannerCode)

    // 成功 / 失败提示音：拆箱时眼睛在货上，听声音就知道这一下成没成
    let audioCtx = null
    function beep(ok) {
      try {
        audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)()
        const osc = audioCtx.createOscillator()
        const gain = audioCtx.createGain()
        osc.frequency.value = ok ? 1200 : 300
        gain.gain.value = 0.15
        osc.connect(gain)
        gain.connect(audioCtx.destination)
        osc.start()
        osc.stop(audioCtx.currentTime + (ok ? 0.08 : 0.35))
      } catch {
        // 没有音频设备：静默
      }
    }

    onMounted(async () => {
      load()
      try { warehouses.value = await warehouseApi.list() } catch { /* 拦截器已提示 */ }
    })

    return {
      t,
      // 列表
      list, total, statusCounts, loading, page, pageSize, filters, STATUS_LIST, statusTag, load, search, thumbUrl,
      // 详情
      detailVisible, detail, header, busy, addPickId, addQty, addOptions, addSearching, totalShipped, totalReceived,
      openDetail, createShipment, saveHeader, searchInventory, setLineQty, addLine,
      shipShipment, unshipShipment, arriveShipment, closeShipment, deleteShipment,
      // 扫码入库
      scanVisible, scanState, scanPending, scanCandidates, scanLast, scanError, scanQty, scanInput, scanInputRef,
      scanLines, receipts, shelfOptions, openScan, pickLine, submitScanInput, cancelPending, relocateTo,
      focusScanInput,
    }
  },
})
