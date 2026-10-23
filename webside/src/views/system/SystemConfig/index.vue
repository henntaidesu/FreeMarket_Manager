<template>
  <div ref="pageRef" class="sc">
    <div class="sc-body">
      <!-- 三级导航：按分类分组，始终展开不收起；点分类 / 模块只显示该分类下的模块。
           宽屏是左侧粘性菜单，窄屏换成顶部两行（分类 + 当前分类的模块），同样常驻。 -->
      <nav class="sc-nav">
        <div v-for="g in navGroups" :key="g.id" class="sc-nav-group">
          <button
            type="button"
            class="sc-nav-cat"
            :class="{ 'is-current': activeCategory === g.id }"
            @click="goCategory(g.id)"
          >
            <el-icon :size="14"><component :is="g.icon" /></el-icon>
            <span class="sc-nav-text">{{ t(g.labelKey) }}</span>
          </button>
          <button
            v-for="s in g.sections"
            :key="s.id"
            type="button"
            class="sc-nav-item"
            :class="{ 'is-active': activeCategory === g.id && activeSection === s.id }"
            @click="goSection(s.id)"
          >
            <el-icon :size="15"><component :is="s.icon" /></el-icon>
            <span class="sc-nav-text">{{ t(s.labelKey) }}</span>
          </button>
        </div>
      </nav>
      <nav class="sc-nav-m">
        <div class="sc-nav-m-row">
          <button
            v-for="g in navGroups"
            :key="g.id"
            type="button"
            class="sc-nav-m-cat"
            :class="{ 'is-active': activeCategory === g.id }"
            @click="goCategory(g.id)"
          >
            {{ t(g.labelKey) }}
          </button>
        </div>
        <div class="sc-nav-m-row">
          <button
            v-for="s in currentGroupSections"
            :key="s.id"
            type="button"
            class="sc-nav-m-item"
            :class="{ 'is-active': activeSection === s.id }"
            @click="goSection(s.id)"
          >
            {{ t(s.labelKey) }}
          </button>
        </div>
      </nav>

      <div class="sc-sections">
        <!-- 界面语言（原在侧边栏底部，改到这里统一管理；仍存 localStorage，跟随浏览器） -->
        <section v-show="sectionShown('language')" id="sc-language" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Compass /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.languageSection') }}</div>
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

        <!-- 账号管理（仅管理员：后端 /users 是管理员接口） -->
        <section v-if="auth.isAdmin" v-show="sectionShown('account')" id="sc-account" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><User /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.accountManagement') }}</div>
            </div>
            <el-button type="primary" size="small" @click="openUserDialog()">
              <el-icon><Plus /></el-icon>
              <span class="sc-btn-text">{{ t('system.addUser') }}</span>
            </el-button>
          </div>
          <div class="sc-panel-body sc-panel-body--flush">
            <el-table :data="users" v-loading="usersLoading" class="sc-table">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="username" :label="t('system.username')" min-width="120" />
              <el-table-column prop="display_name" :label="t('system.displayName')" min-width="140" />
              <!-- 管理员不受角色约束；未分配角色 = 不限制页面（见 backend/src/page_access.py） -->
              <el-table-column :label="t('system.role')" min-width="130">
                <template #default="{ row }">
                  <el-tag v-if="row.is_admin" type="warning" size="small" effect="dark" round>
                    {{ t('roles.admin') }}
                  </el-tag>
                  <span v-else-if="row.role_id">{{ row.role_name || ('#' + row.role_id) }}</span>
                  <span v-else class="sc-muted">{{ t('roles.unassigned') }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('common.status')" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="dark" round>
                    {{ row.is_active ? t('common.enabled') : t('common.disabled') }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_active_at" :label="t('system.lastActiveAt')" min-width="160" />
              <el-table-column prop="created_at" :label="t('common.createdAt')" min-width="160" />
              <el-table-column :label="t('common.operate')" width="90" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openUserDialog(row)">
                    {{ t('common.edit') }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <!-- 系统角色：一个角色 = 一组允许访问的页面（仅管理员）。
             改动即时生效：后端每请求现读角色，前端每 30 秒重拉一次当前用户 -->
        <section v-if="auth.isAdmin" v-show="sectionShown('roles')" id="sc-roles" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Key /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('roles.section') }}</div>
            </div>
            <el-button type="primary" size="small" @click="openRoleDialog()">
              <el-icon><Plus /></el-icon>
              <span class="sc-btn-text">{{ t('roles.add') }}</span>
            </el-button>
          </div>
          <div class="sc-panel-body sc-panel-body--flush">
            <el-table :data="roles" v-loading="rolesLoading" class="sc-table">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="name" :label="t('roles.name')" min-width="120" />
              <el-table-column :label="t('roles.description')" min-width="160" show-overflow-tooltip>
                <template #default="{ row }">{{ row.description || '-' }}</template>
              </el-table-column>
              <el-table-column :label="t('roles.pages')" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  <span v-if="!row.pages.length" class="sc-muted">{{ t('roles.noPages') }}</span>
                  <span v-else>{{ row.pages.map(pageLabel).join(' / ') }}</span>
                </template>
              </el-table-column>
              <!-- 还有用户在用的删不掉（后端 400），把人数摆出来免得点了才知道 -->
              <el-table-column :label="t('roles.userCount')" width="90" align="right">
                <template #default="{ row }">{{ row.user_count ?? 0 }}</template>
              </el-table-column>
              <el-table-column :label="t('common.operate')" width="140" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openRoleDialog(row)">
                    {{ t('common.edit') }}
                  </el-button>
                  <el-button link type="danger" size="small" @click="removeRole(row)">
                    {{ t('common.delete') }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <!-- 代购用户：「购入商品」归属人下拉的取值来源。
             与上面的账号管理**不是同一张表**——那里是能登录这套系统的人，这里是
             「替谁买的」里的那个谁，多半根本不用这套系统，不该为了出现在下拉里就开账号。 -->
        <section v-show="sectionShown('proxy-users')" id="sc-proxy-users" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><UserFilled /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('proxyUsers.section') }}</div>
            </div>
            <el-button type="primary" size="small" @click="openProxyUserDialog()">
              <el-icon><Plus /></el-icon>
              <span class="sc-btn-text">{{ t('proxyUsers.add') }}</span>
            </el-button>
          </div>
          <div class="sc-panel-body sc-panel-body--flush">
            <el-table :data="proxyUsers" v-loading="proxyUsersLoading" class="sc-table">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="name" :label="t('proxyUsers.name')" min-width="140" />
              <el-table-column :label="t('proxyUsers.note')" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.note || '-' }}</template>
              </el-table-column>
              <!-- 名下还有购入记录的删不掉（后端 400），把笔数摆出来免得点了才知道 -->
              <el-table-column :label="t('proxyUsers.purchaseCount')" width="110" align="right">
                <template #default="{ row }">{{ row.purchase_count ?? 0 }}</template>
              </el-table-column>
              <el-table-column :label="t('common.operate')" width="140" align="center">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openProxyUserDialog(row)">
                    {{ t('common.edit') }}
                  </el-button>
                  <el-button link type="danger" size="small" @click="removeProxyUser(row)">
                    {{ t('common.delete') }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <!-- 修改我的密码 -->
        <section v-show="sectionShown('password')" id="sc-password" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Lock /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.changeMyPassword') }}</div>
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
            </div>
          </div>
        </section>

        <!-- DeepSeek AI 配置 -->
        <section v-show="sectionShown('ai')" id="sc-ai" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><MagicStick /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.deepseekSection') }}</div>
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
        <section v-show="sectionShown('listing')" id="sc-listing" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Sell /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('system.listingDefaults') }}</div>
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
              <div class="sc-field sc-field--wide">
                <div class="sc-label">{{ t('system.defaultDescription') }}</div>
                <el-input
                  v-model="listingDefForm.description"
                  type="textarea"
                  :rows="6"
                  :maxlength="900"
                  show-word-limit
                  :placeholder="t('system.defaultDescriptionPlaceholder')"
                  @change="saveListingDefaults"
                />
              </div>
            </div>
          </div>
        </section>

        <!-- 确认后隐藏商品：煤炉订单完成满 24 小时后设为「プロフィールから非表示」；
             开关只管开启之后到期的订单，历史订单用按钮补上 -->
        <section v-show="sectionShown('profile-hide')" id="sc-profile-hide" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Hide /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('profileHide.section') }}</div>
            </div>
            <el-switch
              v-model="profileHide.enabled"
              :loading="profileHideSubmitting"
              :disabled="profileHideLoading || profileHideSubmitting"
              @change="onProfileHideChange"
            />
          </div>
          <div class="sc-panel-body" v-loading="profileHideLoading">
            <el-alert
              v-if="profileHide.history_pending"
              :title="t('profileHide.historyRunning')"
              type="info"
              :closable="false"
              show-icon
            />
            <div class="sc-hc-stats">
              <span>{{ t('profileHide.autoPending', { n: profileHide.auto_pending_count }) }}</span>
              <span>{{ t('profileHide.historyCount', { n: profileHide.history_count }) }}</span>
              <span>{{ t('profileHide.hidden', { n: profileHide.hidden_count }) }}</span>
              <span>{{ t('profileHide.failed', { n: profileHide.failed_count }) }}</span>
            </div>
            <div class="sc-actions">
              <el-button
                :loading="profileHideSubmitting"
                :disabled="profileHide.history_pending || !profileHide.history_count"
                @click="onProfileHideHistory"
              >{{ t('profileHide.processHistory') }}</el-button>
              <el-button
                :type="profileHide.failed_count ? 'warning' : 'default'"
                :loading="profileHideSubmitting"
                :disabled="!profileHide.failed_count"
                @click="submitProfileHide(() => configApi.retryProfileHideFailed())"
              >{{ t('profileHide.retryFailed') }}</el-button>
            </div>
          </div>
        </section>

        <!-- 条码识别（历史数据）：打开即排一条任务——识别历史商品图片里的条码，
             再把同条码 + 同归属人的商品并入管理番号最大的那个 -->
        <section v-show="sectionShown('barcode-history')" id="sc-barcode-history" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Search /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('barcodeHistory.section') }}</div>
            </div>
            <el-switch
              v-model="barcodeHistory.enabled"
              :loading="barcodeHistorySubmitting"
              :disabled="barcodeHistoryLoading || barcodeHistorySubmitting"
              @change="onBarcodeHistoryChange"
            />
          </div>
          <div class="sc-panel-body" v-loading="barcodeHistoryLoading">
            <div class="sc-hc-stats">
              <span>{{ t('barcodeHistory.pending', { n: barcodeHistory.pending_count }) }}</span>
              <span>{{ t('barcodeHistory.found', { n: barcodeHistory.found_count }) }}</span>
              <span>{{ t('barcodeHistory.none', { n: barcodeHistory.none_count }) }}</span>
              <span>{{ t('barcodeHistory.conflict', { n: barcodeHistory.conflict_count }) }}</span>
              <span>{{ t('barcodeHistory.merged', { n: barcodeHistory.merged_count }) }}</span>
              <span v-if="barcodeHistory.borrowed_count">{{ t('barcodeHistory.borrowed', { n: barcodeHistory.borrowed_count }) }}</span>
              <span>{{ t('barcodeHistory.mergeGroupCount', { n: barcodeHistory.merge_group_count }) }}</span>
            </div>
            <div class="sc-actions">
              <el-button
                :loading="barcodeHistorySubmitting"
                :disabled="!barcodeHistory.enabled"
                @click="submitBarcodeHistory(true)"
              >{{ t('barcodeHistory.rerun') }}</el-button>
              <!-- 多张图识别出不同条码的商品：在弹窗里按管理番号逐个看图定夺 -->
              <el-button
                :type="barcodeHistory.conflict_count ? 'warning' : 'default'"
                :disabled="!barcodeHistory.conflict_count"
                @click="barcodeConflictVisible = true"
              >{{ t('barcodeHistory.handleConflicts', { n: barcodeHistory.conflict_count }) }}</el-button>
              <el-button
                :type="barcodeHistory.merge_group_count ? 'warning' : 'default'"
                :disabled="!barcodeHistory.merge_group_count"
                @click="barcodeMergeVisible = true"
              >{{ t('barcodeHistory.mergeGroups', { n: barcodeHistory.merge_group_count }) }}</el-button>
              <!-- 图片里没识别到条码的商品：列表里点管理番号直接打开库存表单 -->
              <el-button
                :disabled="!barcodeHistory.none_count"
                @click="barcodeSkippedVisible = true"
              >{{ t('barcodeHistory.viewSkipped', { n: barcodeHistory.none_count }) }}</el-button>
            </div>
            <BarcodeConflictDialog v-model="barcodeConflictVisible" @resolved="applyBarcodeHistory" />
            <BarcodeSkippedDialog v-model="barcodeSkippedVisible" />
            <BarcodeMergeDialog v-model="barcodeMergeVisible" @changed="onBarcodeMergeChanged" />
          </div>
        </section>

        <!-- 一键修改发货时效：把范围内在售商品的「発送までの日数」整批改成同一个值 -->
        <section v-show="sectionShown('shipping-duration')" id="sc-shipping-duration" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Timer /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('shippingDurationBatch.section') }}</div>
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
            </div>
          </div>
        </section>

        <!-- 数据库管理（连接 / 切换） -->
        <section v-show="sectionShown('database')" id="sc-database" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Coin /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.databaseSection') }}</div>
            </div>
          </div>

          <div class="sc-panel-body">
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

          <!-- 迁移结果紧跟在数据库区块里，不再落到页面最底部 -->
          <div v-if="migrateSummary.length" class="sc-panel-body sc-panel-body--sub">
            <div class="sc-sub-title">迁移结果（逐表行数校验）</div>
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

        <!-- 同步库（= 数据库备份）：把当前库整库覆盖到另一个 MySQL；可定时自动，也可立即同步一次 -->
        <section v-if="auth.isAdmin" v-show="sectionShown('db-sync')" id="sc-db-sync" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><CopyDocument /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.dbSyncSection') }}</div>
            </div>
          </div>

          <div class="sc-panel-body">
            <div class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">主机</div>
                <el-input v-model="syncForm.target.host" />
              </div>
              <div class="sc-field">
                <div class="sc-label">端口</div>
                <el-input-number v-model="syncForm.target.port" :min="1" :max="65535" :controls="false" class="sc-num" />
              </div>
              <div class="sc-field">
                <div class="sc-label">用户</div>
                <el-input v-model="syncForm.target.user" />
              </div>
              <div class="sc-field">
                <div class="sc-label">密码</div>
                <el-input v-model="syncForm.target.password" type="password" show-password :placeholder="syncStatus.target?.password_set ? '••••••••（留空沿用）' : ''" />
              </div>
              <div class="sc-field">
                <div class="sc-label">同步库</div>
                <el-input v-model="syncForm.target.database" />
              </div>
              <div class="sc-field">
                <div class="sc-label">自动同步</div>
                <el-switch v-model="syncForm.enabled" />
              </div>
              <div class="sc-field">
                <div class="sc-label">同步间隔</div>
                <el-select v-model="syncForm.interval_min" :disabled="!syncForm.enabled">
                  <el-option v-for="m in syncIntervals" :key="m" :label="formatInterval(m)" :value="m" />
                </el-select>
              </div>
            </div>
            <div class="sc-actions">
              <el-button :loading="testingSync" @click="onTestSync">测试连接</el-button>
              <el-button :loading="savingSync" @click="onSaveSync">保存设置</el-button>
              <el-button
                type="primary"
                :loading="syncStatus.running || syncingNow"
                :disabled="!(syncForm.target.database || '').trim()"
                @click="onSyncNow"
              >立即同步</el-button>
              <span v-if="syncTestResult" class="sc-result" :class="{ 'is-ok': syncTestResult.ok }">
                <span class="sc-dot" :class="syncTestResult.ok ? 'is-ok' : 'is-bad'" />
                {{ syncTestResult.message }}
                <template v-if="syncTestResult.ok">
                  · 版本 {{ syncTestResult.version }}
                  · 同步库{{ syncTestResult.database_exists ? '已存在' : '不存在（将自动创建）' }}
                </template>
              </span>
            </div>
            <div v-if="syncStatus.running || syncStatus.last_at" class="sc-note sc-note--gap">
              <template v-if="syncStatus.running">正在同步…</template>
              <template v-else>
                上次同步 {{ formatTs(syncStatus.last_at) }}
                {{ syncStatus.last_ok ? '成功' : '失败' }}：{{ syncStatus.last_message }}
                <template v-if="syncStatus.enabled && syncStatus.next_at"> · 下次约 {{ formatTs(syncStatus.next_at) }}</template>
              </template>
            </div>
          </div>

          <div v-if="syncSummary.length" class="sc-panel-body sc-panel-body--sub">
            <div class="sc-sub-title">同步结果（逐表行数校验）</div>
            <el-table :data="syncSummary" size="small" max-height="360" class="sc-table">
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
        <section v-show="sectionShown('image-hosting')" id="sc-image-hosting" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Picture /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.imageHostingSection') }}</div>
            </div>
          </div>

          <div class="sc-panel-body">
            <div class="sc-field">
              <div class="sc-label">开启图床存储</div>
              <el-switch
                v-model="ihEnabled"
                :loading="ihSwitching"
                :disabled="!ih.configured"
                :before-change="onToggleImageHosting"
              />
            </div>

            <div class="sc-grid sc-grid--tight">
              <div class="sc-field">
                <div class="sc-label">图床地址</div>
                <el-input v-model="ihForm.base_url" />
              </div>
              <div class="sc-field">
                <div class="sc-label">对外地址</div>
                <el-input v-model="ihForm.public_base" />
              </div>
              <div class="sc-field">
                <div class="sc-label">项目 slug</div>
                <el-input v-model="ihForm.project" />
              </div>
              <div class="sc-field">
                <div class="sc-label">API Token</div>
                <el-input v-model="ihForm.token" type="password" show-password />
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
              </div>
              <div class="sc-field">
                <div class="sc-label">校验 HTTPS 证书</div>
                <el-switch v-model="ihForm.verify_tls" />
              </div>
            </div>

            <div class="sc-actions">
              <el-button :loading="ihSaving" @click="onSaveImageHosting">保存连接信息</el-button>
              <el-button :loading="ihTesting" :disabled="!ih.configured" @click="onTestImageHosting">测试连接</el-button>
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
              <div class="sc-sub-title">失败明细</div>
              <el-table :data="ihJob.errors" size="small" max-height="240" class="sc-table">
                <el-table-column prop="path" label="图片" min-width="240" show-overflow-tooltip />
                <el-table-column prop="error" label="原因" min-width="280" show-overflow-tooltip />
              </el-table>
            </div>
          </div>
        </section>

        <!-- 二维码打印参数：存 localStorage（跟随浏览器，蓝牙配对本身也是按浏览器授权的） -->
        <section v-show="sectionShown('qrparams')" id="sc-qrparams" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Tickets /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('qrPrint.paramsSection') }}</div>
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
              <!-- 纸张类型决定标签怎么对位：间隙纸由打印机的间隙传感器定位下一张（德佟 SDK LPA_GapType） -->
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.gapType') }}</div>
                <el-select v-model="printerCfg.gapType" @change="savePrinterCfg">
                  <el-option :label="t('qrPrint.gapGap')" :value="2" />
                  <el-option :label="t('qrPrint.gapNone')" :value="0" />
                  <el-option :label="t('qrPrint.gapBlack')" :value="3" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.darkness') }}</div>
                <el-select v-model="printerCfg.darkness" @change="savePrinterCfg">
                  <el-option :label="t('qrPrint.darknessUnset')" :value="255" />
                  <el-option v-for="n in 15" :key="n" :label="String(n)" :value="n" />
                </el-select>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('qrPrint.threshold') }}</div>
                <el-input-number v-model="printerCfg.threshold" :min="10" :max="245" :controls="false" class="sc-num" @change="savePrinterCfg" />
              </div>
            </div>
          </div>
        </section>

        <!-- 打印机连接：连接 / 测试打印 / 忘记设备 -->
        <section v-show="sectionShown('printer')" id="sc-printer" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Printer /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('qrPrint.connSection') }}</div>
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

            <div class="sc-actions">
              <el-button type="primary" :loading="connecting" @click="onConnect">{{ t('qrPrint.connect') }}</el-button>
              <el-button :loading="qrTesting" @click="onQrTest">{{ t('qrPrint.testPrint') }}</el-button>
              <el-button type="danger" plain @click="onForget">{{ t('qrPrint.forget') }}</el-button>
            </div>
          </div>
        </section>

        <!-- 网页访问方式：nginx 反代 HTTP / 直连端口自签 HTTPS（摄像头需要安全上下文） -->
        <section v-show="sectionShown('web-access')" id="sc-web-access" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Connection /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('webAccess.section') }}</div>
            </div>
          </div>
          <div class="sc-panel-body" v-loading="webAccessLoading">
            <el-alert
              v-if="!pageSecure"
              type="error"
              show-icon
              :closable="false"
              :title="t('webAccess.insecureNotice')"
              style="margin-bottom: 12px"
            />
            <div class="sc-field sc-field--stack">
              <div class="sc-label">{{ t('webAccess.mode') }}</div>
              <el-radio-group v-model="webAccess.mode">
                <el-radio value="direct">{{ t('webAccess.modeDirect') }}</el-radio>
                <el-radio value="nginx">{{ t('webAccess.modeNginx') }}</el-radio>
              </el-radio-group>
            </div>
            <div v-if="webAccess.mode === 'direct'" class="sc-field sc-field--stack">
              <div class="sc-label">{{ t('webAccess.hosts') }}</div>
              <el-input v-model="webAccess.hosts" clearable :placeholder="t('webAccess.hostsPlaceholder')" />
            </div>
            <div class="sc-field">
              <div class="sc-label">{{ t('webAccess.running') }}</div>
              <span>{{ webAccess.running_https ? 'HTTPS' : 'HTTP' }}</span>
            </div>
            <el-alert
              v-if="webAccess.pending_restart"
              type="warning"
              show-icon
              :closable="false"
              :title="t('webAccess.pendingRestart')"
              style="margin-top: 12px"
            />
            <template v-if="webAccess.cert_exists">
              <div class="sc-field">
                <div class="sc-label">{{ t('webAccess.certHosts') }}</div>
                <span class="sc-wa-mono">{{ webAccess.cert_hosts.join(', ') }}</span>
              </div>
              <div class="sc-field">
                <div class="sc-label">{{ t('webAccess.certExpires') }}</div>
                <span>{{ webAccess.cert_not_after ? new Date(webAccess.cert_not_after * 1000).toLocaleDateString() : '-' }}</span>
              </div>
            </template>
            <div class="sc-actions">
              <el-button type="primary" :loading="webAccessSaving" @click="saveWebAccess(false)">
                {{ t('systemConfig.save') }}
              </el-button>
              <el-button
                v-if="webAccessRestartAvailable"
                type="warning"
                :loading="webAccessSaving"
                @click="saveWebAccess(true)"
              >
                {{ t('webAccess.saveAndRestart') }}
              </el-button>
              <el-button v-if="webAccess.cert_exists" tag="a" :href="configApi.webCertUrl" target="_blank">
                {{ t('webAccess.downloadCert') }}
              </el-button>
              <el-button v-if="webAccess.mode === 'direct'" :loading="webCertRegenerating" @click="regenerateWebCert">
                {{ t('webAccess.regenerate') }}
              </el-button>
            </div>
          </div>
        </section>

        <!-- Cookie 注入域名：代理经 nginx 以独立域名发布时的对外基址 -->
        <section v-show="sectionShown('proxy')" id="sc-proxy" class="sc-panel">
          <div class="sc-panel-head">
            <span class="sc-ic"><el-icon :size="16"><Link /></el-icon></span>
            <div class="sc-head-text">
              <div class="sc-panel-title">{{ t('systemConfig.proxySection') }}</div>
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
            <div class="sc-field">
              <div class="sc-label">{{ t('systemConfig.proxyBasePath') }}</div>
              <el-input
                v-model="proxyBasePath"
                clearable
                :placeholder="t('systemConfig.proxyBasePathPlaceholder')"
              />
            </div>
            <el-alert
              v-if="proxyBasePath.trim()"
              type="warning"
              show-icon
              :closable="false"
              :title="t('systemConfig.proxyBasePathWarning')"
              style="margin-top: 12px"
            />
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

    <el-dialog
      v-model="userDialogVisible"
      :title="userForm.id ? t('system.editUser') : t('system.addUser')"
      width="420px"
      class="sc-dialog"
      destroy-on-close
    >
      <el-form ref="userFormRef" :model="userForm" :rules="userRules" label-position="top">
        <el-form-item :label="t('system.username')" prop="username">
          <el-input v-model="userForm.username" :disabled="!!userForm.id" />
        </el-form-item>
        <el-form-item :label="t('system.displayName')">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item :label="userForm.id ? t('roles.resetPassword') : t('system.password')" prop="password">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            :placeholder="userForm.id ? t('roles.resetPasswordPlaceholder') : ''"
          />
        </el-form-item>
        <el-form-item :label="t('system.role')">
          <el-select
            v-model="userForm.role_id"
            clearable
            :disabled="userForm.is_admin"
            :placeholder="t('roles.unassignedHint')"
            style="width: 100%"
          >
            <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="userForm.is_admin" :disabled="isSelfUser">{{ t('roles.admin') }}</el-checkbox>
          <el-checkbox v-if="userForm.id" v-model="userForm.is_active" :disabled="isSelfUser">
            {{ t('common.enabled') }}
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="userSubmitting" @click="submitUser">
          {{ userForm.id ? t('common.save') : t('common.create') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="roleDialogVisible"
      :title="roleForm.id ? t('roles.edit') : t('roles.add')"
      width="560px"
      class="sc-dialog"
      destroy-on-close
    >
      <el-form ref="roleFormRef" :model="roleForm" :rules="roleRules" label-position="top">
        <el-form-item :label="t('roles.name')" prop="name">
          <el-input v-model="roleForm.name" maxlength="30" show-word-limit />
        </el-form-item>
        <el-form-item :label="t('roles.description')">
          <el-input v-model="roleForm.description" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item :label="t('roles.pages')">
          <!-- 分组与侧边栏一致（同一份 constants/menu.js） -->
          <div class="sc-role-pages">
            <div v-for="g in pageGroups" :key="g.key" class="sc-role-group">
              <el-checkbox
                :model-value="groupState(g) === 'all'"
                :indeterminate="groupState(g) === 'some'"
                class="sc-role-group-title"
                @change="(v) => toggleGroup(g, v)"
              >
                {{ t(g.key) }}
              </el-checkbox>
              <el-checkbox-group v-model="roleForm.pages" class="sc-role-group-items">
                <el-checkbox v-for="p in g.items" :key="p.key" :value="p.key">{{ t(p.titleKey) }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="roleSubmitting" @click="submitRole">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="proxyUserDialogVisible"
      :title="proxyUserForm.id ? t('proxyUsers.edit') : t('proxyUsers.add')"
      width="420px"
      class="sc-dialog"
      destroy-on-close
    >
      <el-form ref="proxyUserFormRef" :model="proxyUserForm" :rules="proxyUserRules" label-position="top">
        <el-form-item :label="t('proxyUsers.name')" prop="name">
          <el-input v-model="proxyUserForm.name" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item :label="t('proxyUsers.note')">
          <el-input
            v-model="proxyUserForm.note"
            type="textarea"
            :rows="2"
            maxlength="200"
            show-word-limit
            resize="none"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="proxyUserDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="proxyUserSubmitting" @click="submitProxyUser">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Plus, User, UserFilled, Key, Lock, MagicStick, Sell, Coin, Tickets, Printer, Compass, Timer, Link, Picture, Connection, Search, Hide, CopyDocument } from '@element-plus/icons-vue'
import { ElMessage } from '@/utils/notify'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { authApi, roleApi, configApi, proxyUserApi, shopAccountApi } from '@/api/index.js'
import { useAuthStore } from '@/stores/auth.js'
import { MENU_ITEMS, pageKeyOf } from '@/constants/menu.js'
import { databaseApi } from '@/api/database'
import { imageHostingApi } from '@/api/image_hosting'
import BarcodeConflictDialog from './BarcodeConflictDialog.vue'
import BarcodeSkippedDialog from './BarcodeSkippedDialog.vue'
import BarcodeMergeDialog from './BarcodeMergeDialog.vue'
import {
  printTestLabel,
  loadPrinterConfig,
  savePrinterConfig,
  fetchPrinterConfig,
  isBluetoothSupported,
  supportsAutoReconnect,
  getPrinterState,
  connectPrinter,
  forgetPrinter,
} from '@/utils/btPrinter/index.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const { t, locale } = useI18n()

// ===== 三级导航：分类 → 模块（图标名走全局注册的 element-plus 图标，与 Layout 侧边栏一致）=====
// 模块在分类内的顺序 = 模板里 <section> 的顺序，两边要一起改
const CATEGORIES = [
  { id: 'basic', icon: 'Setting', labelKey: 'systemConfig.catBasic' },
  { id: 'business', icon: 'Sell', labelKey: 'systemConfig.catBusiness' },
  { id: 'data', icon: 'Coin', labelKey: 'systemConfig.catData' },
  { id: 'device', icon: 'Monitor', labelKey: 'systemConfig.catDevice' },
]
const SECTIONS = [
  { id: 'language', cat: 'basic', icon: 'Compass', labelKey: 'systemConfig.languageSection' },
  { id: 'account', cat: 'basic', icon: 'User', labelKey: 'system.accountManagement', adminOnly: true },
  { id: 'roles', cat: 'basic', icon: 'Key', labelKey: 'roles.section', adminOnly: true },
  { id: 'proxy-users', cat: 'basic', icon: 'UserFilled', labelKey: 'proxyUsers.section' },
  { id: 'password', cat: 'basic', icon: 'Lock', labelKey: 'system.changeMyPassword' },
  { id: 'ai', cat: 'business', icon: 'MagicStick', labelKey: 'systemConfig.deepseekSection' },
  { id: 'listing', cat: 'business', icon: 'Sell', labelKey: 'system.listingDefaults' },
  { id: 'profile-hide', cat: 'business', icon: 'Hide', labelKey: 'profileHide.section' },
  { id: 'barcode-history', cat: 'business', icon: 'Search', labelKey: 'barcodeHistory.section' },
  { id: 'shipping-duration', cat: 'business', icon: 'Timer', labelKey: 'shippingDurationBatch.section' },
  { id: 'database', cat: 'data', icon: 'Coin', labelKey: 'systemConfig.databaseSection' },
  { id: 'db-sync', cat: 'data', icon: 'CopyDocument', labelKey: 'systemConfig.dbSyncSection', adminOnly: true },
  { id: 'image-hosting', cat: 'data', icon: 'Picture', labelKey: 'systemConfig.imageHostingSection' },
  { id: 'qrparams', cat: 'device', icon: 'Tickets', labelKey: 'qrPrint.paramsSection' },
  { id: 'printer', cat: 'device', icon: 'Printer', labelKey: 'qrPrint.connSection' },
  { id: 'web-access', cat: 'device', icon: 'Connection', labelKey: 'webAccess.section' },
  { id: 'proxy', cat: 'device', icon: 'Link', labelKey: 'systemConfig.proxySection' },
]
const SECTION_CAT = Object.fromEntries(SECTIONS.map((s) => [s.id, s.cat]))

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
/** 账号 / 角色两块只给管理员看：对应接口是管理员专用，非管理员进来只会弹 403 */
const visibleSections = computed(() => SECTIONS.filter((s) => !s.adminOnly || auth.isAdmin))
const navGroups = computed(() =>
  CATEGORIES.map((c) => ({ ...c, sections: visibleSections.value.filter((s) => s.cat === c.id) }))
    .filter((g) => g.sections.length)
)

/** 当前分类记在地址栏 ?cat=，刷新 / 分享链接都停在同一分类 */
const activeCategory = ref(
  CATEGORIES.some((c) => c.id === route.query.cat) ? route.query.cat : CATEGORIES[0].id
)
const currentGroupSections = computed(
  () => navGroups.value.find((g) => g.id === activeCategory.value)?.sections || []
)
function sectionShown(id) {
  return SECTION_CAT[id] === activeCategory.value
}

const pageRef = ref(null)
const activeSection = ref(currentGroupSections.value[0]?.id || SECTIONS[0].id)
/** 真正的滚动容器是 Layout 的 .main-content，不是 window */
let scrollRoot = null

function setCategory(cat) {
  if (activeCategory.value === cat) return false
  activeCategory.value = cat
  router.replace({ query: { ...route.query, cat } })
  return true
}

function goCategory(cat) {
  setCategory(cat)
  activeSection.value = currentGroupSections.value[0]?.id || ''
  ;(scrollRoot || window).scrollTo({ top: 0, behavior: 'smooth' })
}

async function goSection(id) {
  // 跨分类时先等目标分类的区块显示出来，否则 scrollIntoView 拿到的是 display:none 的元素
  if (setCategory(SECTION_CAT[id])) await nextTick()
  document.getElementById(`sc-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  activeSection.value = id
}

/** 当前分类内，取最后一个越过「顶部 96px」的区块作为当前区块 */
function syncActiveSection() {
  const rootTop = scrollRoot ? scrollRoot.getBoundingClientRect().top : 0
  const list = currentGroupSections.value
  let current = list[0]?.id || ''
  for (const s of list) {
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
// id 为空即新建，有值即编辑——两者共用同一个弹窗；编辑时密码留空 = 不重置
const userForm = reactive({
  id: null,
  username: '',
  display_name: '',
  password: '',
  role_id: null,
  is_admin: false,
  is_active: true
})
const userRules = computed(() => ({
  username: [{ required: true, message: t('login.usernameRequired'), trigger: 'blur' }],
  password: userForm.id
    ? [{ min: 6, message: t('system.passwordMin6'), trigger: 'blur' }]
    : [{ required: true, message: t('login.passwordRequired'), trigger: 'blur' }, { min: 6, message: t('system.passwordMin6'), trigger: 'blur' }]
}))
/** 编辑自己时不能取消管理员 / 禁用自己（后端同样拦） */
const isSelfUser = computed(() => !!userForm.id && userForm.id === auth.user?.id)

// ===== 系统角色（页面访问权限）=====
const roles = ref([])
const rolesLoading = ref(false)
const roleDialogVisible = ref(false)
const roleSubmitting = ref(false)
const roleFormRef = ref()
const roleForm = reactive({ id: null, name: '', description: '', pages: [] })
const roleRules = {
  name: [{ required: true, message: t('roles.nameRequired'), trigger: 'blur' }]
}

/** 角色编辑里的页面分组：一级页面一组，「其他功能」的二级按侧边栏分组 */
const pageGroups = (() => {
  const groups = [{ key: 'roles.mainPages', items: [] }]
  for (const m of MENU_ITEMS) {
    if (!m.children) {
      groups[0].items.push({ key: pageKeyOf(m.path), titleKey: m.titleKey })
      continue
    }
    for (const c of m.children) {
      let g = groups.find((x) => x.key === c.group)
      if (!g) groups.push((g = { key: c.group, items: [] }))
      g.items.push({ key: pageKeyOf(c.path), titleKey: c.titleKey })
    }
  }
  return groups
})()
const pageTitleKeys = Object.fromEntries(pageGroups.flatMap((g) => g.items.map((p) => [p.key, p.titleKey])))
const pageLabel = (key) => (pageTitleKeys[key] ? t(pageTitleKeys[key]) : key)

function groupState(g) {
  const n = g.items.filter((p) => roleForm.pages.includes(p.key)).length
  return n === 0 ? 'none' : n === g.items.length ? 'all' : 'some'
}

function toggleGroup(g, checked) {
  const keys = g.items.map((p) => p.key)
  const rest = roleForm.pages.filter((k) => !keys.includes(k))
  roleForm.pages = checked ? [...rest, ...keys] : rest
}

async function loadRoles() {
  rolesLoading.value = true
  try {
    roles.value = await roleApi.list()
  } finally {
    rolesLoading.value = false
  }
}

function openRoleDialog(row) {
  roleForm.id = row?.id ?? null
  roleForm.name = row?.name || ''
  roleForm.description = row?.description || ''
  roleForm.pages = [...(row?.pages || [])]
  roleDialogVisible.value = true
}

async function submitRole() {
  await roleFormRef.value.validate()
  roleSubmitting.value = true
  try {
    const payload = { name: roleForm.name, description: roleForm.description, pages: roleForm.pages }
    if (roleForm.id) await roleApi.update(roleForm.id, payload)
    else await roleApi.create(payload)
    ElMessage.success(t('roles.saved'))
    roleDialogVisible.value = false
    await Promise.all([loadRoles(), loadUsers()])
  } finally {
    roleSubmitting.value = false
  }
}

async function removeRole(row) {
  try {
    await ElMessageBox.confirm(
      t('roles.deleteConfirm', { name: row.name }),
      t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  // 还有用户在用时后端会 400 并说明人数，拦截器已弹提示
  await roleApi.remove(row.id)
  ElMessage.success(t('roles.deleted'))
  await loadRoles()
}

// ===== 代购用户（「购入商品」归属人下拉的取值来源）=====
// 与上面的 users **不是同一张表**：这里的人不能登录系统，只是对账时的一个名字。
const proxyUsers = ref([])
const proxyUsersLoading = ref(false)
const proxyUserDialogVisible = ref(false)
const proxyUserSubmitting = ref(false)
const proxyUserFormRef = ref()
// id 为空即新增，有值即编辑——两者共用同一个弹窗
const proxyUserForm = reactive({ id: null, name: '', note: '' })
const proxyUserRules = {
  name: [{ required: true, message: t('proxyUsers.nameRequired'), trigger: 'blur' }]
}

async function loadProxyUsers() {
  proxyUsersLoading.value = true
  try {
    proxyUsers.value = await proxyUserApi.list()
  } finally {
    proxyUsersLoading.value = false
  }
}

function openProxyUserDialog(row) {
  proxyUserForm.id = row?.id ?? null
  proxyUserForm.name = row?.name || ''
  proxyUserForm.note = row?.note || ''
  proxyUserDialogVisible.value = true
}

async function submitProxyUser() {
  await proxyUserFormRef.value.validate()
  proxyUserSubmitting.value = true
  try {
    const payload = { name: proxyUserForm.name, note: proxyUserForm.note }
    if (proxyUserForm.id) await proxyUserApi.update(proxyUserForm.id, payload)
    else await proxyUserApi.create(payload)
    ElMessage.success(t('proxyUsers.saved'))
    proxyUserDialogVisible.value = false
    await loadProxyUsers()
  } finally {
    proxyUserSubmitting.value = false
  }
}

async function removeProxyUser(row) {
  try {
    await ElMessageBox.confirm(
      t('proxyUsers.deleteConfirm', { name: row.name }),
      t('common.confirm'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  // 名下还有购入记录时后端会 400 并说明剩几笔，拦截器已弹提示，这里不再重复
  await proxyUserApi.remove(row.id)
  ElMessage.success(t('proxyUsers.deleted'))
  await loadProxyUsers()
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

function openUserDialog(row) {
  userForm.id = row?.id ?? null
  userForm.username = row?.username || ''
  userForm.display_name = row?.display_name || ''
  userForm.password = ''
  userForm.role_id = row?.role_id ?? null
  userForm.is_admin = Boolean(row?.is_admin)
  userForm.is_active = row ? Boolean(row.is_active) : true
  userDialogVisible.value = true
}

async function submitUser() {
  await userFormRef.value.validate()
  userSubmitting.value = true
  try {
    if (userForm.id) {
      // 角色清空要显式传 clear_role：role_id=null 在后端表示「这次不改角色」
      await authApi.updateUser(userForm.id, {
        display_name: userForm.display_name,
        is_admin: userForm.is_admin,
        is_active: userForm.is_active,
        role_id: userForm.role_id || null,
        clear_role: !userForm.role_id,
        password: userForm.password || null
      })
      ElMessage.success(t('roles.userSaved'))
      // 改的是自己（显示名等）：立即刷新侧栏与权限
      if (userForm.id === auth.user?.id) await auth.refresh()
    } else {
      await authApi.createUser({
        username: userForm.username,
        display_name: userForm.display_name,
        password: userForm.password,
        is_admin: userForm.is_admin,
        role_id: userForm.role_id || null
      })
      ElMessage.success(t('system.userCreatedSuccess'))
    }
    userDialogVisible.value = false
    await Promise.all([loadUsers(), loadRoles()])
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

// ===== 网页访问方式 =====
const webAccessLoading = ref(false)
const webAccessSaving = ref(false)
const webCertRegenerating = ref(false)
const webAccessRestartAvailable = ref(false)
const pageSecure = window.isSecureContext
const webAccess = reactive({
  mode: 'nginx',
  hosts: '',
  running_https: false,
  pending_restart: false,
  cert_exists: false,
  cert_hosts: [],
  cert_not_after: null,
})

function applyWebAccess(res) {
  if (!res) return
  webAccess.mode = res.mode || 'nginx'
  // 没配过域名时预填当前访问的主机名：证书里没有这个名字，浏览器会多报一条名称不匹配
  webAccess.hosts = (res.hosts || []).join(', ') || window.location.hostname
  webAccess.running_https = !!res.running_https
  webAccess.pending_restart = !!res.pending_restart
  webAccess.cert_exists = !!res.cert_exists
  webAccess.cert_hosts = res.cert_hosts || []
  webAccess.cert_not_after = res.cert_not_after || null
  webAccessRestartAvailable.value = !!res.restart_available
}

async function loadWebAccess() {
  webAccessLoading.value = true
  try {
    applyWebAccess(await configApi.getWebAccess())
  } catch {
    ElMessage.error(t('systemConfig.loadFailed'))
  } finally {
    webAccessLoading.value = false
  }
}

async function saveWebAccess(restart) {
  if (restart) {
    try {
      await ElMessageBox.confirm(t('webAccess.restartConfirm'), t('webAccess.section'), { type: 'warning' })
    } catch {
      return
    }
  }
  const wasHttps = webAccess.running_https
  webAccessSaving.value = true
  try {
    const res = await configApi.putWebAccess({ mode: webAccess.mode, hosts: webAccess.hosts, restart })
    applyWebAccess(res)
    if (res?.restarting) {
      ElMessage.success(t('webAccess.restarting'))
      // 协议随模式变：切到直连 → https；从直连切回 nginx → http。其余情况原地刷新
      let proto = window.location.protocol
      if (res.mode === 'direct') proto = 'https:'
      else if (wasHttps && proto === 'https:') proto = 'http:'
      const target = `${proto}//${window.location.host}${window.location.pathname}${window.location.hash}`
      setTimeout(() => { window.location.href = target }, 12000)
    } else {
      ElMessage.success(t('systemConfig.saveSuccess'))
    }
  } catch {
    /* 错误由 axios 拦截器提示 */
  } finally {
    webAccessSaving.value = false
  }
}

async function regenerateWebCert() {
  webCertRegenerating.value = true
  try {
    applyWebAccess(await configApi.regenerateWebCert())
    ElMessage.success(t('webAccess.regenerated'))
  } catch {
    /* 错误由 axios 拦截器提示 */
  } finally {
    webCertRegenerating.value = false
  }
}

// ===== Cookie 注入域名 =====
const proxyLoading = ref(false)
const proxySaving = ref(false)
const proxyPublicBase = ref('')
const proxyBasePath = ref('')

async function loadProxyBase() {
  proxyLoading.value = true
  try {
    const res = await configApi.getProxyPublicBase()
    proxyPublicBase.value = res?.public_base || ''
    proxyBasePath.value = res?.base_path || ''
  } catch {
    ElMessage.error(t('systemConfig.loadFailed'))
  } finally {
    proxyLoading.value = false
  }
}

async function saveProxyBase() {
  proxySaving.value = true
  try {
    const res = await configApi.putProxyPublicBase({
      public_base: proxyPublicBase.value.trim(),
      base_path: proxyBasePath.value.trim(),
    })
    // 回填后端规范化后的值（去掉末尾斜杠、补上前导斜杠等），避免界面与实际存储不一致
    proxyPublicBase.value = res?.public_base || ''
    proxyBasePath.value = res?.base_path || ''
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
  watermark: 1,
  // 默认商品描述：库存表单出品说明为空时预填（失焦保存）
  description: ''
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
    listingDefForm.description = d?.description ?? ''
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
      watermark: listingDefForm.watermark,
      description: listingDefForm.description
    })
    ElMessage.success(t('system.listingDefaultsSaved'))
  } catch {
    /* 拦截器 */
  } finally {
    listingDefSaving.value = false
  }
}

