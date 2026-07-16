<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="sys-top-actions">
        <el-button type="danger" :loading="restarting" @click="confirmRestartSystem">
          <el-icon><RefreshRight /></el-icon> {{ t('system.restartSystem') }}
        </el-button>
        <el-button type="primary" @click="openUserDialog">
          <el-icon><Plus /></el-icon> {{ t('system.addUser') }}
        </el-button>
      </div>
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="table-card">
          <template #header>
            <div class="card-title">{{ t('system.userList') }}</div>
          </template>
          <el-table :data="users" v-loading="loading" stripe>
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
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="table-card">
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
              <el-button type="primary" :loading="pwdSubmitting" @click="submitPassword">{{ t('system.changePassword') }}</el-button>
            </el-form-item>
          </el-form>
          <div class="pwd-tip">{{ t('system.pwdTip') }}</div>
        </el-card>
      </el-col>
    </el-row>

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

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
