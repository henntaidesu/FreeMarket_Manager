<template>
  <div ref="pageRef" class="sc">
    <!-- 页头：标题 + 两个实时状态（数据库 / 打印机），不用再滚到对应卡片才知道当前状态 -->
    <header class="sc-hero">
      <div class="sc-hero-main">
        <h1 class="sc-hero-title">{{ t('systemConfig.title') }}</h1>
        <p class="sc-hero-sub">{{ t('systemConfig.subtitle') }}</p>
      </div>
      <div class="sc-hero-stats">
        <div class="sc-stat">
          <span class="sc-dot" :class="activeBackend === 'mysql' ? 'is-ok' : 'is-idle'" />
          <span class="sc-stat-label">{{ t('systemConfig.databaseSection') }}</span>
          <span class="sc-stat-value">
            {{ activeBackend === 'mysql' ? 'MySQL' : 'SQLite' }}
            <template v-if="activeBackend === 'mysql' && activeDatabase"> · {{ activeDatabase }}</template>
          </span>
        </div>
        <div class="sc-stat">
          <span class="sc-dot" :class="printerState.connected ? 'is-ok' : 'is-idle'" />
          <span class="sc-stat-label">{{ t('qrPrint.device') }}</span>
          <span class="sc-stat-value">
            {{ printerState.connected ? t('qrPrint.connected') : t('qrPrint.disconnected') }}
          </span>
        </div>
      </div>
    </header>

    <div class="sc-body">
      <!-- 侧边锚点导航：粘在滚动容器顶部，窄屏变成横向 chip 条 -->
      <nav class="sc-nav">
        <button
          v-for="s in SECTIONS"
          :key="s.id"
          type="button"
          class="sc-nav-item"
          :class="{ 'is-active': activeSection === s.id }"
          @click="goSection(s.id)"
        >
          <el-icon :size="15"><component :is="s.icon" /></el-icon>
          <span class="sc-nav-text">{{ t(s.labelKey) }}</span>
        </button>
      </nav>

      <div class="sc-sections">
        <!-- 界面语言（原在侧边栏底部，改到这里统一管理；仍存 localStorage，跟随浏览器） -->
        <section id="sc-language" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--indigo"><el-icon :size="17"><Compass /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.languageSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descLanguage') }}</div>
            </div>
          </div>
          <div class="sc-panel-body">
            <div class="sc-grid">
              <div class="sc-field">
                <el-select v-model="locale" @change="onLocaleChange">
                  <el-option
                    v-for="l in localeOptions"
                    :key="l.value"
                    :label="l.label"
                    :value="l.value"
                  />
                </el-select>
              </div>
            </div>
          </div>
        </section>

        <!-- 账号管理 -->
        <section id="sc-account" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--blue"><el-icon :size="17"><User /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.accountManagement') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descAccount') }}</div>
            </div>
            <el-button type="primary" size="small" @click="openUserDialog">
              <el-icon><Plus /></el-icon>
              <span class="sc-btn-text">{{ t('system.addUser') }}</span>
            </el-button>
          </div>
          <div class="sc-panel-body sc-panel-body--flush">
            <el-table :data="users" v-loading="usersLoading" class="sc-table">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="username" :label="t('system.username')" min-width="120" />
              <el-table-column prop="display_name" :label="t('system.displayName')" min-width="140" />
              <el-table-column :label="t('common.status')" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="dark" round>
                    {{ row.is_active ? t('common.enabled') : t('common.disabled') }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_active_at" :label="t('system.lastActiveAt')" min-width="160" />
              <el-table-column prop="created_at" :label="t('common.createdAt')" min-width="160" />
            </el-table>
          </div>
        </section>

        <!-- 修改我的密码 -->
        <section id="sc-password" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--violet"><el-icon :size="17"><Lock /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.changeMyPassword') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descPassword') }}</div>
            </div>
          </div>
          <div class="sc-panel-body">
            <el-form
              ref="pwdFormRef"
              :model="pwdForm"
              :rules="pwdRules"
              label-position="top"
              class="sc-form sc-grid"
            >
              <el-form-item :label="t('system.oldPassword')" prop="old_password">
                <el-input v-model="pwdForm.old_password" type="password" show-password />
              </el-form-item>
              <el-form-item :label="t('system.newPassword')" prop="new_password">
                <el-input v-model="pwdForm.new_password" type="password" show-password />
              </el-form-item>
              <el-form-item :label="t('system.confirmPassword')" prop="confirm_password">
                <el-input v-model="pwdForm.confirm_password" type="password" show-password />
              </el-form-item>
            </el-form>
            <div class="sc-actions">
              <el-button type="primary" :loading="pwdSubmitting" @click="submitPassword">
                {{ t('system.changePassword') }}
              </el-button>
              <span class="sc-note">{{ t('system.pwdTip') }}</span>
            </div>
          </div>
        </section>

        <!-- DeepSeek AI 配置 -->
        <section id="sc-ai" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--cyan"><el-icon :size="17"><MagicStick /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.deepseekSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descAi') }}</div>
            </div>
          </div>
          <div class="sc-panel-body" v-loading="loading">
            <div class="sc-grid">
              <div class="sc-field">
                <div class="sc-label">{{ t('systemConfig.apiKey') }}</div>
                <el-input v-model="form.api_key" type="password" show-password clearable />
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('systemConfig.model') }}</div>
                <el-input v-model="form.model" clearable />
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('systemConfig.baseUrl') }}</div>
                <el-input v-model="form.base_url" clearable />
              </div>
            </div>
            <div class="sc-actions">
              <el-button type="primary" :loading="saving" @click="save">
                {{ t('systemConfig.save') }}
              </el-button>
            </div>
          </div>
        </section>

        <!-- 出品默认值 -->
        <section id="sc-listing" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--amber"><el-icon :size="17"><Sell /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.listingDefaults') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descListing') }}</div>
            </div>
          </div>
          <div class="sc-panel-body" v-loading="listingDefLoading">
            <div class="sc-grid">
              <div class="sc-field sc-field--wide">
                <div class="sc-label">{{ t('system.defaultShippingFrom') }}</div>
                <el-cascader
                  v-model="listingDefForm.shipping_from_path"
                  :options="shippingFromCascaderOptions"
                  :props="shippingFromCascaderProps"
                  :show-all-levels="false"
                  filterable
                  clearable
                  placeholder=""
                  popper-class="product-type-cascader-popper"
                  @change="onShippingFromChange"
                />
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('system.defaultShippingMethod') }}</div>
                <el-select
                  v-model="listingDefForm.shipping_method"
                  clearable
                  placeholder=""
                  @change="saveListingDefaults"
                >
                  <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('system.defaultShippingPayer') }}</div>
                <el-select v-model="listingDefForm.shipping_payer" clearable placeholder="" @change="saveListingDefaults">
                  <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('system.defaultShippingDays') }}</div>
                <el-select v-model="listingDefForm.shipping_days" clearable placeholder="" @change="saveListingDefaults">
                  <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('system.defaultListingImage') }}</div>
                <el-select v-model="listingDefForm.watermark" placeholder="" @change="saveListingDefaults">
                  <el-option :label="t('system.listingImageWatermark')" :value="1" />
                  <el-option :label="t('system.listingImageNoWatermark')" :value="0" />
                </el-select>
              </div>
            </div>
          </div>
        </section>

        <!-- 回国模式：开启=全部在售暂停出售 + 禁止上架；关闭=只恢复本模式暂停的那些 -->
        <section id="sc-homecoming" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--rose"><el-icon :size="17"><Suitcase /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('homecoming.section') }}</div>
              <div class="sc-panel-desc">{{ t('homecoming.desc') }}</div>
            </div>
            <el-switch
              v-model="homecoming.enabled"
              :loading="homecomingSubmitting"
              :disabled="homecomingLoading || homecomingSubmitting"
              @change="onHomecomingChange"
            />
          </div>
          <div class="sc-panel-body" v-loading="homecomingLoading">
            <el-alert
              v-if="homecoming.enabled"
              :title="t('homecoming.onNotice')"
              type="warning"
              :closable="false"
              show-icon
            />
            <div class="sc-hc-stats">
              <span>{{ t('homecoming.onSaleCount', { n: homecoming.on_sale_count }) }}</span>
              <span>{{ t('homecoming.suspendedCount', { n: homecoming.suspended_count }) }}</span>
            </div>
            <div class="sc-actions">
              <el-button :loading="homecomingSubmitting" @click="retryHomecoming">
                {{ t('homecoming.retry') }}
              </el-button>
              <span class="sc-note">{{ t('homecoming.retryTip') }}</span>
            </div>
          </div>
        </section>

        <!-- 一键修改发货时效：把范围内在售商品的「発送までの日数」整批改成同一个值 -->
        <section id="sc-shipping-duration" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--sky"><el-icon :size="17"><Timer /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('shippingDurationBatch.section') }}</div>
              <div class="sc-panel-desc">{{ t('shippingDurationBatch.desc') }}</div>
            </div>
          </div>
          <div class="sc-panel-body">
            <div class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">{{ t('shippingDurationBatch.platform') }}</div>
                <el-select
                  v-model="sdForm.platform"
                  clearable
                  :placeholder="t('shippingDurationBatch.allPlatforms')"
                >
                  <el-option v-for="p in sdPlatformOptions" :key="p.value" :label="p.label" :value="p.value" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('shippingDurationBatch.account') }}</div>
                <el-select
                  v-model="sdForm.account_id"
                  clearable
                  :placeholder="t('shippingDurationBatch.allAccounts')"
                >
                  <el-option v-for="a in sdAccountOptions" :key="a.value" :label="a.label" :value="a.value" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('shippingDurationBatch.target') }}</div>
                <el-select v-model="sdForm.target">
                  <el-option v-for="s in sdTargetOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </div>
            </div>
            <div class="sc-hc-stats" v-loading="sdLoading">
              <span>{{ t('shippingDurationBatch.pendingCount', { n: sdPreview.pending }) }}</span>
              <span>{{ t('shippingDurationBatch.alreadyCount', { n: sdPreview.already }) }}</span>
            </div>
            <div class="sc-actions">
              <el-button
                type="primary"
                :loading="sdSubmitting"
                :disabled="sdLoading || sdPreview.pending === 0"
                @click="onSubmitShippingDuration"
              >
                {{ t('shippingDurationBatch.apply') }}
              </el-button>
              <span class="sc-note">{{ t('shippingDurationBatch.tip') }}</span>
            </div>
          </div>
        </section>

        <!-- 数据库管理（连接 / 切换 + 备份） -->
        <section id="sc-database" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--emerald"><el-icon :size="17"><Coin /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.databaseSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descDatabase') }}</div>
            </div>
            <div class="sc-seg">
              <button type="button" :class="{ 'is-on': dbPane === 'connect' }" @click="dbPane = 'connect'">连接 / 切换</button>
              <button type="button" :class="{ 'is-on': dbPane === 'backup' }" @click="dbPane = 'backup'">备份</button>
            </div>
          </div>

          <!-- v-show 而非 v-if：来回切换时两边已填的表单不丢 -->
          <div v-show="dbPane === 'connect'" class="sc-panel-body">
            <div class="sc-label">使用数据库</div>
            <div class="sc-choices">
              <button
                type="button"
                class="sc-choice"
                :class="{ 'is-on': dbForm.backend === 'sqlite' }"
                @click="dbForm.backend = 'sqlite'"
              >
                <span class="sc-choice-title">SQLite</span>
                <span class="sc-choice-sub">默认 · 本地文件</span>
                <span v-if="activeBackend === 'sqlite'" class="sc-choice-flag">当前</span>
              </button>
              <button
                type="button"
                class="sc-choice"
                :class="{ 'is-on': dbForm.backend === 'mysql' }"
                @click="dbForm.backend = 'mysql'"
              >
                <span class="sc-choice-title">MySQL</span>
                <span class="sc-choice-sub">独立服务器 · 8.0+</span>
                <span v-if="activeBackend === 'mysql'" class="sc-choice-flag">当前</span>
              </button>
            </div>

            <div v-if="dbForm.backend === 'mysql'" class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">主机</div>
                <el-input v-model="dbForm.mysql.host" />
              </div>
              <div class="sc-field">
                <div class="sc-label">端口</div>
                <el-input-number v-model="dbForm.mysql.port" :min="1" :max="65535" :controls="false" class="sc-num" />
              </div>
              <div class="sc-field">
                <div class="sc-label">用户</div>
                <el-input v-model="dbForm.mysql.user" />
              </div>
              <div class="sc-field">
                <div class="sc-label">密码</div>
                <el-input
                  v-model="dbForm.mysql.password"
                  type="password"
                  show-password
                  :placeholder="passwordSet ? '••••••••' : ''"
                />
              </div>
              <div class="sc-field">
                <div class="sc-label">数据库</div>
                <el-input v-model="dbForm.mysql.database" />
              </div>
            </div>

            <div class="sc-actions">
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
              <span v-if="testResult" class="sc-result" :class="{ 'is-ok': testResult.ok }">
                <span class="sc-dot" :class="testResult.ok ? 'is-ok' : 'is-bad'" />
                {{ testResult.message }}
                <template v-if="testResult.ok">
                  · 版本 {{ testResult.version }}
                  · 目标库{{ testResult.database_exists ? '已存在' : '不存在（将自动创建）' }}
                </template>
              </span>
            </div>
          </div>

          <div v-show="dbPane === 'backup'" class="sc-panel-body">
            <div class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">主机</div>
                <el-input v-model="backup.host" />
              </div>
              <div class="sc-field">
                <div class="sc-label">端口</div>
                <el-input-number v-model="backup.port" :min="1" :max="65535" :controls="false" class="sc-num" />
              </div>
              <div class="sc-field">
                <div class="sc-label">用户</div>
                <el-input v-model="backup.user" />
              </div>
              <div class="sc-field">
                <div class="sc-label">密码</div>
                <el-input v-model="backup.password" type="password" show-password />
              </div>
              <div class="sc-field">
                <div class="sc-label">目标库</div>
                <el-input v-model="backup.database" />
              </div>
            </div>
            <div class="sc-actions">
              <el-button :loading="testingBackup" @click="onTestBackup">测试连接</el-button>
              <el-button type="primary" :loading="backuping" :disabled="!backup.database" @click="onBackup">开始备份</el-button>
              <span v-if="backupTestResult" class="sc-result" :class="{ 'is-ok': backupTestResult.ok }">
                <span class="sc-dot" :class="backupTestResult.ok ? 'is-ok' : 'is-bad'" />
                {{ backupTestResult.message }}
                <template v-if="backupTestResult.ok">
                  · 版本 {{ backupTestResult.version }}
                  · 目标库{{ backupTestResult.database_exists ? '已存在' : '不存在（将自动创建）' }}
                </template>
              </span>
            </div>
          </div>

          <!-- 迁移 / 备份结果紧跟在数据库区块里，不再落到页面最底部 -->
          <div v-if="migrateSummary.length" class="sc-panel-body sc-panel-body--sub">
            <div class="sc-sub-title">迁移 / 备份结果（逐表行数校验）</div>
            <el-table :data="migrateSummary" size="small" max-height="360" class="sc-table">
              <el-table-column prop="table" label="表" min-width="220" />
              <el-table-column prop="src" label="源行数" width="100" align="right" />
              <el-table-column prop="dst" label="目标行数" width="100" align="right" />
              <el-table-column label="状态" width="120" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'OK' ? 'success' : (row.status.includes('不一致') ? 'danger' : 'info')" size="small" effect="dark" round>
                    {{ row.status }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <!-- 图床存储：商品图存本机 imges 目录，还是存独立图床服务 -->
        <section id="sc-image-hosting" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--emerald"><el-icon :size="17"><Picture /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.imageHostingSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descImageHosting') }}</div>
            </div>
          </div>

          <div class="sc-panel-body">
            <div class="sc-label">图片存储位置</div>
            <div class="sc-choices">
              <button
                type="button"
                class="sc-choice"
                :class="{ 'is-on': ihForm.backend === 'local' }"
                @click="ihForm.backend = 'local'"
              >
                <span class="sc-choice-title">本地存储</span>
                <span class="sc-choice-sub">默认 · backend/imges 目录</span>
                <span v-if="ih.backend === 'local'" class="sc-choice-flag">当前</span>
              </button>
              <button
                type="button"
                class="sc-choice"
                :class="{ 'is-on': ihForm.backend === 'remote' }"
                @click="ihForm.backend = 'remote'"
              >
                <span class="sc-choice-title">图床存储</span>
                <span class="sc-choice-sub">独立图床服务 · 浏览器直连取图</span>
                <span v-if="ih.backend === 'remote'" class="sc-choice-flag">当前</span>
              </button>
            </div>

            <div class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">图床地址</div>
                <el-input v-model="ihForm.base_url" placeholder="http://127.0.0.1:9990" />
                <span class="sc-note">后端访问图床用的地址，只填协议 + 域名（可带端口）</span>
              </div>
              <div class="sc-field">
                <div class="sc-label">对外地址</div>
                <el-input v-model="ihForm.public_base" placeholder="留空 = 与图床地址相同" />
                <span class="sc-note">浏览器访问图片用的地址。后端走内网直连、浏览器走对外域名时才需要单独填</span>
              </div>
              <div class="sc-field">
                <div class="sc-label">项目 slug</div>
                <el-input v-model="ihForm.project" placeholder="project-xxxxxxxxxxxx" />
                <span class="sc-note">在图床「项目详情」页地址栏里的那一段</span>
              </div>
              <div class="sc-field">
                <div class="sc-label">API Token</div>
                <el-input
                  v-model="ihForm.token"
                  type="password"
                  show-password
                  :placeholder="ih.token_set ? '••••••••（留空 = 不修改）' : '在图床项目详情页复制'"
                />
              </div>
              <div class="sc-field">
                <div class="sc-label">请求超时（秒）</div>
                <el-input-number v-model="ihForm.timeout" :min="3" :max="300" :controls="false" class="sc-num" />
              </div>
              <div class="sc-field">
                <div class="sc-label">图片投递方式</div>
                <el-select v-model="ihForm.delivery">
                  <el-option label="跳转（浏览器直连图床）" value="redirect" />
                  <el-option label="代理（本服务转发）" value="proxy" />
                </el-select>
                <span class="sc-note">图床只在内网可达时选「代理」；跳转不占本服务带宽，是推荐值</span>
              </div>
              <div class="sc-field">
                <div class="sc-label">校验 HTTPS 证书</div>
                <el-switch v-model="ihForm.verify_tls" />
                <span class="sc-note">图床用自签名证书时才关闭</span>
              </div>
            </div>

            <div class="sc-actions">
              <el-button :loading="ihSaving" @click="onSaveImageHosting">保存连接信息</el-button>
              <el-button :loading="ihTesting" :disabled="!ih.configured" @click="onTestImageHosting">测试连接</el-button>
              <el-button
                v-if="ihForm.backend !== ih.backend"
                type="primary"
                :disabled="ihForm.backend === 'remote' && !ih.configured"
                :loading="ihSwitching"
                @click="onSwitchImageHosting"
              >
                切换到{{ ihForm.backend === 'remote' ? '图床' : '本地' }}存储（立即生效）
              </el-button>
              <span v-if="ihTestResult" class="sc-result" :class="{ 'is-ok': ihTestResult.ok }">
                <span class="sc-dot" :class="ihTestResult.ok ? 'is-ok' : 'is-bad'" />
                {{ ihTestResult.message }}
                <template v-if="ihTestResult.ok">
                  · 单文件上限 {{ ihTestResult.max_upload_mb }} MB
                </template>
              </span>
            </div>

            <!-- 混合内容：HTTPS 页面加载 http:// 图片会被浏览器直接拦掉，而且只在控制台报错，
                 页面上看到的是一片裂图。这个错配值得在保存前就说清楚。 -->
            <el-alert
              v-if="ihMixedContentWarning"
              type="warning"
              :closable="false"
              show-icon
              title="当前页面是 HTTPS，但图床对外地址是 http://"
              description="浏览器会拦截 HTTPS 页面里的 http 图片（混合内容），图片会全部显示不出来。请把图床也配成 HTTPS，或把「图片投递方式」改为「代理」由本服务转发。"
              style="margin-top: 12px"
            />
            <el-alert
              v-if="ihTestResult && ihTestResult.ok && !ihTestResult.public_base_url && !ihForm.public_base"
              type="info"
              :closable="false"
              show-icon
              title="图床未配置「公开访问基地址」"
              description="此时图床返回的图片 URL 由它收到的请求地址推导而来，可能是内网地址。请在图床的系统设置里填写公开访问基地址，或在上面的「对外地址」里填写浏览器能访问到的地址。"
              style="margin-top: 12px"
            />
          </div>

          <!-- 图片搬运：切换后端是瞬时的，历史图片的搬运在后台跑 -->
          <div class="sc-panel-body sc-panel-body--sub">
            <div class="sc-sub-title">历史图片搬运</div>
            <div class="sc-note" style="margin-bottom: 10px">
              切换存储位置只决定「新图片往哪写」，立即生效、不需要重启。历史图片由下面的搬运作业在后台处理：
              还没搬过去的图片继续从原处读取，页面不会出现裂图；中断后再次点击会接着搬剩下的。
            </div>
            <div class="sc-inline" style="flex-wrap: wrap; gap: 10px">
              <el-tag size="small" effect="plain" round>本地 {{ ih.local_files }} 张</el-tag>
              <el-tag size="small" effect="plain" round type="success">图床 {{ ih.remote_records }} 张</el-tag>
              <el-tag v-if="ih.pending_upload > 0" size="small" effect="dark" round type="warning">
                待迁移 {{ ih.pending_upload }} 张 · {{ formatBytes(ih.pending_bytes) }}
              </el-tag>
            </div>

            <div class="sc-actions">
              <el-button
                type="primary"
                :disabled="!ih.configured || ihJob.running"
                :loading="ihMigrating"
                @click="onMigrateImages"
              >
                迁移图片到图床{{ ih.pending_upload > 0 ? `（${ih.pending_upload} 张）` : '' }}
              </el-button>
              <el-button
                :disabled="!ih.configured || ihJob.running || ih.remote_records === 0"
                :loading="ihRollingBack"
                @click="onRollbackImages"
              >
                回迁到本地（{{ ih.remote_records }} 张）
              </el-button>
              <el-button v-if="ihJob.running" type="danger" plain @click="onCancelImageJob">停止搬运</el-button>
            </div>

            <div v-if="ihJob.direction" class="sc-field" style="margin-top: 6px">
              <el-progress
                :percentage="ihJob.percent"
                :status="ihJob.running ? undefined : (ihJob.failed ? 'warning' : 'success')"
                :stroke-width="14"
              />
              <span class="sc-note">
                {{ ihJob.direction === 'to_host' ? '正在迁移到图床' : '正在回迁到本地' }}
                · 成功 {{ ihJob.done }} · 跳过 {{ ihJob.skipped }} · 失败 {{ ihJob.failed }} / 共 {{ ihJob.total }}
                <template v-if="ihJob.running && ihJob.current"> · {{ ihJob.current }}</template>
              </span>
              <span v-if="ihJob.message" class="sc-note">{{ ihJob.message }}</span>
            </div>

            <div v-if="ihJob.errors.length" class="sc-field" style="margin-top: 6px">
              <div class="sc-sub-title">失败明细（最多 100 条，这些图片仍留在原处，可再次搬运）</div>
              <el-table :data="ihJob.errors" size="small" max-height="240" class="sc-table">
                <el-table-column prop="path" label="图片" min-width="240" show-overflow-tooltip />
                <el-table-column prop="error" label="原因" min-width="280" show-overflow-tooltip />
              </el-table>
            </div>
          </div>
        </section>

        <!-- 二维码打印参数：存 localStorage（跟随浏览器，蓝牙配对本身也是按浏览器授权的） -->
        <section id="sc-qrparams" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--rose"><el-icon :size="17"><Tickets /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('qrPrint.paramsSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descQrParams') }}</div>
            </div>
          </div>
          <div class="sc-panel-body">
            <div class="sc-grid sc-grid--narrow">
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.labelSize') }}</div>
                <div class="sc-inline">
                  <el-input-number v-model="printerCfg.labelWmm" :min="10" :max="100" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">×</span>
                  <el-input-number v-model="printerCfg.labelHmm" :min="10" :max="100" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">mm</span>
                </div>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.headWidth') }}</div>
                <div class="sc-inline">
                  <el-input-number v-model="printerCfg.headMm" :min="20" :max="110" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">mm</span>
                </div>
              </div>
              <div class="sc-field">
                <div class="sc-label">DPI</div>
                <el-input-number v-model="printerCfg.dpi" :min="100" :max="600" :controls="false" class="sc-num" @change="savePrinterCfg" />
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.chunk') }}</div>
                <div class="sc-inline">
                  <el-input-number v-model="printerCfg.chunk" :min="20" :max="512" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">{{ t('qrPrint.chunkUnit') }}</span>
                </div>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.feed') }}</div>
                <div class="sc-inline">
                  <el-input-number v-model="printerCfg.feedMm" :min="0" :max="60" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">mm</span>
                </div>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.retract') }}</div>
                <div class="sc-inline">
                  <el-input-number v-model="printerCfg.retractMm" :min="0" :max="60" :precision="1" :step="0.5" :controls="false" class="sc-num" @change="savePrinterCfg" />
                  <span class="sc-unit">mm</span>
                </div>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.retractCmd') }}</div>
                <el-select v-model="printerCfg.retractCmd" @change="savePrinterCfg">
                  <el-option label="FF" value="ff" />
                  <el-option label="GS FF" value="gsff" />
                  <el-option label="ESC K" value="escK" />
                  <el-option label="ESC e" value="escE" />
                  <el-option label="TSPL BACKFEED" value="tspl" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.density') }}</div>
                <el-input-number v-model="printerCfg.density" :min="1" :max="31" :controls="false" class="sc-num" @change="savePrinterCfg" />
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.threshold') }}</div>
                <el-input-number v-model="printerCfg.threshold" :min="10" :max="245" :controls="false" class="sc-num" @change="savePrinterCfg" />
              </div>
            </div>
          </div>
        </section>

        <!-- 打印机连接：连接 / 测试打印 / 忘记设备 -->
        <section id="sc-printer" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--sky"><el-icon :size="17"><Printer /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('qrPrint.connSection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descPrinter') }}</div>
            </div>
            <el-tag :type="printerState.connected ? 'success' : 'info'" effect="dark" round size="small">
              {{ printerState.connected ? t('qrPrint.connected') : t('qrPrint.disconnected') }}
            </el-tag>
          </div>
          <div class="sc-panel-body">
            <div class="sc-device" :class="{ 'is-on': printerState.connected }">
              <span class="sc-device-ic"><el-icon :size="20"><Printer /></el-icon></span>
              <div class="sc-device-text">
                <div class="sc-device-name">{{ printerState.deviceName || t('qrPrint.noDevice') }}</div>
                <!-- 免弹框自动重连：需浏览器支持 getDevices（Chrome/Edge 持久化蓝牙授权） -->
                <div class="sc-device-sub" :class="autoReconnectOk ? 'is-ok' : 'is-warn'">
                  {{ t('qrPrint.autoReconnect') }} · {{ autoReconnectOk ? t('qrPrint.autoReconnectOk') : t('qrPrint.autoReconnectNo') }}
                </div>
              </div>
            </div>

            <!-- 整表发现出多个可写特征时才显示，默认自动选第一个并持久化 -->
            <div v-if="printerState.writableChars.length > 1" class="sc-field sc-field--stack">
              <div class="sc-label">{{ t('qrPrint.writeChar') }}</div>
              <el-select :model-value="printerState.charUuid" @change="onPickChar">
                <el-option
                  v-for="c in printerState.writableChars"
                  :key="c.uuid"
                  :label="c.uuid + '  [' + c.flags + ']'"
                  :value="c.uuid"
                />
              </el-select>
            </div>

            <div class="sc-actions">
              <el-button type="primary" :loading="connecting" @click="onConnect">{{ t('qrPrint.connect') }}</el-button>
              <el-button :loading="qrTesting" @click="onQrTest">{{ t('qrPrint.testPrint') }}</el-button>
              <el-button type="danger" plain @click="onForget">{{ t('qrPrint.forget') }}</el-button>
            </div>
          </div>
        </section>

        <!-- Cookie 注入域名：代理经 nginx 以独立域名发布时的对外基址 -->
        <section id="sc-proxy" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic sc-ic--cyan"><el-icon :size="17"><Link /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.proxySection') }}</div>
              <div class="sc-panel-desc">{{ t('systemConfig.descProxy') }}</div>
            </div>
          </div>
          <div class="sc-panel-body" v-loading="proxyLoading">
            <div class="sc-field">
              <div class="sc-label">{{ t('systemConfig.proxyPublicBase') }}</div>
              <el-input
                v-model="proxyPublicBase"
                clearable
                :placeholder="t('systemConfig.proxyPublicBasePlaceholder')"
              />
            </div>
            <el-alert
              v-if="proxyPublicBase.trim()"
              type="warning"
              show-icon
              :closable="false"
              :title="t('systemConfig.proxyWarning')"
              style="margin-top: 12px"
            />
            <div class="sc-actions">
              <el-button type="primary" :loading="proxySaving" @click="saveProxyBase">
                {{ t('systemConfig.save') }}
              </el-button>
            </div>
          </div>
        </section>
      </div>
    </div>

    <el-dialog v-model="userDialogVisible" :title="t('system.addUser')" width="420px" class="sc-dialog" destroy-on-close>
      <el-form ref="userFormRef" :model="userForm" :rules="userRules" label-position="top">
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
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Plus, User, Lock, MagicStick, Sell, Coin, Tickets, Printer, Compass, Suitcase, Timer, Link, Picture } from '@element-plus/icons-vue'
import { ElMessage } from '@/utils/notify'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { authApi, configApi, shopAccountApi } from '@/api/index.js'
import { databaseApi } from '@/api/database'
import { imageHostingApi } from '@/api/image_hosting'
import {
  printTestLabel,
  loadPrinterConfig,
  savePrinterConfig,
  fetchPrinterConfig,
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

const { t, locale } = useI18n()

// ===== 区块锚点导航（图标名走全局注册的 element-plus 图标，与 Layout 侧边栏一致）=====
const SECTIONS = [
  { id: 'language', icon: 'Compass', labelKey: 'systemConfig.languageSection' },
  { id: 'account', icon: 'User', labelKey: 'system.accountManagement' },
  { id: 'password', icon: 'Lock', labelKey: 'system.changeMyPassword' },
  { id: 'ai', icon: 'MagicStick', labelKey: 'systemConfig.deepseekSection' },
  { id: 'listing', icon: 'Sell', labelKey: 'system.listingDefaults' },
  { id: 'homecoming', icon: 'Suitcase', labelKey: 'homecoming.section' },
  { id: 'shipping-duration', icon: 'Timer', labelKey: 'shippingDurationBatch.section' },
  { id: 'database', icon: 'Coin', labelKey: 'systemConfig.databaseSection' },
  { id: 'image-hosting', icon: 'Picture', labelKey: 'systemConfig.imageHostingSection' },
  { id: 'qrparams', icon: 'Tickets', labelKey: 'qrPrint.paramsSection' },
  { id: 'printer', icon: 'Printer', labelKey: 'qrPrint.connSection' },
  { id: 'proxy', icon: 'Link', labelKey: 'systemConfig.proxySection' },
]

const pageRef = ref(null)
const activeSection = ref(SECTIONS[0].id)
/** 真正的滚动容器是 Layout 的 .main-content，不是 window */
let scrollRoot = null

function goSection(id) {
  document.getElementById(`sc-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  activeSection.value = id
}

/** 取最后一个越过「顶部 96px」的区块作为当前区块 */
function syncActiveSection() {
  const rootTop = scrollRoot ? scrollRoot.getBoundingClientRect().top : 0
  let current = SECTIONS[0].id
  for (const s of SECTIONS) {
    const el = document.getElementById(`sc-${s.id}`)
    if (el && el.getBoundingClientRect().top - rootTop <= 96) current = s.id
  }
  activeSection.value = current
}

// ===== 界面语言（无后端，setLocale 会写 localStorage 并同步 element-plus 语言包）=====
const localeOptions = computed(() => SUPPORTED_LOCALES.map(code => ({
  value: code,
  label: t(`lang.${code}`),
})))

function onLocaleChange(val) {
  setLocale(val)
}

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

// ===== Cookie 注入域名 =====
const proxyLoading = ref(false)
const proxySaving = ref(false)
const proxyPublicBase = ref('')

async function loadProxyBase() {
  proxyLoading.value = true
  try {
    const res = await configApi.getProxyPublicBase()
    proxyPublicBase.value = res?.public_base || ''
  } catch {
    ElMessage.error(t('systemConfig.loadFailed'))
  } finally {
    proxyLoading.value = false
  }
}

async function saveProxyBase() {
  proxySaving.value = true
  try {
    const res = await configApi.putProxyPublicBase(proxyPublicBase.value.trim())
    // 回填后端规范化后的值（去掉末尾斜杠等），避免界面显示与实际存储不一致
    proxyPublicBase.value = res?.public_base || ''
    ElMessage.success(t('systemConfig.saveSuccess'))
  } catch {
    /* 错误由 axios 拦截器提示（含后端的格式校验 400） */
  } finally {
    proxySaving.value = false
  }
}

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

// ===== 回国模式 =====
// 开关本身在 PUT 返回时就已生效（后端立刻禁止上架）；暂停/恢复整批在售商品是后台任务，
// 进度看 /#/tasks。两个计数用来判断是否还有漏网之鱼：开启后「在售中」应为 0，
// 关闭后「待恢复」应为 0，不为 0 时点「重试」再跑一轮（只处理剩下的）。
const homecoming = reactive({ enabled: false, on_sale_count: 0, suspended_count: 0 })
const homecomingLoading = ref(false)
const homecomingSubmitting = ref(false)

function applyHomecoming(res) {
  homecoming.enabled = !!res?.enabled
  homecoming.on_sale_count = Number(res?.on_sale_count) || 0
  homecoming.suspended_count = Number(res?.suspended_count) || 0
}

async function loadHomecoming() {
  homecomingLoading.value = true
  try {
    applyHomecoming(await configApi.getHomecoming())
  } catch {
    /* 拦截器已提示 */
  } finally {
    homecomingLoading.value = false
  }
}

async function submitHomecoming(enable) {
  homecomingSubmitting.value = true
  try {
    applyHomecoming(await configApi.putHomecoming(enable))
    ElMessage.success(t('homecoming.submitted'))
  } catch {
    // 提交失败（例如已有同类任务在排队）→ 回到后端的真实开关状态，不留下假开关
    await loadHomecoming()
  } finally {
    homecomingSubmitting.value = false
  }
}

/** el-switch 已经把值改掉了，确认框取消时要手工改回去 */
async function onHomecomingChange(val) {
  const target = !!val
  try {
    await ElMessageBox.confirm(
      target ? t('homecoming.confirmOnMsg', { n: homecoming.on_sale_count }) : t('homecoming.confirmOffMsg', { n: homecoming.suspended_count }),
      target ? t('homecoming.confirmOnTitle') : t('homecoming.confirmOffTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    homecoming.enabled = !target
    return
  }
  await submitHomecoming(target)
}

/** 重试：按当前开关方向再跑一轮，只处理上一轮没做完的商品 */
function retryHomecoming() {
  return submitHomecoming(homecoming.enabled)
}

// ===== 一键修改发货时效 =====
// 后端只改「当前时效 ≠ 目标」的在售商品（出售中 + 暂停出售），所以同一组参数点两次是安全的：
// 第二次只会处理上一次失败/没轮到的那些。件数由后端纯 SQL 算，改筛选就重新拉一次。
const sdForm = reactive({ platform: '', account_id: null, target: '2' })
const sdPreview = reactive({ pending: 0, already: 0 })
const sdAccounts = ref([])
const sdLoading = ref(false)
const sdSubmitting = ref(false)

const sdPlatformOptions = computed(() => [
  { value: 'mercari', label: t('shippingDurationBatch.platformMercari') },
  { value: 'yahoo', label: t('shippingDurationBatch.platformYahoo') },
])

/** 目标时效（值 = 煤炉 shipping_duration.id，雅虎侧由后端映射成自己的枚举） */
const sdTargetOptions = computed(() => [
  { value: '1', label: t('shippingDurationBatch.duration1') },
  { value: '2', label: t('shippingDurationBatch.duration2') },
  { value: '3', label: t('shippingDurationBatch.duration3') },
])

/** 账号下拉随平台收窄；只列有卖家ID的启用账号（在售表里只有 seller_id 可匹配） */
const sdAccountOptions = computed(() =>
  sdAccounts.value
    .filter((a) => !sdForm.platform || a.platform === sdForm.platform)
    .map((a) => ({ value: a.id, label: a.label }))
)

async function loadSdAccounts() {
  try {
    const res = await shopAccountApi.list({ page: 1, page_size: 200 })
    sdAccounts.value = (res.items || [])
      .filter((a) => a.status === 'active' && String(a.seller_id || '').trim())
      .map((a) => ({
        id: a.id,
        platform: String(a.platform || '').trim() || 'mercari',
        label: `${a.account_name} (${a.seller_id})`,
      }))
  } catch {
    sdAccounts.value = []
  }
}

async function loadSdPreview() {
  sdLoading.value = true
  try {
    const res = await configApi.getShippingDurationPreview({
      target: sdForm.target,
      platform: sdForm.platform || undefined,
      account_id: sdForm.account_id ?? undefined,
    })
    sdPreview.pending = Number(res?.pending) || 0
    sdPreview.already = Number(res?.already) || 0
  } catch {
    sdPreview.pending = 0
    sdPreview.already = 0
  } finally {
    sdLoading.value = false
  }
}

/** 平台变了就把不属于该平台的账号选择清掉，否则会算出恒为 0 的件数 */
watch(
  () => sdForm.platform,
  () => {
    if (sdForm.account_id && !sdAccountOptions.value.some((a) => a.value === sdForm.account_id)) {
      sdForm.account_id = null
    }
  }
)

watch(() => [sdForm.platform, sdForm.account_id, sdForm.target], loadSdPreview)

async function onSubmitShippingDuration() {
  const name = sdTargetOptions.value.find((o) => o.value === sdForm.target)?.label || ''
  try {
    await ElMessageBox.confirm(
      t('shippingDurationBatch.confirmMsg', { n: sdPreview.pending, name }),
      t('shippingDurationBatch.confirmTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  sdSubmitting.value = true
  try {
    const res = await configApi.submitShippingDuration({
      target: sdForm.target,
      platform: sdForm.platform || null,
      account_id: sdForm.account_id ?? null,
    })
    ElMessage.success(t('shippingDurationBatch.submitted'))
    sdPreview.pending = Number(res?.pending) || 0
    sdPreview.already = Number(res?.already) || 0
  } catch {
    /* 拦截器已提示（例如已有同类任务在排队） */
  } finally {
    sdSubmitting.value = false
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

// ===== 图床存储 =====
// ih   = 服务端当前状态（生效的存储位置 + 图片数量概览）
// ihForm = 表单草稿；backend 只有点「切换」才会真正生效，改选项本身不做任何事
const ih = reactive({
  backend: 'local', token_set: false, configured: false,
  local_files: 0, remote_records: 0, pending_upload: 0, pending_bytes: 0
})
const ihForm = reactive({
  backend: 'local', base_url: '', public_base: '', project: '', token: '',
  timeout: 30, verify_tls: true, delivery: 'redirect'
})
const ihJob = reactive({
  running: false, direction: null, total: 0, done: 0, skipped: 0, failed: 0,
  percent: 0, current: '', message: '', errors: []
})
const ihSaving = ref(false)
const ihTesting = ref(false)
const ihSwitching = ref(false)
const ihMigrating = ref(false)
const ihRollingBack = ref(false)
const ihTestResult = ref(null)
let ihPollTimer = null

/** HTTPS 页面 + http 图床 + 跳转投递 = 浏览器按混合内容拦截，图片全裂。代理投递不受影响。 */
const ihMixedContentWarning = computed(() => {
  if (ihForm.delivery !== 'redirect') return false
  if (window.location.protocol !== 'https:') return false
  const base = (ihForm.public_base || ihForm.base_url || '').trim()
  return base.startsWith('http://')
})

function formatBytes(value) {
  let amount = Number(value) || 0
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  for (const unit of units) {
    if (amount < 1024 || unit === 'TB') return `${amount.toFixed(1)} ${unit}`
    amount /= 1024
  }
  return `${amount.toFixed(1)} TB`
}

async function loadImageHosting() {
  const cfg = await imageHostingApi.getConfig()
  Object.assign(ih, {
    backend: cfg.backend, token_set: cfg.token_set, configured: cfg.configured,
    local_files: cfg.local_files, remote_records: cfg.remote_records,
    pending_upload: cfg.pending_upload, pending_bytes: cfg.pending_bytes
  })
  // Token 永远留空：服务端不回传明文，留空提交即「不修改」
  Object.assign(ihForm, {
    backend: cfg.backend, base_url: cfg.base_url, public_base: cfg.public_base,
    project: cfg.project, token: '', timeout: cfg.timeout,
    verify_tls: cfg.verify_tls, delivery: cfg.delivery
  })
}

/** 拉一次搬运进度；作业还在跑就安排下一次轮询，跑完则刷新概览数字 */
async function pollImageJob() {
  clearTimeout(ihPollTimer)
  let job
  try {
    job = await imageHostingApi.getMigration()
  } catch (e) {
    return  // 错误提示已由 http 拦截器统一处理，不要因为一次轮询失败就把轮询停掉
  } finally {
    ihMigrating.value = false
    ihRollingBack.value = false
  }
  Object.assign(ihJob, job, { errors: job.errors || [] })
  if (job.running) {
    ihPollTimer = setTimeout(pollImageJob, 1500)
  } else {
    loadImageHosting()
  }
}

async function onSaveImageHosting() {
  ihSaving.value = true
  ihTestResult.value = null
  try {
    // token 留空不提交：提交空串会被当成「清空 Token」
    const payload = {
      base_url: ihForm.base_url, public_base: ihForm.public_base,
      project: ihForm.project, timeout: ihForm.timeout,
      verify_tls: ihForm.verify_tls, delivery: ihForm.delivery
    }
    if (ihForm.token) payload.token = ihForm.token
    await imageHostingApi.saveConfig(payload)
    await loadImageHosting()
    ElMessage.success('图床连接信息已保存')
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    ihSaving.value = false
  }
}

async function onTestImageHosting() {
  ihTesting.value = true
  ihTestResult.value = null
  try {
    ihTestResult.value = await imageHostingApi.test()
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    ihTesting.value = false
  }
}

async function onSwitchImageHosting() {
  const target = ihForm.backend === 'remote' ? '图床' : '本地'
  try {
    await ElMessageBox.confirm(
      `将把新产生的图片改为存到${target}。立即生效、无需重启；已有图片仍从原处读取，需要另外点击搬运按钮才会挪动。是否继续？`,
      '确认切换图片存储位置',
      { type: 'warning' }
    )
  } catch { return }
  ihSwitching.value = true
  try {
    await imageHostingApi.setBackend(ihForm.backend)
    await loadImageHosting()
    ElMessage.success(`已切换到${target}存储，已即时生效`)
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    ihSwitching.value = false
  }
}

async function onMigrateImages() {
  try {
    await ElMessageBox.confirm(
      `将把本地 ${ih.pending_upload} 张图片上传到图床，并把存储位置切换为图床（立即生效）。` +
      '搬运在后台进行，未搬完的图片继续从本地读取，页面不会出现裂图；中断后再次点击会接着搬剩下的。是否继续？',
      '确认迁移图片到图床',
      { type: 'warning' }
    )
  } catch { return }
  ihMigrating.value = true
  try {
    await imageHostingApi.migrate({ activate: true })
    pollImageJob()
  } catch (e) {
    ihMigrating.value = false
  }
}

async function onRollbackImages() {
  let deleteRemote = false
  try {
    // 「取消」按钮改成第二个动作：回迁 + 删除图床副本。默认（确定）只回迁、保留副本。
    const action = await ElMessageBox.confirm(
      `将把图床上的 ${ih.remote_records} 张图片下载回本地 imges 目录，并把存储位置切回本地（立即生效）。` +
      '图床上的副本默认保留；如需一并删除，请选「回迁并删除图床副本」。',
      '确认回迁图片到本地',
      {
        type: 'warning',
        confirmButtonText: '回迁并保留图床副本',
        cancelButtonText: '回迁并删除图床副本',
        distinguishCancelAndClose: true
      }
    ).then(() => 'keep').catch((reason) => {
      if (reason === 'cancel') return 'delete'
      throw reason
    })
    deleteRemote = action === 'delete'
  } catch { return }
  ihRollingBack.value = true
  try {
    await imageHostingApi.rollback({ activate: true, delete_remote: deleteRemote })
    pollImageJob()
  } catch (e) {
    ihRollingBack.value = false
  }
}

async function onCancelImageJob() {
  try {
    await imageHostingApi.cancelMigration()
    pollImageJob()
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  }
}

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

// 打印参数存数据库，进页面时以库里的为准刷新表单（拉不到就保持本地镜像值）
async function loadPrinterParams() {
  Object.assign(printerCfg, await fetchPrinterConfig())
}

function savePrinterCfg() {
  savePrinterConfig({
    labelWmm: Number(printerCfg.labelWmm) || 30,
    labelHmm: Number(printerCfg.labelHmm) || 30,
    headMm: Number(printerCfg.headMm) || 48,
    dpi: Number(printerCfg.dpi) || 203,
    chunk: Number(printerCfg.chunk) || 180,
    feedMm: Math.max(0, Number(printerCfg.feedMm) || 0),
    retractMm: Math.max(0, Number(printerCfg.retractMm) || 0),
    retractCmd: printerCfg.retractCmd || 'escK',
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
  loadHomecoming()
  loadSdAccounts()
  loadSdPreview()
  loadDbConfig()
  loadImageHosting()
  pollImageJob()
  loadPrinterParams()
  loadProxyBase()

  scrollRoot = pageRef.value?.closest('.main-content') || null
  ;(scrollRoot || window).addEventListener('scroll', syncActiveSection, { passive: true })
  syncActiveSection()
})

onUnmounted(() => {
  ;(scrollRoot || window).removeEventListener('scroll', syncActiveSection)
  // 离开页面就停掉搬运进度轮询：作业在后端继续跑，回来时 onMounted 会重新拉一次进度
  clearTimeout(ihPollTimer)
})
</script>

<style scoped>
/* 配色沿用全站暗色（页面底 #0b1220 / 卡片 #131c2f / 描边 #2a3446），
   这里只把「一堆并排卡片」改成「页头 + 锚点导航 + 单列区块」的设置页版式。 */
.sc {
  --sc-line: #26314a;
  --sc-line-soft: #202a41;
  --sc-text: #e6edf7;
  --sc-text-dim: #9ba8bf;
  --sc-text-mute: #7f8da6;
  --sc-accent: #5b8cff;
  /* 跟随窗口，不设上限：外层 .main-content 已经给了 20px 内边距 */
  width: 100%;
}

/* ── 页头 ──────────────────────────────────────────────────── */
.sc-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 20px 24px;
  margin-bottom: 18px;
  border: 1px solid var(--sc-line);
  border-radius: 16px;
  background:
    radial-gradient(760px 200px at 6% -60%, rgba(91, 140, 255, 0.22), transparent 70%),
    linear-gradient(180deg, #16203a, #111a2c);
}
.sc-hero-title {
  font-size: 21px;
  font-weight: 650;
  line-height: 1.2;
  color: #f2f6ff;
}
.sc-hero-sub {
  margin-top: 6px;
  font-size: 13px;
  color: var(--sc-text-mute);
}
.sc-hero-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.sc-stat {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 13px;
  border: 1px solid var(--sc-line);
  border-radius: 999px;
  background: rgba(11, 18, 32, 0.55);
  font-size: 12px;
}
.sc-stat-label {
  color: var(--sc-text-mute);
}
.sc-stat-value {
  color: var(--sc-text);
  font-weight: 600;
}
.sc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: #4c5b78;
}
.sc-dot.is-ok {
  background: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.16);
}
.sc-dot.is-bad {
  background: #f56c6c;
  box-shadow: 0 0 0 3px rgba(245, 108, 108, 0.16);
}

/* ── 版式：左锚点导航 + 右单列区块 ────────────────────────── */
.sc-body {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.sc-nav {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  border: 1px solid var(--sc-line);
  border-radius: 14px;
  background: rgba(19, 28, 47, 0.82);
  backdrop-filter: blur(8px);
}
.sc-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 9px;
  background: none;
  color: var(--sc-text-dim);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
/* 触摸屏 :hover 会粘住：点过的锚点会一直亮着底色，和 is-active 混在一起 */
@media (hover: hover) {
  .sc-nav-item:hover {
    background: #18233a;
    color: var(--sc-text);
  }
}
.sc-nav-item.is-active {
  background: linear-gradient(90deg, rgba(91, 140, 255, 0.2), rgba(91, 140, 255, 0.04));
  color: #fff;
  box-shadow: inset 2px 0 0 var(--sc-accent);
}
.sc-nav-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sc-sections {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

/* ── 区块 ──────────────────────────────────────────────────── */
.sc-panel {
  border: 1px solid var(--sc-line);
  border-radius: 14px;
  /* 账号表格是贴边铺满的，不裁切的话会把圆角顶成直角 */
  overflow: hidden;
  background: linear-gradient(180deg, #141d31, #111a2c);
  /* 点导航滚过来时，标题不要顶到容器边 */
  scroll-margin-top: 12px;
}
.sc-panel-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 15px 18px;
  border-bottom: 1px solid var(--sc-line-soft);
}
.sc-head-text {
  flex: 1;
  min-width: 160px;
}
.sc-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--sc-text);
}
.sc-panel-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--sc-text-mute);
}
.sc-btn-text {
  margin-left: 4px;
}
.sc-panel-body {
  padding: 18px;
}
.sc-panel-body--flush {
  padding: 0;
}
.sc-panel-body--sub {
  border-top: 1px solid var(--sc-line-soft);
}
.sc-sub-title {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--sc-text);
}

/* 区块图标：色相只用于快速定位，与左侧导航一一对应 */
.sc-ic {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  border: 1px solid transparent;
}
.sc-ic--indigo { background: rgba(129, 140, 248, 0.14); border-color: rgba(129, 140, 248, 0.26); color: #949dfb; }
.sc-ic--blue { background: rgba(91, 140, 255, 0.14); border-color: rgba(91, 140, 255, 0.24); color: #7ea6ff; }
.sc-ic--violet { background: rgba(167, 139, 250, 0.14); border-color: rgba(167, 139, 250, 0.24); color: #b9a6fb; }
.sc-ic--cyan { background: rgba(34, 211, 238, 0.13); border-color: rgba(34, 211, 238, 0.24); color: #4fd8ee; }
.sc-ic--amber { background: rgba(245, 158, 11, 0.13); border-color: rgba(245, 158, 11, 0.24); color: #f0ad3d; }
.sc-ic--emerald { background: rgba(52, 211, 153, 0.13); border-color: rgba(52, 211, 153, 0.24); color: #4bd8a5; }
.sc-ic--rose { background: rgba(251, 113, 133, 0.13); border-color: rgba(251, 113, 133, 0.24); color: #fb8b9c; }
.sc-ic--sky { background: rgba(56, 189, 248, 0.13); border-color: rgba(56, 189, 248, 0.24); color: #5cc7f9; }

/* ── 字段栅格 ──────────────────────────────────────────────── */
/* 一律 auto-fill 而非 auto-fit：区块本身铺满屏幕，但字段数少于列数时
   多余的列要留空，不能让 3 个输入框各自被拉到屏幕的三分之一宽。 */
.sc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 16px 18px;
}
.sc-grid--tight {
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
}
.sc-grid--narrow {
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
}
.sc-field {
  min-width: 0;
}
.sc-field--wide {
  grid-column: span 2;
}
.sc-field--stack {
  margin-top: 16px;
}
.sc-label {
  margin-bottom: 6px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--sc-text-dim);
}
.sc-inline {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sc-inline .sc-num {
  flex: 1;
  min-width: 0;
}
.sc-unit {
  flex: none;
  font-size: 12px;
  color: var(--sc-text-mute);
}
.sc-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}
.sc-note {
  font-size: 12px;
  color: var(--sc-text-mute);
}
/* 回国模式的两个计数 */
.sc-hc-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 14px;
  font-size: 13px;
  color: var(--sc-text-mute);
}
.sc-result {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 11px;
  border: 1px solid rgba(245, 108, 108, 0.35);
  border-radius: 999px;
  background: rgba(245, 108, 108, 0.08);
  font-size: 12px;
  color: #f56c6c;
}
.sc-result.is-ok {
  border-color: rgba(52, 211, 153, 0.35);
  background: rgba(52, 211, 153, 0.08);
  color: #67c23a;
}

/* ── 分栏开关（连接/切换 · 备份） ──────────────────────────── */
.sc-seg {
  display: inline-flex;
  padding: 3px;
  border: 1px solid var(--sc-line);
  border-radius: 10px;
  background: #0f1728;
}
.sc-seg button {
  padding: 5px 14px;
  border: none;
  border-radius: 7px;
  background: none;
  color: var(--sc-text-dim);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
@media (hover: hover) {
  .sc-seg button:hover {
    color: var(--sc-text);
  }
}
.sc-seg button.is-on {
  background: #26314a;
  color: #fff;
}

/* ── 后端选择卡 ───────────────────────────────────────────── */
.sc-choices {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.sc-choice {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 13px 15px;
  border: 1px solid var(--sc-line);
  border-radius: 12px;
  background: #131c2f;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
/* 这是数据库后端选择卡，选错要整库迁移 + 重启后端。触摸屏上粘住的 hover 描边
   会紧挨着 is-on 的高亮描边，最不该在这里让人分不清哪张才是当前生效的。 */
@media (hover: hover) {
  .sc-choice:hover {
    border-color: #3a4c6e;
  }
}
.sc-choice.is-on {
  border-color: var(--sc-accent);
  background: linear-gradient(180deg, rgba(91, 140, 255, 0.12), rgba(91, 140, 255, 0.03));
}
.sc-choice-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--sc-text);
}
.sc-choice-sub {
  font-size: 12px;
  color: var(--sc-text-mute);
}
.sc-choice-flag {
  position: absolute;
  top: 10px;
  right: 12px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.16);
  color: #4bd8a5;
  font-size: 11px;
}

/* ── 打印机设备卡 ─────────────────────────────────────────── */
.sc-device {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 14px 16px;
  border: 1px solid var(--sc-line);
  border-radius: 12px;
  background: #131c2f;
}
.sc-device.is-on {
  border-color: rgba(52, 211, 153, 0.4);
}
.sc-device-ic {
  width: 40px;
  height: 40px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 11px;
  background: #1b2942;
  color: var(--sc-text-dim);
}
.sc-device.is-on .sc-device-ic {
  background: rgba(52, 211, 153, 0.14);
  color: #4bd8a5;
}
.sc-device-text {
  min-width: 0;
}
.sc-device-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--sc-text);
}
.sc-device-sub {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.5;
}
.sc-device-sub.is-ok {
  color: var(--sc-text-mute);
}
.sc-device-sub.is-warn {
  color: var(--el-color-warning);
}

/* ── Element Plus 局部改写 ────────────────────────────────── */
/* 全局把 .el-input/.el-select 钉死在 180px，这里让它们填满各自的栅格单元 */
.sc :deep(.el-input),
.sc :deep(.el-select),
.sc :deep(.el-cascader),
.sc :deep(.el-input-number) {
  width: 100% !important;
}
.sc :deep(.el-input-number .el-input__inner) {
  text-align: left;
}
.sc-form :deep(.el-form-item) {
  margin-bottom: 0;
}
.sc-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 12px;
  line-height: 1.4;
  color: var(--sc-text-dim);
}
.sc-table {
  --el-table-border-color: var(--sc-line-soft);
  background: transparent;
}
.sc-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}
.sc-table :deep(th.el-table__cell) {
  background: #18233a !important;
  font-weight: 600;
}
.sc-table :deep(tr) {
  background: transparent;
}

/* ── 窄屏：导航变成顶部横向 chip 条 ───────────────────────── */
@media (max-width: 900px) {
  .sc-body {
    grid-template-columns: minmax(0, 1fr);
  }
  .sc-nav {
    z-index: 5;
    top: 0;
    flex-direction: row;
    gap: 6px;
    overflow-x: auto;
    border-radius: 12px;
  }
  .sc-nav-item {
    width: auto;
    flex: none;
  }
  .sc-nav-item.is-active {
    box-shadow: inset 0 -2px 0 var(--sc-accent);
  }
  .sc-field--wide {
    grid-column: auto;
  }
}

/* ── 手机端（iOS / Android）──────────────────────────────────
   900px 那档已经把左侧锚点导航改成了顶部 chip 条，这里补的是触摸细节
   和把内边距让出来——三层 padding（页面 12 + 面板 18 + 字段）在 375px
   屏上要吃掉整整 60px。 */
@media (max-width: 768px) {
  /* chip 条要能顺畅横滑，且不显示那条几乎看不见的滚动条 */
  .sc-nav {
    padding: 6px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    overscroll-behavior-x: contain;
  }
  .sc-nav::-webkit-scrollbar {
    display: none;
  }
  .sc-nav-item {
    white-space: nowrap;
    padding: 8px 12px;
  }
  .sc-body {
    gap: 12px;
  }
  .sc-sections {
    gap: 12px;
  }
  .sc-panel-head {
    padding: 12px;
    gap: 8px;
  }
  .sc-panel-body {
    padding: 12px;
  }
  .sc-head-text {
    min-width: 0;
  }
  .sc-grid {
    gap: 12px;
  }
  /* 后端选择卡改单列：并排时每张只有 130 出头，副标题会折成三行 */
  .sc-choices {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    margin-bottom: 12px;
  }
}
</style>

<!-- el-dialog 默认挂到 body，scoped 选择器够不到，单独用带前缀的全局块 -->
<style>
.sc-dialog .el-input,
.sc-dialog .el-select {
  width: 100% !important;
}
.sc-dialog .el-form-item__label {
  padding-bottom: 4px;
  font-size: 12px;
  color: #9ba8bf;
}
</style>
