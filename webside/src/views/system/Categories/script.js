import { defineComponent, computed, ref, onMounted } from 'vue'
import { ElMessage } from '@/utils/notify'
import { useI18n } from 'vue-i18n'
import { categoryApi } from '@/api/index.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const dialogVisible = ref(false)
    const submitting = ref(false)
    const formRef = ref()
    const form = ref({ id: null, name: '', company: '', description: '' })
    const rules = { name: [{ required: true, message: t('system.categoryNameRequired'), trigger: 'blur' }] }

    /** 已有的所属公司去重列表，供下拉选择（仍可 allow-create 输入新公司） */
    const companyOptions = computed(() => {
      const set = new Set()
      for (const c of list.value || []) {
        const name = String(c?.company ?? '').trim()
        if (name) set.add(name)
      }
      return [...set].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
    })

    async function load() {
      loading.value = true
      list.value = await categoryApi.list().finally(() => (loading.value = false))
    }

    function openDialog(row = null) {
      form.value = row
        ? { ...row, company: row.company || '' }
        : { id: null, name: '', company: '', description: '' }
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value.validate()
      submitting.value = true
      try {
        if (form.value.id) await categoryApi.update(form.value.id, form.value)
        else await categoryApi.create(form.value)
        ElMessage.success(t('common.success'))
        dialogVisible.value = false
        load()
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await categoryApi.remove(id)
      ElMessage.success(t('common.success'))
      load()
    }

    onMounted(load)

    return {
      ref,
      onMounted,
      ElMessage,
      useI18n,
      categoryApi,
      t,
      list,
      loading,
      dialogVisible,
      submitting,
      formRef,
      form,
      rules,
      companyOptions,
      load,
      openDialog,
      submit,
      remove,
    }
  },
})
