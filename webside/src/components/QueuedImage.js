// 全局 <el-image> 的替身：轮到它（utils/imageQueue.js）之前只画 ElImage 同款的占位块，轮到了才渲染真正的 ElImage。
// 不能先渲染 ElImage 再晚点给 src：它的 src 默认 ''，会立刻出一个 <img src=""> 报 error。
// lazy 由队列按可见性处理，所以内层一律不再 lazy。其余属性 / 插槽原样透传。
import { defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElImage } from 'element-plus'
import { enqueueImage } from '../utils/imageQueue.js'

export default defineComponent({
  name: 'ElImage',
  inheritAttrs: false,
  props: {
    src: { type: String, default: '' },
    lazy: Boolean,
    loading: { type: String, default: undefined },
  },
  setup(props, { attrs, slots }) {
    const holder = ref(null)
    const granted = ref(undefined)
    let ticket = null

    function release() {
      if (ticket) ticket.cancel()
      ticket = null
    }

    async function schedule() {
      release()
      const src = props.src
      // 空地址照旧交给 ElImage，由它显示「加载失败」
      if (!src) {
        granted.value = src
        return
      }
      granted.value = undefined
      await nextTick()
      if (props.src !== src || !holder.value) return
      ticket = enqueueImage(holder.value, src, {
        lazy: props.lazy || props.loading === 'lazy',
        onStart: () => {
          granted.value = src
        },
      })
    }

    function settle(ok, handler, event) {
      if (ticket) ticket.done(ok)
      ticket = null
      if (typeof handler === 'function') handler(event)
    }

    onMounted(schedule)
    watch(() => props.src, schedule)
    onBeforeUnmount(release)

    return () => {
      if (granted.value === undefined) {
        return h('div', { ref: holder, class: ['el-image', attrs.class], style: attrs.style }, [
          h('div', { class: 'el-image__wrapper' }, slots.placeholder ? slots.placeholder() : [h('div', { class: 'el-image__placeholder' })]),
        ])
      }
      return h(
        ElImage,
        {
          ...attrs,
          src: granted.value,
          onLoad: (e) => settle(true, attrs.onLoad, e),
          onError: (e) => settle(false, attrs.onError, e),
        },
        slots,
      )
    }
  },
})
