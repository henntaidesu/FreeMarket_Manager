<template>
  <div class="sysconf-page">
    <div class="sysconf-grid">
    <!-- 账号管理 + 修改我的密码：并排一行（用户表列多，占 2/3 宽） -->
    <div class="account-row">
    <el-card shadow="never" class="sysconf-card account-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">{{ t('system.accountManagement') }}</span>
          <el-button type="primary" size="small" @click="openUserDialog">
            <el-icon><Plus /></el-icon> {{ t('system.addUser') }}
          </el-button>
        </div>
      </template>
      <el-table :data="users" v-loading="usersLoading" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="username" :label="t('system.username')" min-width="120" />
        <el-table-column prop="display_name" :label="t('system.displayName')" min-width="140" />
        <el-table-column :label="t('common.status')" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? t('common.enabled') : t('common.disabled') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" :label="t('system.lastLoginAt')" min-width="160" />
        <el-table-column prop="created_at" :label="t('common.createdAt')" min-width="160" />
      </el-table>
    </el-card>

    <!-- 修改我的密码 -->
    <el-card shadow="never" class="sysconf-card">
      <template #header>
        <div class="card-title">{{ t('system.changeMyPassword') }}</div>
      </template>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="90px">
        <el-form-item :label="t('system.oldPassword')" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('system.newPassword')" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item :label="t('system.confirmPassword')" prop="confirm_password">
          <el-input v-model="pwdForm.confirm_password" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="pwdSubmitting" @click="submitPassword">
            {{ t('system.changePassword') }}
          </el-button>
        </el-form-item>
      </el-form>
      <div class="hint-tip">{{ t('system.pwdTip') }}</div>
    </el-card>
    </div>

    <!-- DeepSeek AI 配置 -->
    <el-card shadow="never" class="sysconf-card" v-loading="loading">
      <template #header>
        <div class="card-title">{{ t('systemConfig.deepseekSection') }}</div>
      </template>
      <el-form label-width="120px" class="sysconf-form" @submit.prevent>
        <el-form-item :label="t('systemConfig.apiKey')">
          <el-input v-model="form.api_key" type="password" show-password clearable />
        </el-form-item>
        <el-form-item :label="t('systemConfig.model')">
          <el-input v-model="form.model" clearable />
        </el-form-item>
        <el-form-item :label="t('systemConfig.baseUrl')">
          <el-input v-model="form.base_url" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">
            {{ t('systemConfig.save') }}
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 出品默认值 -->
    <el-card shadow="never" class="sysconf-card listing-def-card" v-loading="listingDefLoading">
      <template #header>
        <div class="card-title">{{ t('system.listingDefaults') }}</div>
      </template>
      <el-form label-width="132px" class="listing-def-form">
        <el-form-item :label="t('system.defaultShippingFrom')">
          <el-cascader
            v-model="listingDefForm.shipping_from_path"
            :options="shippingFromCascaderOptions"
            :props="shippingFromCascaderProps"
            :show-all-levels="false"
            filterable
            clearable
            placeholder=""
            style="width: 100%; max-width: 520px"
            popper-class="product-type-cascader-popper"
            @change="onShippingFromChange"
          />
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingMethod')">
          <el-select
            v-model="listingDefForm.shipping_method"
            clearable
            placeholder=""
            style="width: 100%; max-width: 360px"
            @change="saveListingDefaults"
          >
            <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingPayer')">
          <el-select v-model="listingDefForm.shipping_payer" clearable placeholder="" style="width: 100%; max-width: 360px" @change="saveListingDefaults">
            <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultShippingDays')">
          <el-select v-model="listingDefForm.shipping_days" clearable placeholder="" style="width: 100%; max-width: 280px" @change="saveListingDefaults">
            <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.defaultListingImage')">
          <el-select v-model="listingDefForm.watermark" placeholder="" style="width: 100%; max-width: 280px" @change="saveListingDefaults">
            <el-option :label="t('system.listingImageWatermark')" :value="1" />
            <el-option :label="t('system.listingImageNoWatermark')" :value="0" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 数据库管理（连接 / 切换 + 备份） -->
    <el-card shadow="never" class="sysconf-card db-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">数据库管理</span>
          <el-tag :type="activeBackend === 'mysql' ? 'success' : 'info'" effect="dark">
            当前：{{ activeBackend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-tag>
        </div>
      </template>

      <div class="db-tabs">
        <el-radio-group v-model="dbPane" size="small">
          <el-radio-button label="connect">连接 / 切换</el-radio-button>
          <el-radio-button label="backup">备份</el-radio-button>
        </el-radio-group>
      </div>

      <!-- v-show 而非 v-if：来回切换时两边已填的表单不丢 -->
      <el-form v-show="dbPane === 'connect'" label-width="110px" @submit.prevent>
        <el-form-item label="使用数据库">
          <el-radio-group v-model="dbForm.backend">
            <el-radio-button label="sqlite">SQLite（默认）</el-radio-button>
            <el-radio-button label="mysql">MySQL</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="dbForm.backend === 'mysql'">
          <el-form-item label="主机">
            <el-input v-model="dbForm.mysql.host" style="max-width:360px" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="dbForm.mysql.port" :min="1" :max="65535" :controls="false" style="width:160px" class="port-input" />
          </el-form-item>
          <el-form-item label="用户">
            <el-input v-model="dbForm.mysql.user" style="max-width:360px" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="dbForm.mysql.password"
              type="password"
              show-password
              :placeholder="passwordSet ? '••••••••' : ''"
              style="max-width:360px"
            />
          </el-form-item>
          <el-form-item label="数据库">
            <el-input v-model="dbForm.mysql.database" style="max-width:360px" />
          </el-form-item>
        </template>

        <el-form-item label=" ">
          <!-- 测试连接（仅在选择 MySQL 时） -->
          <el-button v-if="dbForm.backend === 'mysql'" :loading="testing" @click="onTest">测试连接</el-button>
          <!-- 切换数据库：同服务器热切换库名（仅当前为 MySQL 时） -->
          <el-button
            v-if="activeBackend === 'mysql'"
            type="warning"
            :loading="hotSwitching"
            :disabled="!dbForm.mysql.database || dbForm.mysql.database.trim() === activeDatabase"
            @click="onHotSwitch"
          >切换数据库</el-button>
          <!-- 迁移数据：当前为 MySQL 时不显示「迁移数据到 MySQL」 -->
          <el-button
            v-if="!(dbForm.backend === 'mysql' && activeBackend === 'mysql')"
            :loading="migrating"
            :disabled="dbForm.backend === activeBackend || switching"
            @click="onMigrate"
          >
            迁移数据到 {{ dbForm.backend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-button>
          <el-button
            v-if="dbForm.backend !== activeBackend"
            type="primary"
            :disabled="migrating"
            :loading="switching"
            @click="onSwitch"
          >
            切换到 {{ dbForm.backend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-button>
          <span v-if="testResult" class="test-result" :class="{ ok: testResult.ok }">
            {{ testResult.message }}
            <template v-if="testResult.ok">
              · 版本 {{ testResult.version }}
              · 目标库{{ testResult.database_exists ? '已存在' : '不存在（将自动创建）' }}
            </template>
          </span>
        </el-form-item>
      </el-form>

      <el-form v-show="dbPane === 'backup'" label-width="110px" @submit.prevent>
        <el-form-item label="主机">
          <el-input v-model="backup.host" style="max-width:360px" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="backup.port" :min="1" :max="65535" :controls="false" style="width:160px" class="port-input" />
        </el-form-item>
        <el-form-item label="用户">
          <el-input v-model="backup.user" style="max-width:360px" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="backup.password" type="password" show-password style="max-width:360px" />
        </el-form-item>
        <el-form-item label="目标库">
          <el-input v-model="backup.database" style="max-width:360px" />
        </el-form-item>
        <el-form-item label=" ">
          <el-button :loading="testingBackup" @click="onTestBackup">测试连接</el-button>
          <el-button type="primary" :loading="backuping" :disabled="!backup.database" @click="onBackup">开始备份</el-button>
          <span v-if="backupTestResult" class="test-result" :class="{ ok: backupTestResult.ok }">
            {{ backupTestResult.message }}
            <template v-if="backupTestResult.ok">
              · 版本 {{ backupTestResult.version }}
              · 目标库{{ backupTestResult.database_exists ? '已存在' : '不存在（将自动创建）' }}
            </template>
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 二维码打印参数：存 localStorage（跟随浏览器，蓝牙配对本身也是按浏览器授权的） -->
    <el-card shadow="never" class="sysconf-card">
      <template #header>
        <div class="card-title">{{ t('qrPrint.paramsSection') }}</div>
      </template>
      <el-form label-width="120px" class="qrprint-form" @submit.prevent>
        <el-form-item :label="t('qrPrint.labelSize')">
          <el-input-number v-model="printerCfg.labelWmm" :min="10" :max="100" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
          <span class="qrprint-sep">×</span>
          <el-input-number v-model="printerCfg.labelHmm" :min="10" :max="100" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
          <span class="qrprint-unit">mm</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.headWidth')">
          <el-input-number v-model="printerCfg.headMm" :min="20" :max="110" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
          <span class="qrprint-unit">mm</span>
        </el-form-item>
        <el-form-item label="DPI">
          <el-input-number v-model="printerCfg.dpi" :min="100" :max="600" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
        </el-form-item>
        <el-form-item :label="t('qrPrint.chunk')">
          <el-input-number v-model="printerCfg.chunk" :min="20" :max="512" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
          <span class="qrprint-unit">{{ t('qrPrint.chunkUnit') }}</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.feed')">
          <el-input-number v-model="printerCfg.feedMm" :min="0" :max="60" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
          <span class="qrprint-unit">mm</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.density')">
          <el-input-number v-model="printerCfg.density" :min="1" :max="31" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
        </el-form-item>
        <el-form-item :label="t('qrPrint.threshold')">
          <el-input-number v-model="printerCfg.threshold" :min="10" :max="245" :controls="false" class="qrprint-num" @change="savePrinterCfg" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 打印机连接：连接 / 测试打印 / 忘记设备 -->
    <el-card shadow="never" class="sysconf-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">{{ t('qrPrint.connSection') }}</span>
          <el-tag :type="printerState.connected ? 'success' : 'info'" effect="dark">
            {{ printerState.connected ? t('qrPrint.connected') : t('qrPrint.disconnected') }}
          </el-tag>
        </div>
      </template>
      <el-form label-width="120px" @submit.prevent>
        <el-form-item :label="t('qrPrint.device')">
          <span>{{ printerState.deviceName || t('qrPrint.noDevice') }}</span>
        </el-form-item>
        <!-- 免弹框自动重连：需浏览器支持 getDevices（Chrome/Edge 持久化蓝牙授权） -->
        <el-form-item :label="t('qrPrint.autoReconnect')">
          <span :class="autoReconnectOk ? 'qrprint-ok' : 'qrprint-warn'">
            {{ autoReconnectOk ? t('qrPrint.autoReconnectOk') : t('qrPrint.autoReconnectNo') }}
          </span>
        </el-form-item>
        <!-- 整表发现出多个可写特征时才显示，默认自动选第一个并持久化 -->
        <el-form-item v-if="printerState.writableChars.length > 1" :label="t('qrPrint.writeChar')">
          <el-select :model-value="printerState.charUuid" style="width: 100%; max-width: 480px" @change="onPickChar">
            <el-option
              v-for="c in printerState.writableChars"
              :key="c.uuid"
              :label="c.uuid + '  [' + c.flags + ']'"
              :value="c.uuid"
            />
          </el-select>
        </el-form-item>
        <el-form-item label=" ">
          <el-button type="primary" :loading="connecting" @click="onConnect">{{ t('qrPrint.connect') }}</el-button>
          <el-button :loading="qrTesting" @click="onQrTest">{{ t('qrPrint.testPrint') }}</el-button>
          <el-button type="danger" plain @click="onForget">{{ t('qrPrint.forget') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    </div>

    <el-card v-if="migrateSummary.length" shadow="never" class="sysconf-card summary-card">
      <template #header>
        <div class="card-title">迁移 / 备份结果（逐表行数校验）</div>
      </template>
      <el-table :data="migrateSummary" stripe size="small" max-height="420">
        <el-table-column prop="table" label="表" min-width="220" />
        <el-table-column prop="src" label="源行数" width="100" align="right" />
        <el-table-column prop="dst" label="目标行数" width="100" align="right" />
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'OK' ? 'success' : (row.status.includes('不一致') ? 'danger' : 'info')" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="userDialogVisible" :title="t('system.addUser')" width="420px" destroy-on-close>
      <el-form ref="userFormRef" :model="userForm" :rules="userRules" label-width="90px">
        <el-form-item :label="t('system.username')" prop="username">
          <el-input v-model="userForm.username" />
        </el-form-item>
        <el-form-item :label="t('system.displayName')">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item :label="t('system.password')" prop="password">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="userSubmitting" @click="submitUser">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from '@/utils/notify'
import { authApi, configApi } from '@/api/index.js'
import { databaseApi } from '@/api/database'
import {
  printTestLabel,
  loadPrinterConfig,
  savePrinterConfig,
  isBluetoothSupported,
  supportsAutoReconnect,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  forgetPrinter,
} from '@/utils/btPrinter/index.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const { t } = useI18n()

// ===== 账号管理（用户列表 / 新建用户 / 改密码，原「系统总览」页并入）=====
const users = ref([])
const usersLoading = ref(false)

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
  usersLoading.value = true
  try {
    users.value = await authApi.listUsers()
  } finally {
    usersLoading.value = false
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

// ===== DeepSeek AI 配置 =====
const loading = ref(false)
const saving = ref(false)
const form = reactive({
  api_key: '',
  model: '',
  base_url: '',
})

async function load() {
  loading.value = true
  try {
    const res = await configApi.getDeepseekConfig()
    form.api_key = res?.api_key || ''
    form.model = res?.model || ''
    form.base_url = res?.base_url || ''
  } catch {
    ElMessage.error(t('systemConfig.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await configApi.putDeepseekConfig({
      api_key: form.api_key,
      model: form.model,
      base_url: form.base_url,
    })
    form.api_key = res?.api_key || ''
    form.model = res?.model || ''
    form.base_url = res?.base_url || ''
    ElMessage.success(t('systemConfig.saveSuccess'))
  } finally {
    saving.value = false
  }
}

// ===== 出品默认值（手动出品表单预填 + 默认出品方式；不影响自动补挂） =====
const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false
}

const shippingFromCascaderOptions = computed(() =>
  JP_REGION_OPTIONS.map((r) => ({
    value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
    label: r.label,
    children: r.areaIds
      .map((aid) => {
        const a = MERCARI_AREAS.find((x) => x.id === aid)
        return a ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name } : null
      })
      .filter(Boolean)
  }))
)

const shippingPayerOptions = computed(() => [
  { label: t('system.shippingPayerSeller'), value: 'seller' },
  { label: t('system.shippingPayerBuyer'), value: 'buyer' }
])
const shippingMethodOptions = computed(() => [
  { label: t('system.shippingMethodUndecided'), value: 'undecided' },
  { label: t('system.shippingMethodRakuraku'), value: 'rakuraku' },
  { label: t('system.shippingMethodYuuyu'), value: 'yuuyu' }
])
const shippingDaysOptions = computed(() => [
  { label: t('system.shippingDays12'), value: '1_2_days' },
  { label: t('system.shippingDays23'), value: '2_3_days' },
  { label: t('system.shippingDays47'), value: '4_7_days' }
])

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [`${SHIPPING_FROM_REGION_PREFIX}${regionId}`, `${SHIPPING_FROM_AREA_PREFIX}${areaId}`]
}

const listingDefForm = reactive({
  shipping_from_path: [],
  shipping_method: null,
  shipping_payer: null,
  shipping_days: null,
  // 默认出品图片：1=有水印 / 0=无水印
  watermark: 1
})

const listingDefLoading = ref(false)
const listingDefSaving = ref(false)

function onShippingFromChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    listingDefForm.shipping_from_path = []
  }
  saveListingDefaults()
}

function pathToAreaId(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) return null
  const id = String(picked).slice(SHIPPING_FROM_AREA_PREFIX.length).trim()
  return id || null
}

async function loadListingDefaults() {
  listingDefLoading.value = true
  try {
    const d = await configApi.getListingDefaults()
    const area = normalizeShippingFromSeed(d?.shipping_from_area_id)
    listingDefForm.shipping_from_path = buildShippingFromPath(area)
    listingDefForm.shipping_method = d?.shipping_method ?? null
    listingDefForm.shipping_payer = d?.shipping_payer ?? null
    listingDefForm.shipping_days = d?.shipping_days ?? null
    listingDefForm.watermark = Number(d?.watermark) === 0 ? 0 : 1
  } catch {
    /* 拦截器已提示 */
  } finally {
    listingDefLoading.value = false
  }
}

async function saveListingDefaults() {
  listingDefSaving.value = true
  try {
    const areaId = pathToAreaId(listingDefForm.shipping_from_path)
    await configApi.putListingDefaults({
      shipping_from_area_id: areaId,
      shipping_method: listingDefForm.shipping_method,
      shipping_payer: listingDefForm.shipping_payer,
      shipping_days: listingDefForm.shipping_days,
      watermark: listingDefForm.watermark
    })
    ElMessage.success(t('system.listingDefaultsSaved'))
  } catch {
    /* 拦截器 */
  } finally {
    listingDefSaving.value = false
  }
}

// ===== 数据库管理 =====
/** 数据库卡片内的分栏：connect = 连接/切换，backup = 备份 */
const dbPane = ref('connect')
const activeBackend = ref('sqlite')
const passwordSet = ref(false)
const testing = ref(false)
const switching = ref(false)
const migrating = ref(false)
const testResult = ref(null)
const migrateSummary = ref([])
const hotSwitching = ref(false)
const activeDatabase = ref('')   // 当前生效的 MySQL 库名，用于判断库名是否被修改
const testingBackup = ref(false)
const backuping = ref(false)
const backupTestResult = ref(null)

const dbForm = reactive({
  backend: 'sqlite',
  mysql: { host: '127.0.0.1', port: 3306, user: 'root', password: '', database: 'mercari' }
})

// 备份目标：默认沿用当前 MySQL 服务器，库名留空由用户填写
const backup = reactive({ host: '127.0.0.1', port: 3306, user: 'root', password: '', database: '' })

async function loadDbConfig() {
  const cfg = await databaseApi.getConfig()
  activeBackend.value = cfg.backend
  dbForm.backend = cfg.backend
  passwordSet.value = !!cfg.mysql.password_set
  activeDatabase.value = cfg.mysql.database
  Object.assign(dbForm.mysql, {
    host: cfg.mysql.host, port: cfg.mysql.port,
    user: cfg.mysql.user, database: cfg.mysql.database, password: ''
  })
  // 备份目标默认预填当前 MySQL 服务器（库名留空，避免误备份到当前库）
  Object.assign(backup, { host: cfg.mysql.host, port: cfg.mysql.port, user: cfg.mysql.user })
}

async function onTestBackup() {
  testingBackup.value = true
  backupTestResult.value = null
  try {
    backupTestResult.value = await databaseApi.testConnection({ ...backup })
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    testingBackup.value = false
  }
}

async function onBackup() {
  const target = `${backup.host}:${backup.port}/${backup.database.trim()}`
  try {
    await ElMessageBox.confirm(
      `将把当前数据库的全部数据备份到「${target}」（先清空目标库同名表再整库覆盖）。当前使用的数据库不变。是否继续？`,
      '确认备份数据库',
      { type: 'warning', confirmButtonText: '开始备份', cancelButtonText: '取消' }
    )
  } catch (_) {
    return
  }
  backuping.value = true
  migrateSummary.value = []
  try {
    const res = await databaseApi.backup({ ...backup })
    migrateSummary.value = res.tables || []
    ElMessage.success(res.message)
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示（如 409：有后台同步任务正在进行）
  } finally {
    backuping.value = false
  }
}

async function onHotSwitch() {
  const target = (dbForm.mysql.database || '').trim()
  try {
    await ElMessageBox.confirm(
      `将把当前使用的数据库切换为「${target}」（同一服务器切库，无需重启后端）。切换前会确认没有正在进行的后台同步任务。是否继续？`,
      '确认切换数据库',
      { type: 'warning', confirmButtonText: '切换', cancelButtonText: '取消' }
    )
  } catch (_) {
    return
  }
  hotSwitching.value = true
  try {
    const res = await databaseApi.hotSwitch(target)
    ElMessage.success(res.message)
    // 后端已切库（未重启），刷新页面以让所有视图读取新库数据
    setTimeout(() => window.location.reload(), 800)
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示（如 409：有后台同步任务正在进行）
  } finally {
    hotSwitching.value = false
  }
}

async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await databaseApi.testConnection({ ...dbForm.mysql })
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    testing.value = false
  }
}

async function onMigrate() {
  const target = dbForm.backend === 'mysql' ? 'MySQL' : 'SQLite'
  try {
    await ElMessageBox.confirm(
      `将把当前数据库的全部数据复制到 ${target}（覆盖目标库同名数据），当前使用的数据库不变。是否继续？`,
      '确认迁移数据库',
      { type: 'warning', confirmButtonText: '开始迁移', cancelButtonText: '取消' }
    )
  } catch (_) {
    return
  }
  migrating.value = true
  migrateSummary.value = []
  try {
    const payload = { backend: dbForm.backend }
    if (dbForm.backend === 'mysql') payload.mysql = { ...dbForm.mysql }
    const res = await databaseApi.migrate(payload)
    migrateSummary.value = res.tables || []
    ElMessage.success(res.message)
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    migrating.value = false
  }
}

async function onSwitch() {
  const target = dbForm.backend === 'mysql' ? 'MySQL' : 'SQLite'
  try {
    await ElMessageBox.confirm(
      `将把当前使用的数据库切换为 ${target}（仅改变连接，不迁移数据），成功后会自动重启后端。是否继续？`,
      '确认切换数据库',
      { type: 'warning', confirmButtonText: '切换', cancelButtonText: '取消' }
    )
  } catch (_) {
    return
  }
  switching.value = true
  try {
    const payload = { backend: dbForm.backend }
    if (dbForm.backend === 'mysql') payload.mysql = { ...dbForm.mysql }
    const res = await databaseApi.switch(payload)
    ElMessage.success(res.message)
    if (res.restarting) {
      // 后端将重启，稍后自动刷新页面
      setTimeout(() => window.location.reload(), 12000)
    } else {
      loadDbConfig()
    }
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    switching.value = false
  }
}

// ===== 二维码打印（参数存 localStorage，无后端；原「二维码设置」页并入）=====
// testing / onTest 已被上面的数据库测试连接占用，这里一律加 qr 前缀
const printerCfg = reactive(loadPrinterConfig())
const printerState = ref(getPrinterState())
const connecting = ref(false)
const qrTesting = ref(false)
const autoReconnectOk = supportsAutoReconnect()

function savePrinterCfg() {
  savePrinterConfig({
    labelWmm: Number(printerCfg.labelWmm) || 30,
    labelHmm: Number(printerCfg.labelHmm) || 30,
    headMm: Number(printerCfg.headMm) || 48,
    dpi: Number(printerCfg.dpi) || 203,
    chunk: Number(printerCfg.chunk) || 180,
    feedMm: Math.max(0, Number(printerCfg.feedMm) || 0),
    density: Number(printerCfg.density) || 10,
    threshold: Number(printerCfg.threshold) || 128,
  })
  ElMessage.success(t('qrPrint.saved'))
}

function checkBtSupported() {
  if (isBluetoothSupported()) return true
  ElMessage.error(t('qrPrint.notSupported'))
  return false
}

async function onConnect() {
  if (!checkBtSupported()) return
  connecting.value = true
  try {
    printerState.value = await connectPrinter()
    ElMessage.success(t('qrPrint.connectOk'))
  } catch (e) {
    // 仅「用户点了取消」不当作错误；GATT 服务发现失败同为 NotFoundError，须提示
    const isCancel = e?.name === 'NotFoundError' && /cancel/i.test(String(e?.message || ''))
    if (!isCancel) {
      ElMessage.error(t('qrPrint.connectFail') + ': ' + (e?.message || e))
    }
  } finally {
    connecting.value = false
  }
}

async function onQrTest() {
  if (!checkBtSupported()) return
  qrTesting.value = true
  try {
    await printTestLabel()
    printerState.value = getPrinterState()
    ElMessage.success(t('qrPrint.testSent'))
  } catch (e) {
    const isCancel = e?.name === 'NotFoundError' && /cancel/i.test(String(e?.message || ''))
    if (!isCancel) {
      ElMessage.error(t('qrPrint.testFail') + ': ' + (e?.message || e))
    }
  } finally {
    qrTesting.value = false
  }
}

function onPickChar(uuid) {
  pickWriteChar(uuid)
  printerState.value = getPrinterState()
}

function onForget() {
  forgetPrinter()
  printerState.value = getPrinterState()
  ElMessage.success(t('qrPrint.forgotten'))
}

onMounted(() => {
  loadUsers()
  load()
  loadListingDefaults()
  loadDbConfig()
})
</script>

<style scoped>
.sysconf-page {
  width: 100%;
}
.sysconf-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(440px, 1fr));
  gap: 16px;
}
.card-title {
  font-weight: 600;
}
.summary-card {
  margin-top: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
/* 账号管理 + 修改我的密码 并排：整行独占，用户表 6 列吃 2/3 宽（挤在 440px 网格列里会串行） */
.account-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .account-row {
    grid-template-columns: 1fr;
  }
}
/* 数据库卡片内「连接/切换」与「备份」两套表单的切换按钮 */
.db-tabs {
  margin-bottom: 16px;
}
.hint-tip {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 8px;
}
.test-result {
  margin-left: 12px;
  color: #f56c6c;
}
.test-result.ok {
  color: #67c23a;
}
.port-input :deep(.el-input__inner) {
  text-align: left;
}
.qrprint-form {
  max-width: 640px;
}
.qrprint-num {
  width: 100px;
}
.qrprint-num :deep(.el-input__inner) {
  text-align: left;
}
.qrprint-sep {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}
.qrprint-unit {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
}
.qrprint-ok {
  color: var(--el-color-success);
}
.qrprint-warn {
  color: var(--el-color-warning);
}
</style>
