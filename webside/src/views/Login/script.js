import { defineComponent, reactive, ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from '@/utils/notify'
import { useI18n } from 'vue-i18n'
import { authApi, ssoApi } from '@/api'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { useAuthStore } from '@/stores/auth.js'

export default defineComponent({
  setup() {
    const router = useRouter()
    const formRef = ref()
    const loading = ref(false)
    const form = reactive({
      username: '',
      password: ''
    })
    const { t, locale } = useI18n()

    const localeOptions = computed(() => SUPPORTED_LOCALES.map(code => ({
      value: code,
      label: t(`lang.${code}`),
    })))

    function onLocaleChange(val) {
      setLocale(val)
    }

    const rules = computed(() => ({
      username: [{ required: true, message: t('login.usernameRequired'), trigger: 'blur' }],
      password: [{ required: true, message: t('login.passwordRequired'), trigger: 'blur' }]
    }))

    // 账号密码登录与门户单点登录拿到的是同一种 { token, user }，进系统的收尾共用一份
    function enter(res) {
      localStorage.setItem('auth_token', res.token)
      // 登录响应已带角色与可访问页面，算作核对过，路由守卫不必再拉一次 /me
      const auth = useAuthStore()
      auth.setUser(res.user)
      auth.verified = true
      ElMessage.success(t('login.success'))
      router.replace(auth.firstAllowedPath())
    }

    const handleLogin = async () => {
      await formRef.value?.validate()
      loading.value = true
      try {
        enter(await authApi.login(form))
      } finally {
        loading.value = false
      }
    }

    // ---- 门户单点登录 ----
    const route = useRoute()
    const ssoEnabled = ref(false)
    const ssoLabel = ref('')
    const ssoLoading = ref(false)

    function handleSsoLogin() {
      ssoLoading.value = true
      location.href = ssoApi.loginUrl()   // 整页跳转，门户走完会带着一次性票跳回本页
    }

    onMounted(async () => {
      const { sso_ticket: ticket, sso_error: failed } = route.query
      if (ticket || failed) router.replace({ path: '/login' })   // 票只能用一次，别留在地址栏
      if (failed) ElMessage.error(t('login.ssoFailed') + failed)
      if (ticket) {
        ssoLoading.value = true
        try {
          enter(await ssoApi.exchange(String(ticket)))
          return
        } catch {
          /* http.js 已提示错误，留在登录页 */
        } finally {
          ssoLoading.value = false
        }
      }
      try {
        const st = await ssoApi.status()
        ssoEnabled.value = !!st.enabled
        ssoLabel.value = st.label || ''
      } catch {
        ssoEnabled.value = false
      }
    })

    return {
      reactive,
      ref,
      computed,
      useRouter,
      ElMessage,
      useI18n,
      authApi,
      setLocale,
      SUPPORTED_LOCALES,
      router,
      formRef,
      loading,
      form,
      t,
      locale,
      localeOptions,
      onLocaleChange,
      rules,
      handleLogin,
      ssoEnabled,
      ssoLabel,
      ssoLoading,
      handleSsoLogin,
    }
  },
})
