<script setup>
import { SHOP_NAME } from './format'
</script>

<template>
  <header class="site-head">
    <div class="wrap site-head__inner">
      <RouterLink to="/" class="site-title">{{ SHOP_NAME }}<span>.</span></RouterLink>
    </div>
  </header>

  <main class="wrap">
    <RouterView />
  </main>

  <footer class="site-foot">
    <div class="wrap">{{ SHOP_NAME }} · 库存实时同步，数量以页面显示为准</div>
  </footer>
</template>
