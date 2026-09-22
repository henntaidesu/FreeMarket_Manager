<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchItem, thumbUrl, imageUrl } from '../api'
import { formatPrice, conditionLabel, SHOP_NAME } from '../format'

const route = useRoute()
const item = ref(null)
const loading = ref(true)
const error = ref('')
const active = ref(0)

async function load(id) {
  loading.value = true
  error.value = ''
  active.value = 0
  try {
    item.value = await fetchItem(id)
    // 商品名进标题栏：详情页是会被分享出去的那一个，标签页/分享卡片都读它
    document.title = `${item.value.name} · ${SHOP_NAME}`
  } catch (e) {
    error.value = e.message
    item.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => load(route.params.id))
// 同一路由换 id（从详情页再点到另一件商品）不会重新挂载组件，必须自己重载
watch(() => route.params.id, (id) => { if (id) load(id) })
</script>

<template>
  <RouterLink to="/" class="back">← 返回目录</RouterLink>

  <div v-if="loading" class="state">加载中…</div>

  <div v-else-if="error" class="state">
    <div class="state__title">没能打开这件商品</div>
    <div>{{ error }}</div>
  </div>

  <div v-else-if="item" class="detail">
    <div class="gallery">
      <div class="gallery__main">
        <img v-if="item.images.length" :src="imageUrl(item.images[active])" :alt="item.name" />
        <div v-else class="thumb__empty">暂无图片</div>
      </div>
      <div v-if="item.images.length > 1" class="gallery__strip">
        <button
          v-for="(p, i) in item.images"
          :key="p"
          class="gallery__thumb"
          :class="{ 'gallery__thumb--on': i === active }"
          type="button"
          @click="active = i"
        >
          <img :src="thumbUrl(p, 160)" :alt="`${item.name} 图 ${i + 1}`" loading="lazy" />
        </button>
      </div>
    </div>

    <div>
      <h1 class="detail__title">{{ item.name }}</h1>
      <div v-if="item.price > 0" class="detail__price">{{ formatPrice(item.price) }}</div>
      <div v-else class="detail__price" style="font-size: 20px; color: var(--text-dim)">价格待定</div>

      <div class="detail__tags">
        <span v-if="item.category_name" class="tag">{{ item.category_name }}</span>
        <span v-if="item.product_type_name" class="tag">{{ item.product_type_name }}</span>
      </div>

      <dl class="detail__rows">
        <div class="detail__row">
          <dt>库存</dt>
          <dd>{{ item.stock }} 件</dd>
        </div>
        <div v-if="conditionLabel(item.condition)" class="detail__row">
          <dt>商品状态</dt>
          <dd>{{ conditionLabel(item.condition) }}</dd>
        </div>
        <div class="detail__row">
          <dt>商品编号</dt>
          <dd>{{ item.id }}</dd>
        </div>
      </dl>

      <div v-if="item.body" class="detail__body">
        <h3>商品说明</h3>{{ item.body }}
      </div>
    </div>
  </div>
</template>
