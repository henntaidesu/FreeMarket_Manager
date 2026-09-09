import http from './http'

// 待办事项（本地缓存 services/todolist/v1/list）→ /mercariV2/src/use_web/todos/*
export const todosApi = {
  list: (params) => http.get('/use_web/todos', { params }),
  kinds: () => http.get('/use_web/todos/kinds'),
  /** 顶部筛选各 chip 的条数（与列表同一套过滤条件） */
  chipCounts: (params) => http.get('/use_web/todos/chip-counts', { params }),
  /** 「発送をしてください」处理：按商品 ID 反查本地库存（图片）与关联订单号 */
  matchInventory: (itemId, axiosConfig = {}) =>
    http.get('/use_web/todos/inventory-match', { params: { item_id: itemId }, ...axiosConfig }),
  /** 旧数据按需翻译：把单条消息日译中并写回 text_zh，返回 { ok, text_zh } */
  translateMessage: (payload, axiosConfig = {}) =>
    http.post('/use_web/todos/translate-message', payload, { timeout: 20000, ...axiosConfig }),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/todos/sync', data, { timeout: 0, ...axiosConfig }),
  /** 与 sync 的 progress_job_id 配合，轮询当前同步步骤 */
  getSyncProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/todos/sync-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  /** 处理按钮：打开浏览器到 transaction 页并抓取 DOM 字段 */
  fetchTransactionDetail: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/transaction-detail`, body || {}, { timeout: 0, ...axiosConfig }),
  /** 交易详情缓存：读本地 DB 缓存（不开浏览器），打开「处理」面板时优先用 */
  transactionDetailCache: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/transaction-detail-cache`, { timeout: 20000, ...axiosConfig }),
  /** 关闭交易详情 dialog 时关掉对应账号的 __auto 浏览器（fire-and-forget） */
  closeDetailBrowser: (accountId, axiosConfig = {}) =>
    http.post(`/use_web/todos/close-detail-browser/${encodeURIComponent(accountId)}`, {}, { timeout: 0, ...axiosConfig }),
  /** 填回复并点击「取引メッセージを送る」；浏览器未开时后端会自动打开交易页再发送（故不设超时） */
  sendTransactionMessage: (todoId, text, opts = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/send-message`, { text, ...opts }, { timeout: 0, ...axiosConfig }),
  /** 对买家某条消息发送 emoji 反应（reaction_index = 在 is_buyer 消息中的索引） */
  sendMessageReaction: (todoId, payload, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/send-reaction`, payload, { timeout: 60000, ...axiosConfig }),
  /** 取引評価页：选 rating（good=良かった / bad=残念だった）+ 填评价，
   *  再点「購入者を評価して取引完了する」。rating 走 opts 传入 */
  submitTransactionReview: (todoId, text, opts = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/submit-review`, { text, ...opts }, { timeout: 60000, ...axiosConfig }),
  /** 买家侧「确认收货」（受取評価）：勾选已确认收到 + 选 rating（good=良かった / bad=残念だった）
   *  + 填评价，点「評価を投稿する」。仅 kind=Shipped + title=受取評価をしてください 命中，无二次确认 */
  confirmBuyerReceipt: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/confirm-receipt`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 退货「确认签收」：点「返送された商品を受け取った」+ 二次确认「キャンセルを完了する」，
   *  完成后软删待办并刷新订单。后端自带开浏览器 → 不设超时。 */
  confirmCancellationReceipt: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/confirm-cancellation-receipt`, body || {}, { timeout: 0, ...axiosConfig }),
  /** 一键好评：后端按账号分组、复用浏览器逐条提交评价（不设超时，进度走 sync-progress 轮询） */
  bulkSubmitReviews: (body = {}, axiosConfig = {}) =>
    http.post('/use_web/todos/bulk-review', body || {}, { timeout: 0, ...axiosConfig }),
  /** 一键确认发送：后端按账号分组、复用浏览器对「已打包」逐条确认发送（不设超时，进度走 sync-progress 轮询） */
  bulkFinalizePostShipping: (body = {}, axiosConfig = {}) =>
    http.post('/use_web/todos/bulk-confirm-ship', body || {}, { timeout: 0, ...axiosConfig }),
  /** 点「商品サイズと発送場所を選択する」→ 抓 shipping_classes → 返回可选项 */
  startShippingClass: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/start`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 提交所选 size+facility：浏览器内完成全套点击（ゆうパケットポスト系传 scan_qr=true 完了后自动打开二维码扫描页） */
  confirmShippingSelection: (todoId, data, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/confirm`, data, { timeout: 60000, ...axiosConfig }),
  /** QR 扫描页镜像：抓取有头浏览器当前标签页一帧（base64 JPEG）+ 完成状态 */
  qrScannerFrame: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/qr-scanner-frame`, { timeout: 20000, ...axiosConfig }),
  /** 远程摄像头：上传客户端摄像头一帧（data URL）到有头浏览器的虚拟摄像头 + 取回扫描状态 */
  /** 发货扫码：提交一张含二维码的照片 → 后端校验并入队后台执行（不阻塞页面） */
  scanQrPhoto: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/scan-qr-photo`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 发货扫码失败后重试：照片与解出的码都还在库里，直接重新入队，不用重拍 */
  retryShipQr: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/retry-ship-qr`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 虚拟发货收尾：实物真的投出去了 → 本单结束。平台侧早在虚拟发货那步就发完了，
   *  这里是纯本地写，不开浏览器 */
  confirmActualShipped: (todoId, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/confirm-actual-shipped`, {}, { timeout: 20000, ...axiosConfig }),
  cameraFrame: (todoId, data, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/camera-frame`, data || {}, { timeout: 15000, ...axiosConfig }),
  /** QR 读取成功后读取「発送確認符号 / 追跡番号」供二次确认 */
  postShippingInfo: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/post-shipping-info`, { timeout: 30000, ...axiosConfig }),
  /** 用户二次确认后：勾选シール → 发送通知 → 「発送しました」 */
  finalizePostShipping: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/finalize-post-shipping`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 点「発送方法を変更する」→ 跳到 /shipping_method 并返回可选配送方式（radio）选项 */
  changeShippingMethod: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/change-method`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 在 /shipping_method 页选中指定配送方式并点「変更する」 */
  confirmChangeShippingMethod: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/confirm-change-method`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」+ 二次确认，清除二维码 */
  reviseShippingAfterQr: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/revise-after-qr`, body || {}, { timeout: 60000, ...axiosConfig }),

  // ── 雅虎待办：交易页上一张三项发货表单 + 留言框，与煤炉的多步流程各走各的端点 ──
  /** 读上次抓到的雅虎交易详情（不开浏览器） */
  yahooTradeDetailCache: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/trade-detail-cache`, { timeout: 20000, ...axiosConfig }),
  /** 打开雅虎交易页抓详情（含发货表单当前可选的尺寸/发货场所） */
  yahooTradeDetail: (todoId, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/trade-detail`, {}, { timeout: 0, ...axiosConfig }),
  /** 提交发货信息并发行配送コード（dry_run 只校验不提交）。
   *  尺寸为 ゆうパケットポスト / mini 时后端自动改走 App API，需一并传 material_image（二维码照片） */
  yahooShip: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/ship`, body || {}, { timeout: 0, ...axiosConfig }),
  /** 投函型（ゆうパケットポスト / mini）发货：提交一张二维码照片 → 后端校验并入队后台执行
   *  （发行配送コード → 発送通知 → 刷订单 → 软删待办），与煤炉的 scanQrPhoto 同一形态 */
  yahooShipQr: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/ship-qr`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 発送通知失败后的手动补发（正常路径下发货任务已经通知过了） */
  yahooNotifyShipped: (todoId, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/notify-shipped`, {}, { timeout: 0, ...axiosConfig }),
  /** 给买家发一条雅虎取引メッセージ */
  yahooSendMessage: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/send-message`, body || {}, { timeout: 0, ...axiosConfig }),
  /** 雅虎待回复：直接标记处理完毕（软删）。纯本地写，不开浏览器 */
  yahooFinishReply: (todoId, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/yahoo/finish-reply`, {}, { timeout: 20000, ...axiosConfig })
}
