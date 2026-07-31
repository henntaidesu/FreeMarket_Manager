<template>
  <div>
    <el-card shadow="never" class="list-card" v-loading="loading">
      <el-row :gutter="16">
        <el-col v-for="row in list" :key="row.id" :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
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
                <el-tag :type="platformTagType(row.platform)" size="small" effect="plain">
                  {{ platformName(row.platform) }}
                </el-tag>
                <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
                  {{ row.status === 'active' ? t('mercariAccounts.enabled') : t('mercariAccounts.disabled') }}
                </el-tag>
              </div>
            </div>
            <div class="card-item"><span>{{ t('mercariAccounts.platformLabel') }}</span>{{ platformName(row.platform) }}</div>
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
                    :disabled="row.status !== 'active'"
                    @click="openSyncDataDialog(row)"
                  >{{ t('mercariAccounts.syncData') }}</el-button>
                </span>
              </el-tooltip>
              <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <div class="add-card">
            <div class="add-card-main" @click="openCreate">
              <el-icon class="add-card-icon"><Plus /></el-icon>
              <span>{{ t('mercariAccounts.addAccount') }}</span>
            </div>
          </div>
        </el-col>
      </el-row>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load"
          background
          size="small"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="platformPickerVisible"
      :title="t('mercariAccounts.pickPlatformTitle')"
      width="420px"
      destroy-on-close
      class="mercari-dialog"
    >
      <div class="platform-picker">
        <div
          v-for="opt in PLATFORM_OPTIONS"
          :key="opt.value"
          class="platform-picker-card"
          @click="pickPlatform(opt.value)"
        >
          <el-tag :type="opt.tagType" size="large" effect="plain">{{ t(opt.labelKey) }}</el-tag>
        </div>
      </div>
    </el-dialog>

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
      <el-form :model="form" :rules="formRules" ref="formRef" label-width="120px" class="mercari-form">
        <el-divider content-position="left">{{ t('mercariAccounts.sectionBasicInfo') }}</el-divider>
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
                :placeholder="sellerIdPlaceholder"
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
        <el-divider content-position="left">{{ t('mercariAccounts.sectionAutoFetch') }}</el-divider>
        <el-form-item :label="t('mercariAccounts.syncItems')">
          <div class="af-task-list">
            <div class="af-task-row" v-for="def in FETCH_TASKS" :key="def.key">
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
      </el-form>
      <template #footer>
        <div class="mercari-dialog-footer">
          <el-popconfirm v-if="form.id" :title="t('mercariAccounts.deleteConfirm')" @confirm="removeFromDialog">
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
              v-if="form.id && form.platform === 'mercari'"
              type="success"
              plain
              :loading="syncingIds.has(form.id)"
              @click="fetchHistoryFromForm"
            >{{ t('mercariAccounts.fetchHistory') }}</el-button>
            <el-button
              v-if="form.id && form.platform === 'mercari'"
              type="warning"
              plain
              :loading="cookieInjectKeys.has(browserKeyFor(form.id))"
              @click="injectCookieForAccount(form)"
            >{{ t('mercariAccounts.cookieInject') }}</el-button>
            <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
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
