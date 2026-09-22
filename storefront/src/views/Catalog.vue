<script setup>
import { ref, reactive, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchItems, fetchFilters, thumbUrl } from '../api'
import { formatPrice } from '../format'

const route = useRoute()
const router = useRouter()

const items = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref('')
const options = reactive({ categories: [], product_types: [] })

const PAGE_SIZE = 24
// 筛选条件从 URL 初始化：带筛选的地址可以直接分享，浏览器的前进/后退也才有意义。
const q = reactive({
  keyword: route.query.keyword || '',
  category_id: route.query.category_id || '',
  product_type_id: route.query.product_type_id || '',
  sort: route.query.sort || 'newest',
  page: Number(route.query.page || 1) || 1
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetchItems({ ...q, page_size: PAGE_SIZE })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    error.value = e.message
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 把当前条件写回地址栏。空值不入 query，避免 ?keyword=&sort=newest 这种噪声。 */
function syncUrl() {
  const query = {}
  for (const [k, v] of Object.entries(q)) {
    if (v === '' || v === null || v === undefined) continue
    if (k === 'page' && v === 1) continue
    if (k === 'sort' && v === 'newest') continue
    query[k] = String(v)
  }
  router.replace({ query })
}

let kwTimer = null
function onKeyword() {
  // 输入防抖：每敲一个字就打一次接口，对一个公开端点是自找 429
  clearTimeout(kwTimer)
  kwTimer = setTimeout(() => { q.page = 1; apply() }, 350)
}

function apply() {
  syncUrl()
  load()
}

function go(page) {
  q.page = page
  apply()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 下拉筛选与排序即时生效，并回到第一页——留在第 5 页换分类多半会落到空结果上
watch(() => [q.category_id, q.product_type_id, q.sort], () => { q.page = 1; apply() })

onMounted(async () => {
  load()
  try {
    const f = await fetchFilters()
    options.categories = f.categories
    options.product_types = f.product_types
  } catch {
    // 筛选项拉不到不影响浏览：下拉留空，列表照常
  }
})
</script>

<template>
  <div class="toolbar">
    <input
      v-model="q.keyword"
      class="field search"
      type="search"
      placeholder="搜索商品名称"
      @input="onKeyword"
    />
    <select v-model="q.category_id" class="field">
      <option value="">全部分类</option>
      <option v-for="c in options.categories" :key="c.id" :value="c.id">{{ c.name }}</option>
    </select>
    <select v-model="q.product_type_id" class="field">
      <option value="">全部类型</option>
      <option v-for="t in options.product_types" :key="t.id" :value="t.id">{{ t.name }}</option>
    </select>
    <select v-model="q.sort" class="field">
      <option value="newest">最新上架</option>
      <option value="price_asc">价格从低到高</option>
      <option value="price_desc">价格从高到低</option>
    </select>
    <span v-if="!loading && !error" class="toolbar__count">共 {{ total }} 件</span>
  </div>

  <div v-if="loading" class="state">加载中…</div>

  <div v-else-if="error" class="state">
    <div class="state__title">没能加载商品</div>
    <div>{{ error }}</div>
  </div>

  <div v-else-if="!items.length" class="state">
    <div class="state__title">没有符合条件的商品</div>
    <div>换个关键词或分类试试</div>
  </div>

  <template v-else>
    <div class="grid">
      <RouterLink v-for="it in items" :key="it.id" class="card" :to="`/item/${it.id}`">
        <div class="thumb">
          <img
            v-if="it.images.length"
            :src="thumbUrl(it.images[0], 400)"
            :alt="it.name"
            loading="lazy"
          />
          <div v-else class="thumb__empty">暂无图片</div>
          <span class="badge" :class="{ 'badge--low': it.stock <= 2 }">
            {{ it.stock <= 2 ? `仅剩 ${it.stock} 件` : `库存 ${it.stock}` }}
          </span>
        </div>
        <div class="card__body">
          <div class="card__name">{{ it.name }}</div>
          <div class="card__meta">
            <!-- price 为 0 的库存行是「还没定价」，显示 ¥0 会被当成免费 -->
            <span v-if="it.price > 0" class="price">{{ formatPrice(it.price) }}</span>
            <span v-else class="price price--tbd">价格待定</span>
            <span v-if="it.category_name" class="tag">{{ it.category_name }}</span>
          </div>
        </div>
      </RouterLink>
    </div>

    <div v-if="total > PAGE_SIZE" class="pager">
      <button class="btn" :disabled="q.page <= 1" @click="go(q.page - 1)">上一页</button>
      <span>{{ q.page }} / {{ Math.ceil(total / PAGE_SIZE) }}</span>
      <button
        class="btn"
        :disabled="q.page >= Math.ceil(total / PAGE_SIZE)"
        @click="go(q.page + 1)"
      >下一页</button>
    </div>
  </template>
</template>
