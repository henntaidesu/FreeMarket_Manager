import { defineComponent, ref, computed, onMounted } from 'vue'
import { ElMessage } from '@/utils/notify'
import { useI18n } from 'vue-i18n'
import { costRecordApi } from '@/api/index.js'
import { SHIP_SIZE_GROUPS } from '@/constants/shipSizes.js'

// 库存包材 = 包材目录：只维护 物品图 / 物品名称 / 单价 / 关联发货尺寸。
// 数量按无限计算（后端不再扣减、不再按数量过滤），所以这里不显示也不提交数量。
export default defineComponent({
  setup() {
    const { t } = useI18n()

    const loading = ref(false)
    const submitting = ref(false)
    const list = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const dialogVisible = ref(false)
    const formRef = ref()
    const fileInputRef = ref()
    const uploadingImage = ref(false)

    const createDefaultForm = () => ({
      id: null,
      item_name: '',
      item_image: '',
      amount: null,
      ship_sizes: [],
    })

    const form = ref(createDefaultForm())

    const rules = computed(() => ({
      item_name: [{ required: true, message: t('system.costRecordInputItemName'), trigger: 'blur' }],
      amount: [{ required: true, message: t('system.costRecordInputUnitPrice'), trigger: 'blur' }],
    }))

    async function load() {
      loading.value = true
      const params = {
        page: page.value,
        page_size: pageSize.value,
        type: 'packaging',
      }
      const res = await costRecordApi.list(params).finally(() => {
        loading.value = false
      })
      list.value = res.items || []
      total.value = res.total || 0
    }

    function openCreate() {
      form.value = createDefaultForm()
      dialogVisible.value = true
    }

    function openEdit(row) {
      form.value = {
        id: row.id,
        item_name: row.item_name || '',
        item_image: row.item_image || '',
        amount: Number(row.amount || 0),
        ship_sizes: Array.isArray(row.ship_sizes) ? [...row.ship_sizes] : [],
      }
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value?.validate()
      submitting.value = true
      const payload = {
        type: 'packaging',
        item_name: String(form.value.item_name || '').trim(),
        item_image: form.value.item_image || null,
        amount: Number(form.value.amount || 0),
        ship_sizes: (form.value.ship_sizes || []).map((s) => String(s || '').trim()).filter(Boolean),
      }
      try {
        if (form.value.id) {
          await costRecordApi.update(form.value.id, payload)
          ElMessage.success(t('system.costRecordUpdateSuccess'))
        } else {
          await costRecordApi.create(payload)
          ElMessage.success(t('system.costRecordCreateSuccess'))
        }
        dialogVisible.value = false
        load()
      } finally {
        submitting.value = false
      }
    }

    async function handleImageUpload(e) {
      const file = e.target.files?.[0]
      e.target.value = ''
      if (!file) return
      if (file.size > 25 * 1024 * 1024) {
        ElMessage.warning(t('system.costRecordImageSizeLimit'))
        return
      }
      uploadingImage.value = true
      try {
        const res = await costRecordApi.uploadImage(file)
        form.value.item_image = res.path || ''
        ElMessage.success(t('system.costRecordImageUploadSuccess'))
      } finally {
        uploadingImage.value = false
      }
    }

    function clearImage() {
      form.value.item_image = ''
    }

    async function remove(id) {
      await costRecordApi.remove(id)
      ElMessage.success(t('system.costRecordDeleteSuccess'))
      if (list.value.length === 1 && page.value > 1) page.value -= 1
      load()
    }

    onMounted(load)

    return {
      t,
      SHIP_SIZE_GROUPS,
      loading,
      submitting,
      list,
      total,
      page,
      pageSize,
      dialogVisible,
      formRef,
      fileInputRef,
      uploadingImage,
      form,
      rules,
      load,
      openCreate,
      openEdit,
      submit,
      handleImageUpload,
      clearImage,
      remove,
    }
  },
})
