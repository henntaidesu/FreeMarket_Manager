<template>
  <div>
    <el-card shadow="never" class="list-card" v-loading="loading">
      <div class="list-toolbar">
        <el-button
          v-if="$can('shop-accounts:sync')"
          type="warning"
          plain
          :loading="pausingAll"
          :disabled="!list.some(anyTaskEnabled)"
          @click="pauseAllAutoFetch"
        >{{ t('mercariAccounts.pauseAllSync') }}</el-button>
      </div>
      <!-- 各平台独立成块：煤炉与雅虎分开显示，不再混在同一网格里 -->
      <section v-for="section in platformSections" :key="section.value" class="platform-section">
        <div v-if="!section.rows.length" class="platform-section-empty">
          {{ t('mercariAccounts.platformEmpty', { platform: t(section.labelKey) }) }}
        </div>
        <el-row :gutter="16">
          <el-col v-for="row in section.rows" :key="row.id" :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
            <el-card shadow="hover" class="account-card">
              <div class="card-header">
                <div class="card-header-main">
                  <el-avatar
                    v-if="row.avatar"
                    :src="mercariImageUrl(row.avatar)"
                    :size="28"
                    class="card-avatar"
                  />
                  <div class="card-title">{{ row.account_name || '-' }}</div>
                </div>
                <div class="card-header-tags">
                  <el-tag :type="section.tagType" size="small" effect="plain">
                    {{ t(section.labelKey) }}
                  </el-tag>
                  <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
                    {{ row.status === 'active' ? t('mercariAccounts.enabled') : t('mercariAccounts.disabled') }}
                  </el-tag>
                </div>
              </div>
              <div class="card-item"><span>{{ t('mercariAccounts.platformLabel') }}</span>{{ t(section.labelKey) }}</div>
              <div class="card-item"><span>{{ t('mercariAccounts.sellerIdLabel') }}</span>{{ row.seller_id || '-' }}</div>
              <div class="card-item">
                <span>{{ t('mercariAccounts.autoFetchLabel') }}</span>
                <template v-if="anyTaskEnabled(row) && row.status === 'active'">
                  {{ taskIntervalSummary(row) }}
                  <template v-if="pauseWindowLabel(row)"> · {{ t('mercariAccounts.pauseShort') }} {{ pauseWindowLabel(row) }}</template>
                </template>
                <template v-else>{{ t('mercariAccounts.autoFetchOff') }}</template>
              </div>
              <div class="card-item"><span>{{ t('mercariAccounts.remarkLabel') }}</span>{{ row.remark || '-' }}</div>
              <div class="card-actions">
                <el-button
                  v-if="$can('shop-accounts:browser')"
                  size="small"
                  type="primary"
                  plain
                  :loading="browserLoadingKeys.has(browserKeyFor(row.id))"
                  @click="openBrowserForSavedAccount(row)"
                >{{ t('mercariAccounts.openBrowser') }}</el-button>
                <!-- 同步数据走任务队列：提交即返回，同步锁被占用时由队列排队，不再禁用按钮 -->
                <el-tooltip
                  :disabled="row.status === 'active'"
                  :content="t('mercariAccounts.syncDataDisabledHint')"
                  placement="top"
                >
                  <span>
                    <el-button
                      size="small"
                      type="success"
                      :disabled="row.status !== 'active' || !$can('shop-accounts:sync')"
                      @click="openSyncDataDialog(row)"
                    >{{ t('mercariAccounts.syncData') }}</el-button>
                  </span>
                </el-tooltip>
                <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
              </div>
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
            <div v-if="$can('shop-accounts:create')" class="add-card">
              <div class="add-card-main" @click="openCreate(section.value)">
                <el-icon class="add-card-icon"><Plus /></el-icon>
                <span>{{ t('mercariAccounts.addAccountFor', { platform: t(section.labelKey) }) }}</span>
              </div>
            </div>
          </el-col>
        </el-row>
      </section>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="620px"
      top="6vh"
      destroy-on-close
      class="mercari-dialog"
    >
      <p v-if="!form.id && form.platform === 'mercari'" class="form-intro-tip">
        {{ t('mercariAccounts.formIntroTip') }}
      </p>
      <!-- 没有「编辑账号」时已有账号的表单只读（新建走「新建账号」权限） -->
      <el-form
        :model="form"
        :rules="formRules"
        ref="formRef"
        label-width="120px"
        class="mercari-form"
        :disabled="!!form.id && !$can('shop-accounts:edit')"
      >
        <!-- 各模块统一为折叠面板：默认展开基础信息 / 雅虎 App 令牌 / 自动数据获取，退货地址默认收起 -->
        <el-collapse v-model="openSections" class="account-sections">
          <el-collapse-item :title="t('mercariAccounts.sectionBasicInfo')" name="basic">
            <div class="basic-info-row">
              <div class="basic-info-fields">
                <el-form-item :label="t('mercariAccounts.accountNameLabel')" prop="account_name">
                  <el-input v-model="form.account_name" maxlength="60" clearable />
                </el-form-item>
                <el-form-item :label="t('mercariAccounts.sellerId')" prop="seller_id">
                  <el-input
                    v-model="form.seller_id"
                    maxlength="30"
                    clearable
                  />
                </el-form-item>
                <el-form-item :label="t('mercariAccounts.accountStatus')" prop="status">
                  <el-select v-model="form.status" style="width: 100%">
                    <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                </el-form-item>
              </div>
              <div class="basic-info-avatar">
                <el-image
                  v-if="form.avatar"
                  :src="mercariImageUrl(form.avatar)"
                  fit="cover"
                  class="avatar-preview"
                  :preview-src-list="[mercariImageUrl(form.avatar)]"
                  :preview-teleported="true"
                  hide-on-click-modal
                />
                <div v-else class="avatar-placeholder">{{ t('mercariAccounts.avatarPlaceholder') }}</div>
              </div>
            </div>
            <!-- 两个平台都有：煤炉经 MITM 截包取 seller_id，雅虎读「マイページ」DOM -->
            <el-form-item label-width="120px">
              <el-button
                type="primary"
                plain
                :loading="fetchSellerIdLoading"
                @click="fetchBasicInfo"
              >{{ t('mercariAccounts.fetchBasicInfo') }}</el-button>
            </el-form-item>
          </el-collapse-item>
          <!-- 雅虎 App 令牌：ゆうパケットポスト / mini 网页端不下发，只能走 App 的 sparkle 接口。
               令牌从手机 App 抓包得到；填了 refresh_token 之后由后端自动续期，不用再管。
               只写不读——后端不回传明文，输入框始终是空的。 -->
          <el-collapse-item
            v-if="form.id && form.platform === 'yahoo'"
            :title="t('mercariAccounts.sectionYahooAppToken')"
            name="yahoo-token"
          >
            <el-form-item :label="t('mercariAccounts.appTokenStatus')">
              <div class="app-token-status">
                <el-tag :type="appTokenStatus?.configured ? 'success' : 'info'" size="small" effect="light">
                  {{ appTokenStatus?.configured ? t('mercariAccounts.appTokenSet') : t('mercariAccounts.appTokenUnset') }}
                </el-tag>
                <el-tag
                  v-if="appTokenStatus?.configured && !appTokenStatus?.has_refresh_token"
                  type="warning"
                  size="small"
                  effect="light"
                >{{ t('mercariAccounts.appTokenNoRefresh') }}</el-tag>
                <span v-if="appTokenExpiresText" class="app-token-expires">
                  {{ t('mercariAccounts.appTokenExpiresAt', { at: appTokenExpiresText }) }}
                </span>
                <el-button
                  v-if="appTokenStatus?.configured && $can('shop-accounts:app_token')"
                  link
                  type="danger"
                  @click="clearYahooAppToken"
                >{{ t('mercariAccounts.appTokenClear') }}</el-button>
              </div>
            </el-form-item>
            <!-- 取得令牌只有这一条路：雅虎没有账密接口，登录页只能由雅虎自己渲染，
                 所以开一个独立 profile 的浏览器窗口让用户登录一次，之后靠 refresh_token 续期。 -->
            <el-form-item v-if="$can('shop-accounts:app_token')" label-width="120px">
              <el-button
                type="primary"
                :loading="appLoginLoading"
                @click="loginYahooApp"
              >{{ t('mercariAccounts.appLogin') }}</el-button>
            </el-form-item>
          </el-collapse-item>
          <el-collapse-item :title="t('mercariAccounts.sectionAutoFetch')" name="auto-fetch">
            <el-form-item :label="t('mercariAccounts.syncItems')">
              <div class="af-task-list">
                <div class="af-task-row" v-for="def in visibleFetchTasks" :key="def.key">
                  <span class="af-task-name">{{ taskLabel(def) }}</span>
                  <el-select
                    v-model="form.tasks[def.key].sel"
                    class="af-task-select"
                    :placeholder="t('mercariAccounts.intervalPlaceholder')"
                  >
                    <el-option v-for="opt in fetchIntervalOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                  </el-select>
                  <template v-if="form.tasks[def.key].sel === CUSTOM_INTERVAL">
                    <el-input-number
                      v-model="form.tasks[def.key].num"
                      :min="1"
                      :max="1440"
                      :step="1"
                      :controls="false"
                      class="af-task-num"
                    />
                    <el-select v-model="form.tasks[def.key].unit" class="af-task-unit">
                      <el-option v-for="u in intervalUnitOptions" :key="u.value" :label="u.label" :value="u.value" />
                    </el-select>
                  </template>
                </div>
              </div>
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.taskRelist')">
              <el-switch v-model="form.auto_fetch_relist" :active-value="1" :inactive-value="0" />
            </el-form-item>
            <!-- 确认后隐藏商品（仅煤炉）：订单完成满 24 小时后设为「プロフィールから非表示」；
                 开关只管开启之后到期的订单，历史订单用按钮补上。「一键暂停同步」会把它一并关掉 -->
            <el-form-item v-if="form.platform !== 'yahoo'" :label="t('mercariAccounts.profileHide')">
              <div class="ph-block">
                <el-tooltip :content="t('mercariAccounts.profileHideHint')" placement="top">
                  <el-switch v-model="form.profile_hide" :active-value="1" :inactive-value="0" />
                </el-tooltip>
                <template v-if="form.id && profileHide">
                  <el-alert
                    v-if="profileHide.history_pending"
                    :title="t('mercariAccounts.phHistoryRunning')"
                    type="info"
                    :closable="false"
                    show-icon
                  />
                  <div class="ph-stats">
                    <span>{{ t('mercariAccounts.phAutoPending', { n: profileHide.auto_pending_count }) }}</span>
                    <span>{{ t('mercariAccounts.phHistoryCount', { n: profileHide.history_count }) }}</span>
                    <span>{{ t('mercariAccounts.phHidden', { n: profileHide.hidden_count }) }}</span>
                    <span>{{ t('mercariAccounts.phFailed', { n: profileHide.failed_count }) }}</span>
                  </div>
                  <div v-if="$can('shop-accounts:edit')" class="ph-actions">
                    <el-button
                      size="small"
                      :loading="profileHideSubmitting"
                      :disabled="!profileHide.enabled || profileHide.history_pending || !profileHide.history_count"
                      @click="processProfileHideHistory"
                    >{{ t('mercariAccounts.phProcessHistory') }}</el-button>
                    <el-button
                      size="small"
                      :type="profileHide.failed_count ? 'warning' : 'default'"
                      :loading="profileHideSubmitting"
                      :disabled="!profileHide.failed_count"
                      @click="retryProfileHideFailed"
                    >{{ t('mercariAccounts.phRetryFailed') }}</el-button>
                  </div>
                </template>
              </div>
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.pauseRange')" prop="pause_window">
              <div class="af-pause-row">
                <el-time-picker
                  v-model="form.pause_start_time"
                  :placeholder="t('mercariAccounts.pauseStartPlaceholder')"
                  format="HH:mm"
                  value-format="HH:mm"
                  :clearable="true"
                  class="af-pause-picker"
                />
                <span class="af-pause-sep">{{ t('common.to') }}</span>
                <el-time-picker
                  v-model="form.pause_end_time"
                  :placeholder="t('mercariAccounts.pauseEndPlaceholder')"
                  format="HH:mm"
                  value-format="HH:mm"
                  :clearable="true"
                  class="af-pause-picker"
                />
              </div>
            </el-form-item>
          </el-collapse-item>
          <!-- 煤炉退货的返品先住所（默认折叠）：取消申请被同意后，待办「填写返品先住所」把它填进 返品くん。
               独立接口、独立实时保存，不走上面账号字段的保存。 -->
          <el-collapse-item
            v-if="form.id && form.platform === 'mercari'"
            :title="t('mercariAccounts.sectionReturnAddress')"
            name="return-address"
          >
            <el-form-item :label="t('mercariAccounts.raName')">
              <div class="ra-pair">
                <el-input v-model="returnAddress.last_name" maxlength="30" />
                <el-input v-model="returnAddress.first_name" maxlength="30" />
              </div>
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raKana')">
              <div class="ra-pair">
                <el-input v-model="returnAddress.last_name_kana" maxlength="30" />
                <el-input v-model="returnAddress.first_name_kana" maxlength="30" />
              </div>
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raTel')">
              <el-input v-model="returnAddress.tel" maxlength="20" />
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raEmail')">
              <el-input v-model="returnAddress.email" maxlength="100" />
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raZipcode')">
              <el-input v-model="returnAddress.zipcode" maxlength="10" />
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raPrefecture')">
              <el-select v-model="returnAddress.prefecture" clearable style="width: 100%">
                <el-option v-for="p in prefectureOptions" :key="p" :label="p" :value="p" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raCity')">
              <el-input v-model="returnAddress.city" maxlength="60" />
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raAddress1')">
              <el-input v-model="returnAddress.address1" maxlength="60" />
            </el-form-item>
            <el-form-item :label="t('mercariAccounts.raAddress2')">
              <el-input v-model="returnAddress.address2" maxlength="60" />
            </el-form-item>
            <el-form-item label-width="120px">
              <el-alert
                v-if="returnAddressProblems.length"
                type="warning"
                :closable="false"
                show-icon
                :title="t('mercariAccounts.raIncomplete', { list: returnAddressProblems.join('；') })"
              />
              <el-alert v-else type="success" :closable="false" show-icon :title="t('mercariAccounts.raReady')" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
      </el-form>
      <template #footer>
        <div class="mercari-dialog-footer">
          <el-popconfirm v-if="form.id && $can('shop-accounts:delete')" :title="t('mercariAccounts.deleteConfirm')" @confirm="removeFromDialog">
            <template #reference>
              <el-button type="danger" plain>{{ t('common.delete') }}</el-button>
            </template>
          </el-popconfirm>
          <div class="mercari-dialog-footer__actions">
            <el-button
              v-if="!form.id && form.platform === 'mercari'"
              plain
              :loading="browserLoadingKeys.has(MERCARI_PREPARE_KEY)"
              @click="openPrepareLoginBrowser"
            >{{ t('mercariAccounts.openLoginBrowser') }}</el-button>
            <el-button
              v-if="!form.id && form.platform === 'yahoo'"
              type="warning"
              plain
              :loading="browserLoadingKeys.has(YAHOO_PREPARE_KEY)"
              @click="openYahooLoginBrowser"
            >{{ t('mercariAccounts.openYahooLoginBrowser') }}</el-button>
            <el-button v-if="!form.id && form.platform === 'mercari'" plain @click="onFetchUserInfoPlaceholder">{{ t('mercariAccounts.fetchUserInfo') }}</el-button>
            <el-button
              v-if="form.id && form.platform === 'mercari' && $can('shop-accounts:sync')"
              type="success"
              plain
              :loading="syncingIds.has(form.id)"
              @click="fetchHistoryFromForm"
            >{{ t('mercariAccounts.fetchHistory') }}</el-button>
            <el-button
              v-if="form.id && $can('shop-accounts:browser')"
              type="warning"
              plain
              :loading="cookieInjectKeys.has(browserKeyFor(form.id))"
              @click="injectCookieForAccount(form)"
            >{{ t('mercariAccounts.cookieInject') }}</el-button>
            <!-- 编辑态实时保存：没有「保存」按钮，改动即写库（不提示保存状态，失败由拦截器报错） -->
            <el-button @click="dialogVisible = false">{{ form.id ? t('common.close') : t('common.cancel') }}</el-button>
            <el-button v-if="!form.id" type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="syncDataDialogVisible"
      :title="t('mercariAccounts.syncDataDialogTitle')"
      width="420px"
      destroy-on-close
      class="mercari-dialog"
    >
      <div class="af-task-cards sync-data-cards">
        <div
          v-for="def in SYNC_TASK_DEFS"
          :key="def.key"
          class="af-task-card"
          :class="{ 'is-active': syncDataChecked[def.key] }"
          @click="syncDataChecked[def.key] = !syncDataChecked[def.key]"
        >
          <el-checkbox
            v-model="syncDataChecked[def.key]"
            @click.stop
          >{{ syncTaskLabel(def) }}</el-checkbox>
        </div>
      </div>
      <template #footer>
        <el-button @click="syncDataDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="confirmSyncData">{{ t('mercariAccounts.syncData') }}</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<style src="./style.global.css"></style>
