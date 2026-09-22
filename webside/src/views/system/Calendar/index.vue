<template>
  <el-card shadow="never" class="cal-card" v-loading="loading">
    <!-- 工具栏：今天 / 前后翻 / 标题 / 视图切换 / 新建 -->
    <div class="cal-toolbar">
      <el-button @click="goToday">{{ t('calendar.today') }}</el-button>
      <el-button-group>
        <el-button :icon="ArrowLeft" @click="step(-1)" />
        <el-button :icon="ArrowRight" @click="step(1)" />
      </el-button-group>
      <span class="cal-title">{{ headerTitle }}</span>
      <div class="cal-toolbar-spacer" />
      <el-switch v-model="hideDone" :active-text="t('calendar.hideDone')" />
      <el-radio-group v-model="view">
        <el-radio-button value="month">{{ t('calendar.viewMonth') }}</el-radio-button>
        <el-radio-button value="week">{{ t('calendar.viewWeek') }}</el-radio-button>
        <el-radio-button value="day">{{ t('calendar.viewDay') }}</el-radio-button>
      </el-radio-group>
      <el-button type="primary" :icon="Plus" @click="openCreate({ all_day: true, start_at: fmtDate(cursor), end_at: fmtDate(cursor) })">
        {{ t('calendar.create') }}
      </el-button>
    </div>

    <!-- ============ 月视图 ============ -->
    <div v-if="view === 'month'" class="cal-month">
      <div class="cal-month-head">
        <div v-for="(w, i) in weekdayNames" :key="i" class="cal-month-head-cell">{{ w }}</div>
      </div>
      <div class="cal-month-body">
        <div v-for="week in monthWeeks" :key="week.key" class="cal-week">
          <!-- 格子层：边框、日期数字、点空白新建 -->
          <div class="cal-week-cells">
            <div
              v-for="day in week.days"
              :key="day.getTime()"
              class="cal-cell"
              :class="{ 'is-other-month': !inCurrentMonth(day), 'is-today': isToday(day) }"
              @click="onMonthCellClick(day)"
            >
              <div class="cal-cell-num" @click.stop="openDay(day)">{{ day.getDate() }}</div>
            </div>
          </div>
          <!-- 横条层：跨天事项要压在多个格子上，只能另起一层绝对定位 -->
          <div class="cal-week-bars">
            <div
              v-for="bar in week.bars"
              :key="`${bar.item.ev.id}-${bar.startCol}`"
              class="cal-bar"
              :class="{
                'is-done': bar.item.ev.is_done,
                'is-overdue': isOverdue(bar.item),
                'cont-before': bar.continuesBefore,
                'cont-after': bar.continuesAfter,
              }"
              :style="{
                left: `${(bar.startCol / 7) * 100}%`,
                width: `${(bar.span / 7) * 100}%`,
                top: `${bar.lane * 22}px`,
                '--bar-color': colorOf(bar.item.ev),
              }"
              :title="bar.item.ev.title"
              @click.stop="openEdit(bar.item.ev)"
            >
              <span v-if="!bar.item.ev.all_day" class="cal-bar-dot" />
              <span class="cal-bar-text">{{ barLabel(bar.item) }}</span>
            </div>
            <template v-for="(n, col) in week.overflow" :key="`ov-${col}`">
              <div
                v-if="n > 0"
                class="cal-more"
                :style="{ left: `${(col / 7) * 100}%`, width: `${(1 / 7) * 100}%` }"
                @click.stop="openDay(week.days[col])"
              >
                {{ t('calendar.more', { n }) }}
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 周 / 日视图 ============ -->
    <div v-else class="cal-time">
      <div class="cal-time-head">
        <div class="cal-gutter" />
        <div class="cal-time-head-days">
          <div
            v-for="day in timeGridDays"
            :key="day.getTime()"
            class="cal-time-head-cell"
            :class="{ 'is-today': isToday(day) }"
            @click="openDay(day)"
          >
            <span class="cal-time-head-wd">{{ weekdayNames[(day.getDay() + 6) % 7] }}</span>
            <span class="cal-time-head-num">{{ day.getDate() }}</span>
          </div>
        </div>
      </div>

      <!-- 全天条：跨天与全天事项不属于任何一个时刻，放在时间轴之外 -->
      <div class="cal-allday">
        <div class="cal-gutter cal-allday-label">{{ t('calendar.allDayRow') }}</div>
        <div
          class="cal-allday-lanes"
          :style="{ height: `${Math.max(1, timeGridAllDay.laneCount) * 22 + 4}px` }"
        >
          <div
            v-for="bar in timeGridAllDay.bars"
            :key="`ad-${bar.item.ev.id}`"
            class="cal-bar"
            :class="{ 'is-done': bar.item.ev.is_done, 'is-overdue': isOverdue(bar.item) }"
            :style="{
              left: `${(bar.startCol / timeGridAllDay.cols) * 100}%`,
              width: `${(Math.min(bar.span, timeGridAllDay.cols - bar.startCol) / timeGridAllDay.cols) * 100}%`,
              top: `${bar.lane * 22}px`,
              '--bar-color': colorOf(bar.item.ev),
            }"
            :title="bar.item.ev.title"
            @click.stop="openEdit(bar.item.ev)"
          >
            <span class="cal-bar-text">{{ bar.item.ev.title }}</span>
          </div>
        </div>
      </div>

      <div class="cal-time-body">
        <div class="cal-gutter cal-hours">
          <div
            v-for="h in hours"
            :key="h"
            class="cal-hour-label"
            :style="{ height: `${HOUR_H}px` }"
          >
            <span v-if="h > 0">{{ hourLabel(h) }}</span>
          </div>
        </div>
        <div class="cal-time-cols">
          <div
            v-for="(col, i) in timeGridColumns"
            :key="col.key"
            class="cal-time-col"
            :style="{ height: `${hours.length * HOUR_H}px` }"
            @click="onTimeSlotClick(col.day, $event)"
          >
            <div
              v-for="h in hours"
              :key="h"
              class="cal-hour-line"
              :style="{ top: `${h * HOUR_H}px` }"
            />
            <div
              v-for="b in col.blocks"
              :key="`bk-${b.item.ev.id}`"
              class="cal-block"
              :class="{ 'is-done': b.item.ev.is_done, 'is-overdue': isOverdue(b.item) }"
              :style="{
                top: `${b.topPct}%`,
                height: `max(${MIN_BLOCK_H}px, ${b.heightPct}%)`,
                left: `${(b.col / b.cols) * 100}%`,
                width: `calc(${100 / b.cols}% - 4px)`,
                '--bar-color': colorOf(b.item.ev),
              }"
              :title="b.item.ev.title"
              @click.stop="openEdit(b.item.ev)"
            >
              <div class="cal-block-time">{{ blockTimeRange(b) }}</div>
              <div class="cal-block-title">{{ b.item.ev.title }}</div>
            </div>
            <div v-if="nowLine && nowLine.dayIndex === i" class="cal-now" :style="{ top: `${nowLine.topPct}%` }" />
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 新建 / 编辑 ============ -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="520px" append-to-body>
      <el-form label-width="76px">
        <el-form-item :label="t('calendar.fieldTitle')">
          <el-input
            v-model="form.title"
            :placeholder="t('calendar.titlePlaceholder')"
            maxlength="120"
            show-word-limit
          />
        </el-form-item>
        <el-form-item :label="t('calendar.fieldAllDay')">
          <el-switch v-model="form.all_day" />
        </el-form-item>
        <el-form-item :label="t('calendar.fieldStart')">
          <el-date-picker
            v-if="form.all_day"
            v-model="form.start_at"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="t('calendar.startPlaceholder')"
            class="cal-picker"
          />
          <el-date-picker
            v-else
            v-model="form.start_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            :placeholder="t('calendar.startPlaceholder')"
            class="cal-picker"
          />
        </el-form-item>
        <el-form-item :label="t('calendar.fieldEnd')">
          <el-date-picker
            v-if="form.all_day"
            v-model="form.end_at"
            type="date"
            value-format="YYYY-MM-DD"
            :placeholder="t('calendar.endPlaceholder')"
            class="cal-picker"
          />
          <el-date-picker
            v-else
            v-model="form.end_at"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            :placeholder="t('calendar.endPlaceholder')"
            class="cal-picker"
          />
        </el-form-item>
        <el-form-item :label="t('calendar.fieldColor')">
          <div class="cal-colors">
            <span
              v-for="k in COLOR_KEYS"
              :key="k"
              class="cal-color"
              :class="{ 'is-on': form.color === k }"
              :style="{ background: COLORS[k] }"
              @click="form.color = k"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('calendar.fieldDescription')">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            :placeholder="t('calendar.descriptionPlaceholder')"
          />
        </el-form-item>
      </el-form>
      <div v-if="form.created_by_name" class="cal-meta">
        {{ t('calendar.createdBy', { name: form.created_by_name }) }}
      </div>
      <template #footer>
        <div class="cal-dialog-footer">
          <el-button v-if="editingId" type="danger" plain :icon="Delete" @click="remove">
            {{ t('common.delete') }}
          </el-button>
          <div class="cal-toolbar-spacer" />
          <el-button :type="form.is_done ? 'info' : 'success'" plain @click="toggleDone">
            {{ form.is_done ? t('calendar.markUndone') : t('calendar.markDone') }}
          </el-button>
          <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </el-card>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