// ===== 确认后隐藏商品 =====
// 后端只写开关 / 标记并立刻试排一条 system.profile_hide 任务；实际点击在任务里分批跑，
// 剩下的由自动获取循环约 10 分钟续排一批。
const profileHide = reactive({
  enabled: false, history_pending: false, auto_pending_count: 0, history_count: 0, hidden_count: 0, failed_count: 0
})
const profileHideLoading = ref(false)
const profileHideSubmitting = ref(false)

function applyProfileHide(res) {
  profileHide.enabled = !!res?.enabled
  profileHide.history_pending = !!res?.history_pending
  for (const k of ['auto_pending_count', 'history_count', 'hidden_count', 'failed_count']) {
    profileHide[k] = Number(res?.[k]) || 0
  }
}

async function loadProfileHide() {
  profileHideLoading.value = true
  try {
    applyProfileHide(await configApi.getProfileHide())
  } catch {
    /* 拦截器已提示 */
  } finally {
    profileHideLoading.value = false
  }
}

/** 统一提交：返回里带 task_id 说明排上了任务，否则只是保存 */
async function submitProfileHide(call, { silent = false } = {}) {
  profileHideSubmitting.value = true
  try {
    const res = await call()
    applyProfileHide(res)
    if (!silent) ElMessage.success(res?.task_id ? t('profileHide.submitted') : t('profileHide.nothingToDo'))
  } catch {
    await loadProfileHide()
  } finally {
    profileHideSubmitting.value = false
  }
}

