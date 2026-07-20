import { defineComponent, ref, onMounted } from 'vue'
import { ElMessage } from '@/utils/notify'
import { Search, EditPen, Check, Plus, Picture } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { memosApi } from '@/api/index.js'

function isSafeHttpUrl(u) {
  try {
    const p = new URL(u, window.location.origin)
    return p.protocol === 'http:' || p.protocol === 'https:'
  } catch {
    return false
  }
}

export default defineComponent({
  components: { Search, EditPen, Check, Plus, Picture },
  setup() {
    const { t } = useI18n()

    const tab = ref('inbox')
    const keyword = ref('')

    const list = ref([])
    const loading = ref(false)
    const page = ref(1)
    const pageSize = ref(20)
    const total = ref(0)
    const unread = ref(0)

    const composeVisible = ref(false)
    const submitting = ref(false)
    const composeFormRef = ref()
    const users = ref([])
    const composeForm = ref({ receiver_id: null, title: '', content: '' })
    const composeFileList = ref([])
    const composeRules = {
      receiver_id: [{ required: true, message: t('memos.receiverRequired'), trigger: 'change' }],
      content: [{ required: true, message: t('memos.contentRequired'), trigger: 'blur' }],
    }

    const detailVisible = ref(false)
    const detailMemo = ref(null)

    async function refreshUnread() {
      try {
        const r = await memosApi.unreadCount()
        unread.value = r?.unread || 0
      } catch {
        // 静默
      }
    }

    async function reload(toPage) {
      if (toPage) page.value = toPage
      loading.value = true
      try {
        const params = {
          keyword: keyword.value || undefined,
          page: page.value,
          page_size: pageSize.value,
        }
        let r
        if (tab.value === 'sent') {
          r = await memosApi.sent(params)
        } else {
          // inbox = 待处理 (processed=false)，processed = 已处理 (processed=true)
          params.processed = tab.value === 'processed' || undefined
          r = await memosApi.inbox(params)
        }
        list.value = r?.items || []
        total.value = r?.total || 0
      } finally {
        loading.value = false
      }
      refreshUnread()
    }

    function onTabChange() {
      page.value = 1
      keyword.value = ''
      reload(1)
    }

    /** 标记已处理 / 退回待处理：变更后该项会移出当前列表，重新拉取 */
    async function setRead(row, isRead) {
      try {
        await memosApi.markRead([row.id], isRead)
        if (isRead) ElMessage.success(t('memos.processedSuccess'))
        detailVisible.value = false
        await reload()
      } catch {
        // 错误已被 axios 拦截器提示
      }
    }

    async function onRowClick(row) {
      openDetail(row)
    }

    /** 仅打开详情查看，不再自动标记为已处理（需手动点击按钮） */
    function openDetail(row) {
      detailMemo.value = row
      detailVisible.value = true
    }

    async function markAllRead() {
      try {
        await memosApi.markAllRead()
        ElMessage.success(t('common.success'))
        await reload()
      } catch {
        // ignore
      }
    }

    async function remove(id) {
      try {
        await memosApi.remove(id)
        ElMessage.success(t('common.success'))
        if (list.value.length === 1 && page.value > 1) page.value -= 1
        reload()
      } catch {
        // ignore
      }
    }

    async function openComposeDialog() {
      if (!users.value.length) {
        try {
          users.value = await memosApi.users()
        } catch {
          users.value = []
        }
      }
      composeForm.value = { receiver_id: null, title: '', content: '' }
      composeFileList.value = []
      composeVisible.value = true
    }

    /** el-upload :on-change：选了新文件时立即上传到 /memos/upload-image，拿到 /imges/ 路径 */
    async function onPickImage(uploadFile, fileList) {
      if (uploadFile?.status !== 'ready') return
      const raw = uploadFile.raw
      if (!raw) return
      if (!/^image\//i.test(raw.type || '')) {
        ElMessage.error(t('memos.invalidImage'))
        composeFileList.value = fileList.filter((f) => f.uid !== uploadFile.uid)
        return
      }
      try {
        uploadFile.status = 'uploading'
        const r = await memosApi.uploadImage(raw)
        uploadFile.status = 'success'
        uploadFile.url = r?.path
        uploadFile.serverPath = r?.path
        // 同步到 reactive 列表（el-upload 内部已维护 file-list）
        composeFileList.value = fileList.map((f) =>
          f.uid === uploadFile.uid ? uploadFile : f
        )
      } catch {
        // 错误已弹提示；从列表里移除
        composeFileList.value = fileList.filter((f) => f.uid !== uploadFile.uid)
      }
    }

    function onRemoveImage(uploadFile, fileList) {
      composeFileList.value = fileList
    }

    function onPreviewImage(uploadFile) {
      const src = uploadFile?.url || uploadFile?.serverPath
      if (!src) return
      if (!isSafeHttpUrl(src)) {
        ElMessage.warning(t('memos.previewFailed'))
        return
      }
      window.open(src, '_blank')
    }

    async function submitCompose() {
      await composeFormRef.value.validate()
      const uploading = composeFileList.value.some((f) => f.status === 'uploading')
      if (uploading) {
        ElMessage.warning(t('memos.waitImageUpload'))
        return
      }
      const images = composeFileList.value
        .map((f) => f.serverPath || f.url)
        .filter((p) => typeof p === 'string' && p.startsWith('/imges/'))
      submitting.value = true
      try {
        await memosApi.create({
          receiver_id: composeForm.value.receiver_id,
          title: composeForm.value.title?.trim() || null,
          content: composeForm.value.content,
          images: images.length ? images : undefined,
        })
        ElMessage.success(t('memos.sentSuccess'))
        composeVisible.value = false
        if (tab.value === 'sent') reload()
      } finally {
        submitting.value = false
      }
    }

    onMounted(() => {
      reload(1)
      refreshUnread()
    })

    return {
      t,
      tab,
      keyword,
      list,
      loading,
      page,
      pageSize,
      total,
      unread,
      composeVisible,
      submitting,
      composeFormRef,
      users,
      composeForm,
      composeFileList,
      composeRules,
      detailVisible,
      detailMemo,
      reload,
      onTabChange,
      onRowClick,
      openDetail,
      setRead,
      markAllRead,
      remove,
      openComposeDialog,
      submitCompose,
      onPickImage,
      onRemoveImage,
      onPreviewImage,
    }
  },
})
