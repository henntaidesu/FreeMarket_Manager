import { defineComponent, reactive, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { Plus, RefreshRight } from '@element-plus/icons-vue'
import { authApi, systemApi } from '@/api/index.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const users = ref([])
    const loading = ref(false)
    const restarting = ref(false)

    async function confirmRestartSystem() {
      try {
        await ElMessageBox.confirm(
          t('system.restartConfirmMsg'),
          t('system.restartSystem'),
          { type: 'warning', confirmButtonText: t('system.confirmRestart'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      restarting.value = true
      try {
        const res = await systemApi.restart()
        ElMessage.success(res?.message || t('system.restartingMsg'))
      } catch {
        /* 拦截器已提示；进程退出时也可能出现网络错误，仍提示用户稍后刷新 */
      } finally {
        restarting.value = false
      }
    }

    const userDialogVisible = ref(false)
    const userSubmitting = ref(false)
    const userFormRef = ref()
    const userForm = reactive({
      username: '',
      display_name: '',
      password: ''
    })
    const userRules = {
      username: [{ required: true, message: t('login.usernameRequired'), trigger: 'blur' }],
      password: [{ required: true, message: t('login.passwordRequired'), trigger: 'blur' }, { min: 6, message: t('system.passwordMin6'), trigger: 'blur' }]
    }

    const pwdSubmitting = ref(false)
    const pwdFormRef = ref()
    const pwdForm = reactive({
      old_password: '',
      new_password: '',
      confirm_password: ''
    })
    const pwdRules = {
      old_password: [{ required: true, message: t('system.oldPasswordRequired'), trigger: 'blur' }],
      new_password: [{ required: true, message: t('system.newPasswordRequired'), trigger: 'blur' }, { min: 6, message: t('system.newPasswordMin6'), trigger: 'blur' }],
      confirm_password: [
        { required: true, message: t('system.confirmPasswordRequired'), trigger: 'blur' },
        {
          validator: (rule, value, callback) => {
            if (value !== pwdForm.new_password) callback(new Error(t('validation.passwordMismatch')))
            else callback()
          },
          trigger: 'blur'
        }
      ]
    }

    async function loadUsers() {
      loading.value = true
      try {
        users.value = await authApi.listUsers()
      } finally {
        loading.value = false
      }
    }

    function openUserDialog() {
      userForm.username = ''
      userForm.display_name = ''
      userForm.password = ''
      userDialogVisible.value = true
    }

    async function submitUser() {
      await userFormRef.value.validate()
      userSubmitting.value = true
      try {
        await authApi.createUser(userForm)
        ElMessage.success(t('system.userCreatedSuccess'))
        userDialogVisible.value = false
        await loadUsers()
      } finally {
        userSubmitting.value = false
      }
    }

    async function submitPassword() {
      await pwdFormRef.value.validate()
      pwdSubmitting.value = true
      try {
        await authApi.changePassword({
          old_password: pwdForm.old_password,
          new_password: pwdForm.new_password
        })
        ElMessage.success(t('system.passwordChangedSuccess'))
        localStorage.removeItem('auth_token')
        localStorage.removeItem('auth_user')
        window.location.hash = '#/login'
      } finally {
        pwdSubmitting.value = false
      }
    }

    onMounted(async () => {
      await loadUsers()
    })

    return {
      t,
      Plus,
      RefreshRight,
      users,
      loading,
      restarting,
      confirmRestartSystem,
      userDialogVisible,
      userSubmitting,
      userFormRef,
      userForm,
      userRules,
      pwdSubmitting,
      pwdFormRef,
      pwdForm,
      pwdRules,
      loadUsers,
      openUserDialog,
      submitUser,
      submitPassword,
    }
  },
})
