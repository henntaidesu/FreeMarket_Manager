<template>
  <div ref="host" class="echart-host" :style="{ height: height }"></div>
</template>

<script setup>
/**
 * 极小的 ECharts 容器：按需注册图表/组件（只打包用到的部分），
 * 跟随容器尺寸变化 resize，卸载时销毁实例。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '260px' },
})

const host = ref(null)
const chart = shallowRef(null)
let observer = null

function render() {
  if (!chart.value) return
  // notMerge=true：区间切换后系列长度会变，合并会残留上一次的数据点
  chart.value.setOption(props.option, true)
}

onMounted(() => {
  chart.value = echarts.init(host.value, null, { renderer: 'canvas' })
  render()
  observer = new ResizeObserver(() => chart.value && chart.value.resize())
  observer.observe(host.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
  if (chart.value) chart.value.dispose()
  chart.value = null
})
</script>

<style scoped>
.echart-host {
  width: 100%;
}
</style>
