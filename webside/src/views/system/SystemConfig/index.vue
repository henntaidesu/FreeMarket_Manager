<template>
  <div>
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

    <!-- 数据库管理 -->
    <el-card shadow="never" class="sysconf-card db-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">数据库管理</span>
          <el-tag :type="activeBackend === 'mysql' ? 'success' : 'info'" effect="dark">
            当前：{{ activeBackend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-tag>
        </div>
      </template>

      <el-form label-width="110px" class="mt" @submit.prevent>
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
    </el-card>

    <!-- 数据库备份 -->
    <el-card shadow="never" class="sysconf-card db-card">
      <template #header>
        <div class="card-title">数据库备份</div>
      </template>
      <el-form label-width="110px" class="mt" @submit.prevent>
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

    <el-card v-if="migrateSummary.length" shadow="never" class="sysconf-card db-card">
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { configApi } from '@/api/index.js'
import { databaseApi } from '@/api/database'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const { t } = useI18n()

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
  { label: 'らくらくメルカリ便', value: 'rakuraku' },
  { label: 'ゆうゆうメルカリ便', value: 'yuuyu' },
  { label: t('system.shippingMethodRegularMail'), value: 'regular_mail' }
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

onMounted(() => {
  load()
  loadListingDefaults()
  loadDbConfig()
})
</script>

<style scoped>
.sysconf-card {
  max-width: 720px;
}
.listing-def-card {
  margin-top: 16px;
}
.card-title {
  font-weight: 600;
}
.sysconf-form {
  max-width: 640px;
}
.db-card {
  margin-top: 16px;
  max-width: 820px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.mt {
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
</style>
