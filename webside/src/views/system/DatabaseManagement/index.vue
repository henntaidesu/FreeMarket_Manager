<template>
  <div class="db-mgmt">
    <el-card shadow="never" class="mb">
      <template #header>
        <div class="card-head">
          <span>数据库管理</span>
          <el-tag :type="activeBackend === 'mysql' ? 'success' : 'info'" effect="dark">
            当前：{{ activeBackend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-tag>
        </div>
      </template>

      <el-form label-width="110px" class="mt" @submit.prevent>
        <el-form-item label="使用数据库">
          <el-radio-group v-model="form.backend">
            <el-radio-button label="sqlite">SQLite（默认）</el-radio-button>
            <el-radio-button label="mysql">MySQL</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.backend === 'mysql'">
          <el-form-item label="主机">
            <el-input v-model="form.mysql.host" style="max-width:360px" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="form.mysql.port" :min="1" :max="65535" :controls="false" style="width:160px" class="port-input" />
          </el-form-item>
          <el-form-item label="用户">
            <el-input v-model="form.mysql.user" style="max-width:360px" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.mysql.password"
              type="password"
              show-password
              :placeholder="passwordSet ? '••••••••' : ''"
              style="max-width:360px"
            />
          </el-form-item>
          <el-form-item label="数据库">
            <el-input v-model="form.mysql.database" style="max-width:360px" />
          </el-form-item>
        </template>

        <el-form-item label=" ">
          <!-- 测试连接（仅在选择 MySQL 时） -->
          <el-button v-if="form.backend === 'mysql'" :loading="testing" @click="onTest">测试连接</el-button>
          <!-- 切换数据库：同服务器热切换库名（仅当前为 MySQL 时） -->
          <el-button
            v-if="activeBackend === 'mysql'"
            type="warning"
            :loading="hotSwitching"
            :disabled="!form.mysql.database || form.mysql.database.trim() === activeDatabase"
            @click="onHotSwitch"
          >切换数据库</el-button>
          <!-- 迁移数据：当前为 MySQL 时不显示「迁移数据到 MySQL」 -->
          <el-button
            v-if="!(form.backend === 'mysql' && activeBackend === 'mysql')"
            :loading="migrating"
            :disabled="form.backend === activeBackend || switching"
            @click="onMigrate"
          >
            迁移数据到 {{ form.backend === 'mysql' ? 'MySQL' : 'SQLite' }}
          </el-button>
          <el-button
            v-if="form.backend !== activeBackend"
            type="primary"
            :disabled="migrating"
            :loading="switching"
            @click="onSwitch"
          >
            切换到 {{ form.backend === 'mysql' ? 'MySQL' : 'SQLite' }}
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

    <el-card shadow="never" class="mb">
      <template #header>数据库备份</template>
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

    <el-card v-if="migrateSummary.length" shadow="never">
      <template #header>迁移 / 备份结果（逐表行数校验）</template>
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { databaseApi } from '@/api/database'

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

const form = reactive({
  backend: 'sqlite',
  mysql: { host: '127.0.0.1', port: 3306, user: 'root', password: '', database: 'mercari' }
})

// 备份目标：默认沿用当前 MySQL 服务器，库名留空由用户填写
const backup = reactive({ host: '127.0.0.1', port: 3306, user: 'root', password: '', database: '' })

async function loadConfig() {
  const cfg = await databaseApi.getConfig()
  activeBackend.value = cfg.backend
  form.backend = cfg.backend
  passwordSet.value = !!cfg.mysql.password_set
  activeDatabase.value = cfg.mysql.database
  Object.assign(form.mysql, {
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
  const target = (form.mysql.database || '').trim()
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
    testResult.value = await databaseApi.testConnection({ ...form.mysql })
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    testing.value = false
  }
}

async function onMigrate() {
  const target = form.backend === 'mysql' ? 'MySQL' : 'SQLite'
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
    const payload = { backend: form.backend }
    if (form.backend === 'mysql') payload.mysql = { ...form.mysql }
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
  const target = form.backend === 'mysql' ? 'MySQL' : 'SQLite'
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
    const payload = { backend: form.backend }
    if (form.backend === 'mysql') payload.mysql = { ...form.mysql }
    const res = await databaseApi.switch(payload)
    ElMessage.success(res.message)
    if (res.restarting) {
      // 后端将重启，稍后自动刷新页面
      setTimeout(() => window.location.reload(), 12000)
    } else {
      loadConfig()
    }
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    switching.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.db-mgmt { max-width: 820px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.mb { margin-bottom: 16px; }
.mt { margin-top: 8px; }
.test-result { margin-left: 12px; color: #f56c6c; }
.test-result.ok { color: #67c23a; }
.port-input :deep(.el-input__inner) { text-align: left; }
</style>