function onProfileHideChange(val) {
  return submitProfileHide(() => configApi.putProfileHide(!!val), { silent: !val })
}

async function onProfileHideHistory() {
  try {
    await ElMessageBox.confirm(
      t('profileHide.confirmHistoryMsg', { n: profileHide.history_count }),
      t('profileHide.confirmHistoryTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  await submitProfileHide(() => configApi.processProfileHideHistory())
}

// ===== 条码识别（历史数据）=====
// 打开开关即排一条任务（只识别，幂等）：再跑一轮只处理还没识别的。同条码商品走「待合并」人工确认。
const barcodeHistory = reactive({
  enabled: false, pending_count: 0, found_count: 0, none_count: 0, conflict_count: 0, merged_count: 0, borrowed_count: 0,
  merge_group_count: 0
})
const barcodeHistoryLoading = ref(false)
const barcodeHistorySubmitting = ref(false)
const barcodeConflictVisible = ref(false)
const barcodeSkippedVisible = ref(false)
const barcodeMergeVisible = ref(false)

function applyBarcodeHistory(res) {
  barcodeHistory.enabled = !!res?.enabled
  for (const k of ['pending_count', 'found_count', 'none_count', 'conflict_count', 'merged_count', 'borrowed_count', 'merge_group_count']) {
    barcodeHistory[k] = Number(res?.[k]) || 0
  }
}

function onBarcodeMergeChanged(res) {
  if (res) applyBarcodeHistory(res)
  else loadBarcodeHistory()
}

async function loadBarcodeHistory() {
  barcodeHistoryLoading.value = true
  try {
    applyBarcodeHistory(await configApi.getBarcodeHistory())
  } catch {
    // 拦截器已提示
  } finally {
    barcodeHistoryLoading.value = false
  }
}

async function submitBarcodeHistory(enable) {
  barcodeHistorySubmitting.value = true
  try {
    applyBarcodeHistory(await configApi.putBarcodeHistory(enable))
    if (enable) ElMessage.success(t('barcodeHistory.submitted'))
  } catch {
    await loadBarcodeHistory()
  } finally {
    barcodeHistorySubmitting.value = false
  }
}

/** 打开前确认：合并会软删旧商品，不可一键撤销 */
async function onBarcodeHistoryChange(val) {
  const target = !!val
  if (target) {
    try {
      await ElMessageBox.confirm(
        t('barcodeHistory.confirmMsg', { n: barcodeHistory.pending_count }),
        t('barcodeHistory.confirmTitle'),
        { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
      )
    } catch {
      barcodeHistory.enabled = false
      return
    }
  }
  await submitBarcodeHistory(target)
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
const activeBackend = ref('sqlite')
const passwordSet = ref(false)
const testing = ref(false)
const switching = ref(false)
const migrating = ref(false)
const testResult = ref(null)
const migrateSummary = ref([])
const hotSwitching = ref(false)
const activeDatabase = ref('')   // 当前生效的 MySQL 库名，用于判断库名是否被修改

const dbForm = reactive({
  backend: 'sqlite',
  mysql: { host: '127.0.0.1', port: 3306, user: 'root', password: '', database: 'mercari' }
})

// 同步库（= 数据库备份）：手动「立即同步」，或开启后每隔 interval_min 分钟整库覆盖过去一次
const syncIntervals = ref([30, 60, 120, 360, 720, 1440])
const syncForm = reactive({
  enabled: false,
  interval_min: 60,
  target: { host: '', port: 3306, user: '', password: '', database: '' }
})
const syncStatus = ref({})
const testingSync = ref(false)
const savingSync = ref(false)
const syncingNow = ref(false)
const syncTestResult = ref(null)
const syncSummary = ref([])   // 最近一次「立即同步」的逐表行数校验

// ===== 图床存储 =====
// ih   = 服务端当前状态（生效的存储位置 + 图片数量概览）
// ihForm = 连接信息的表单草稿，要点「保存」才生效
// ihEnabled = 「开启图床存储」开关；拨动即调接口，成功后 el-switch 才跟着翻（before-change）
const ih = reactive({
  backend: 'local', token_set: false, configured: false,
  local_files: 0, remote_records: 0, pending_upload: 0, pending_bytes: 0
})
const ihEnabled = ref(false)
const ihForm = reactive({
  base_url: '', public_base: '', project: '', token: '',
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
  ihEnabled.value = cfg.backend === 'remote'
  // Token 永远留空：服务端不回传明文，留空提交即「不修改」
  Object.assign(ihForm, {
    base_url: cfg.base_url, public_base: cfg.public_base,
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

/**
 * 开关的 before-change：此刻 ihEnabled 还是**旧值**，所以目标后端取它的反面。
 * 只有 resolve(true) 时 el-switch 才会真正翻过去——接口失败就停在原位，
 * 不会出现「开关显示已开启、后端其实还在本地」。
 */
async function onToggleImageHosting() {
  const backend = ihEnabled.value ? 'local' : 'remote'
  ihSwitching.value = true
  try {
    await imageHostingApi.setBackend(backend)
    await loadImageHosting()
    ElMessage.success(backend === 'remote' ? '已开启图床存储，新图片直接写入图床' : '已关闭图床存储，新图片写回本地')
    return true
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
    return false
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
    loadImageHosting()   // 作业会把存储位置切到图床，开关要立刻跟上，而不是等搬完才刷新
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
    loadImageHosting()   // 同上：回迁会把存储位置切回本地
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
  // 同步库接口仅管理员可用
  if (auth.isAdmin) applySyncStatus(await databaseApi.getSyncSettings(), cfg.mysql)
}

/** 用服务端状态刷新同步库表单；从未保存过同步库时预填当前 MySQL 服务器（库名留空，避免误覆盖当前库） */
function applySyncStatus(st, mysqlDefaults) {
  syncStatus.value = st
  syncIntervals.value = st.intervals
  syncForm.enabled = st.enabled
  syncForm.interval_min = st.interval_min
  const tg = st.target
  if (tg.host) {
    Object.assign(syncForm.target, { host: tg.host, port: tg.port, user: tg.user, database: tg.database, password: '' })
  } else if (mysqlDefaults) {
    Object.assign(syncForm.target, { host: mysqlDefaults.host, port: mysqlDefaults.port, user: mysqlDefaults.user })
  }
}

function formatInterval(min) {
  return min < 60 ? `${min} 分钟` : `${min / 60} 小时`
}

function formatTs(sec) {
  return new Date(sec * 1000).toLocaleString()
}

async function onTestSync() {
  testingSync.value = true
  syncTestResult.value = null
  try {
    syncTestResult.value = await databaseApi.testSyncTarget({ ...syncForm.target })
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    testingSync.value = false
  }
}

async function onSaveSync() {
  if (syncForm.enabled) {
    const target = `${syncForm.target.host}:${syncForm.target.port}/${(syncForm.target.database || '').trim()}`
    try {
      await ElMessageBox.confirm(
        `开启后每隔 ${formatInterval(syncForm.interval_min)} 会把当前数据库整库覆盖到「${target}」（先清空同名表）。是否继续？`,
        '确认开启同步库',
        { type: 'warning', confirmButtonText: '开启', cancelButtonText: '取消' }
      )
    } catch (_) {
      return
    }
  }
  savingSync.value = true
  try {
    const st = await databaseApi.saveSyncSettings({ ...syncForm, target: { ...syncForm.target } })
    applySyncStatus(st)
    ElMessage.success('同步库设置已保存')
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    savingSync.value = false
  }
}

/** 立即同步 = 手动备份：先保存当前表单（目标 / 开关 / 间隔），再整库覆盖一次 */
async function onSyncNow() {
  const target = `${syncForm.target.host}:${syncForm.target.port}/${syncForm.target.database.trim()}`
  try {
    await ElMessageBox.confirm(
      `将把当前数据库的全部数据同步到「${target}」（先清空同名表再整库覆盖）。当前使用的数据库不变。是否继续？`,
      '确认立即同步',
      { type: 'warning', confirmButtonText: '立即同步', cancelButtonText: '取消' }
    )
  } catch (_) {
    return
  }
  syncingNow.value = true
  syncSummary.value = []
  try {
    applySyncStatus(await databaseApi.saveSyncSettings({ ...syncForm, target: { ...syncForm.target } }))
    const res = await databaseApi.syncNow()
    syncStatus.value = res.status
    syncSummary.value = res.tables || []
    if (res.ok) ElMessage.success(res.message)
    else if (res.skipped) ElMessage.warning(res.message)
    else ElMessage.error(res.message)
  } catch (e) {
    // 错误消息已由 http 拦截器统一提示
  } finally {
    syncingNow.value = false
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
    gapType: Number(printerCfg.gapType ?? 2),
    darkness: Number(printerCfg.darkness) || 255,
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

async function onForget() {
  await forgetPrinter()
  printerState.value = getPrinterState()
  ElMessage.success(t('qrPrint.forgotten'))
}

onMounted(() => {
  if (auth.isAdmin) {
    loadUsers()
    loadRoles()
  }
  loadProxyUsers()
  load()
  loadListingDefaults()
  loadProfileHide()
  loadBarcodeHistory()
  loadSdAccounts()
  loadSdPreview()
  loadDbConfig()
  loadImageHosting()
  pollImageJob()
  loadPrinterParams()
  loadProxyBase()
  loadWebAccess()

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
/* 配色与全站卡片一致（App.vue：卡片 #131c2f / 卡片头 #161f33 / 描边 #2a3446 / 分隔 #28354a，
   主色 Element 默认蓝），这里只保留「锚点导航 + 单列区块」的设置页版式。 */
.sc {
  --sc-line: #2a3446;
  --sc-line-soft: #28354a;
  --sc-text: #e6edf7;
  --sc-text-dim: #9ba8bf;
  --sc-text-mute: #7f8da6;
  --sc-accent: var(--el-color-primary);
  /* 跟随窗口，不设上限：外层 .main-content 已经给了 20px 内边距 */
  width: 100%;
}

/* ── 版式：左三级导航 + 右单列区块 ────────────────────────── */
.sc-body {
  display: grid;
  grid-template-columns: 208px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
/* 三级导航常驻：粘在滚动容器顶部，超出视口高度时自身滚动，永远不会被滚出视野 */
.sc-nav {
  position: sticky;
  top: 0;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 4px 0 8px;
  border: 1px solid var(--sc-line);
  border-radius: 8px;
  background: #131c2f;
}
.sc-nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sc-nav-group + .sc-nav-group {
  margin-top: 4px;
  border-top: 1px solid var(--sc-line-soft);
}
/* 分类标题 = 二级菜单 el-menu-item-group 的标题样式，可点（切到该分类） */
.sc-nav-cat {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 20px 6px;
  border: none;
  background: none;
  color: var(--sc-text-mute);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.sc-nav-cat.is-current {
  color: var(--el-color-primary);
  font-weight: 600;
}
/* 选中 / 悬停与左侧菜单（Layout.vue 的 el-menu-item）同一套 */
.sc-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: calc(100% - 16px);
  margin: 0 8px;
  padding: 9px 12px;
  border: none;
  border-radius: 6px;
  background: none;
  color: #a6adb4;
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
/* 触摸屏 :hover 会粘住：点过的锚点会一直亮着底色，和 is-active 混在一起 */
@media (hover: hover) {
  .sc-nav-item:hover {
    background: #1b2942;
    color: var(--sc-text);
  }
}
.sc-nav-item.is-active {
  background: #1890ff;
  color: #fff;
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
  border-radius: 8px;
  /* 账号表格是贴边铺满的，不裁切的话会把圆角顶成直角 */
  overflow: hidden;
  background: #131c2f;
  color: var(--sc-text);
  /* 点导航滚过来时，标题不要顶到容器边 */
  scroll-margin-top: 12px;
}
/* 区块头 = el-card__header 的样子 */
.sc-panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 14px 20px;
  background: #161f33;
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
.sc-btn-text {
  margin-left: 4px;
}
.sc-panel-body {
  padding: 20px;
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

/* 区块图标：与仪表盘卡片标题一样，主色小图标、不加底块 */
.sc-ic {
  flex: none;
  display: inline-flex;
  align-self: flex-start;
  margin-top: 2px;
  color: var(--el-color-primary);
}

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
/* 系统角色 / 账号编辑（弹窗挂在 body 下，取不到页面根上的 --sc-* 变量，用 element 变量） */
.sc-muted {
  color: var(--el-text-color-secondary);
}
.sc-role-pages {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sc-role-group {
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.sc-role-group-title {
  font-weight: 600;
}
.sc-role-group-items {
  display: flex;
  flex-wrap: wrap;
  column-gap: 4px;
  padding-left: 22px;
}
.sc-wa-mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
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
.sc-note--gap {
  margin-top: 10px;
}
.sc-sub-title--gap {
  margin-top: 24px;
}
/* 业务开关模块的计数行 */
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
  border-radius: 4px;
  background: rgba(245, 108, 108, 0.08);
  font-size: 12px;
  color: #f56c6c;
}
.sc-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: #4c5b78;
}
.sc-dot.is-ok {
  background: var(--el-color-success);
}
.sc-dot.is-bad {
  background: var(--el-color-danger);
}
.sc-result.is-ok {
  border-color: rgba(103, 194, 58, 0.35);
  background: rgba(103, 194, 58, 0.08);
  color: #67c23a;
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
  border-radius: 8px;
  background: #161f33;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
/* 这是数据库后端选择卡，选错要整库迁移 + 重启后端。触摸屏上粘住的 hover 描边
   会紧挨着 is-on 的高亮描边，最不该在这里让人分不清哪张才是当前生效的。 */
@media (hover: hover) {
  .sc-choice:hover {
    border-color: var(--el-color-primary-light-5);
  }
}
.sc-choice.is-on {
  border-color: var(--sc-accent);
  background: rgba(64, 158, 255, 0.08);
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
  background: rgba(103, 194, 58, 0.16);
  color: var(--el-color-success);
  font-size: 11px;
}

/* ── 打印机设备卡 ─────────────────────────────────────────── */
.sc-device {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 14px 16px;
  border: 1px solid var(--sc-line);
  border-radius: 8px;
  background: #161f33;
}
.sc-device.is-on {
  border-color: rgba(103, 194, 58, 0.45);
}
.sc-device-ic {
  width: 40px;
  height: 40px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #1b2942;
  color: var(--sc-text-dim);
}
.sc-device.is-on .sc-device-ic {
  background: rgba(103, 194, 58, 0.14);
  color: var(--el-color-success);
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
.sc-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

/* 窄屏版三级导航：两行横条（分类 / 当前分类的模块），宽屏不显示 */
.sc-nav-m {
  display: none;
}
.sc-nav-m-row {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  overscroll-behavior-x: contain;
}
.sc-nav-m-row::-webkit-scrollbar {
  display: none;
}
.sc-nav-m-row + .sc-nav-m-row {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--sc-line-soft);
}
.sc-nav-m-cat,
.sc-nav-m-item {
  flex: none;
  padding: 7px 12px;
  border: none;
  border-radius: 6px;
  background: none;
  color: #a6adb4;
  font: inherit;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
}
.sc-nav-m-cat.is-active {
  background: #1890ff;
  color: #fff;
}
.sc-nav-m-item {
  font-size: 12px;
}
.sc-nav-m-item.is-active {
  background: #1b2942;
  color: var(--sc-text);
}

/* ── 窄屏：左侧导航换成顶部常驻两行横条 ─────────────────────── */
@media (max-width: 900px) {
  .sc-body {
    grid-template-columns: minmax(0, 1fr);
  }
  .sc-nav {
    display: none;
  }
  .sc-nav-m {
    display: block;
    position: sticky;
    top: 0;
    z-index: 5;
    padding: 6px;
    border: 1px solid var(--sc-line);
    border-radius: 8px;
    background: #131c2f;
  }
  .sc-field--wide {
    grid-column: auto;
  }
}

/* ── 手机端（iOS / Android）──────────────────────────────────
   900px 那档已经把左侧三级导航改成了顶部两行横条，这里补的是触摸细节
   和把内边距让出来——三层 padding（页面 12 + 面板 18 + 字段）在 375px
   屏上要吃掉整整 60px。 */
@media (max-width: 768px) {
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
  .sc-panel-head > .el-radio-group {
    margin-left: auto;
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
