<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-radio-group v-model="tab" @change="onTabChange">
            <el-radio-button label="inbox">
              {{ t('memos.tabInbox') }}
              <el-badge
                v-if="unread > 0"
                :value="unread"
                :max="99"
                class="memos-badge"
              />
            </el-radio-button>
            <el-radio-button label="processed">{{ t('memos.tabProcessed') }}</el-radio-button>
            <el-radio-button label="sent">{{ t('memos.tabSent') }}</el-radio-button>
          </el-radio-group>

          <el-input
            v-model="keyword"
            :placeholder="t('memos.searchPlaceholder')"
            clearable
            class="search-keyword"
            @keyup.enter="reload(1)"
            @clear="reload(1)"
          >
            <template #suffix>
              <el-icon class="memos-search-icon" @click="reload(1)"><Search /></el-icon>
            </template>
          </el-input>
        </div>
        <div class="search-actions">
          <el-button
            v-if="tab === 'inbox'"
            :disabled="unread === 0"
            @click="markAllRead"
          >
            <el-icon><Check /></el-icon> {{ t('memos.markAllProcessed') }}
          </el-button>
          <el-button type="primary" @click="openComposeDialog">
            <el-icon><EditPen /></el-icon> {{ t('memos.compose') }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        :data="list"
        v-loading="loading"
        stripe
        @row-click="onRowClick"
      >
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column
          v-if="tab !== 'sent'"
          :label="t('memos.colSender')"
          width="140"
        >
          <template #default="{ row }">
            <span>{{ row.sender?.display_name || row.sender?.username || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column
          v-else
          :label="t('memos.colReceiver')"
          width="140"
        >
          <template #default="{ row }">
            <span>{{ row.receiver?.display_name || row.receiver?.username || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('memos.colTitle')" prop="title" min-width="160">
          <template #default="{ row }">
            <span>{{ row.title || t('memos.untitled') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('memos.colContent')" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.content }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('memos.colImages')" width="90" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.images && row.images.length"
              effect="dark"
              placement="top"
              :content="t('memos.imageCount', { n: row.images.length })"
            >
              <span class="memos-image-count">
                <el-icon><Picture /></el-icon>
                {{ row.images.length }}
              </span>
            </el-tooltip>
            <span v-else class="memos-image-none">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('memos.colCreatedAt')" prop="created_at" width="170" />
        <el-table-column
          v-if="tab === 'processed'"
          :label="t('memos.colProcessedAt')"
          prop="read_at"
          width="170"
        >
          <template #default="{ row }">
            <span>{{ row.read_at || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click.stop="openDetail(row)">
              {{ t('memos.view') }}
            </el-button>
            <el-button
              v-if="tab === 'inbox'"
              size="small"
              type="primary"
              @click.stop="setRead(row, true)"
            >
              {{ t('memos.markProcessed') }}
            </el-button>
            <el-button
              v-else-if="tab === 'processed'"
              size="small"
              @click.stop="setRead(row, false)"
            >
              {{ t('memos.markUnprocessed') }}
            </el-button>
            <el-popconfirm
              :title="t('memos.deleteConfirm')"
              @confirm="remove(row.id)"
            >
              <template #reference>
                <el-button size="small" type="danger" @click.stop>
                  {{ t('common.delete') }}
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="memos-pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="reload()"
          @size-change="reload(1)"
        />
      </div>
    </el-card>

    <!-- 新建备忘录 -->
    <el-dialog
      v-model="composeVisible"
      :title="t('memos.composeTitle')"
      width="520px"
      destroy-on-close
    >
      <el-form :model="composeForm" :rules="composeRules" ref="composeFormRef" label-width="80px">
        <el-form-item :label="t('memos.receiver')" prop="receiver_id">
          <el-select
            v-model="composeForm.receiver_id"
            :placeholder="t('memos.receiverPlaceholder')"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="u in users"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('memos.colTitle')">
          <el-input v-model="composeForm.title" :placeholder="t('memos.titlePlaceholder')" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item :label="t('memos.colContent')" prop="content">
          <el-input
            v-model="composeForm.content"
            type="textarea"
            :rows="5"
            :placeholder="t('memos.contentPlaceholder')"
            maxlength="2000"
            show-word-limit
          />
        </el-form-item>
        <el-form-item :label="t('memos.attachments')">
          <el-upload
            list-type="picture-card"
            :file-list="composeFileList"
            :auto-upload="false"
            :on-change="onPickImage"
            :on-remove="onRemoveImage"
            :on-preview="onPreviewImage"
            :limit="9"
            accept="image/*"
            multiple
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
          <div class="memos-attach-hint">
            {{ t('memos.attachmentsHint') }}
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="composeVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCompose">
          {{ t('memos.send') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 查看详情 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailMemo?.title || t('memos.untitled')"
      width="560px"
      destroy-on-close
    >
      <div v-if="detailMemo" class="memos-detail">
        <div class="memos-detail-row">
          <span class="memos-detail-label">{{ tab === 'inbox' ? t('memos.colSender') : t('memos.colReceiver') }}：</span>
          <span>
            {{
              tab === 'inbox'
                ? (detailMemo.sender?.display_name || detailMemo.sender?.username || '-')
                : (detailMemo.receiver?.display_name || detailMemo.receiver?.username || '-')
            }}
          </span>
        </div>
        <div class="memos-detail-row">
          <span class="memos-detail-label">{{ t('memos.colCreatedAt') }}：</span>
          <span>{{ detailMemo.created_at }}</span>
        </div>
        <div v-if="tab === 'processed' && detailMemo.read_at" class="memos-detail-row">
          <span class="memos-detail-label">{{ t('memos.colProcessedAt') }}：</span>
          <span>{{ detailMemo.read_at }}</span>
        </div>
        <el-divider />
        <pre class="memos-detail-content">{{ detailMemo.content }}</pre>
        <div
          v-if="detailMemo.images && detailMemo.images.length"
          class="memos-detail-images"
        >
          <el-image
            v-for="(src, i) in detailMemo.images"
            :key="src + i"
            class="memos-detail-image"
            :src="src"
            :preview-src-list="detailMemo.images"
            :initial-index="i"
            fit="cover"
            preview-teleported
          />
        </div>
      </div>
      <template #footer>
        <el-button
          v-if="tab === 'inbox' && detailMemo"
          type="primary"
          @click="setRead(detailMemo, true)"
        >
          {{ t('memos.markProcessed') }}
        </el-button>
        <el-button
          v-else-if="tab === 'processed' && detailMemo"
          @click="setRead(detailMemo, false)"
        >
          {{ t('memos.markUnprocessed') }}
        </el-button>
        <el-button @click="detailVisible = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
