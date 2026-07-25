<script setup lang="ts">
import { computed } from 'vue'
import { useAdviceTooltip } from '../composables/useAdviceTooltip'
import { renderMacdChartSVG } from '../utils/macdChart'
const { state } = useAdviceTooltip()
const chartSvg = computed(() =>
  state.data && state.data.series && state.data.series.length ? renderMacdChartSVG(state.data.series) : ''
)
</script>

<template>
  <Teleport to="body">
    <div v-if="state.visible && state.data" class="advice-tooltip" :style="{ left: state.x + 'px', top: state.y + 'px' }">
      <div class="advice-header">
        <span class="advice-trend">{{ state.data.trend }}</span>
        <span class="advice-badge">操作建议</span>
      </div>
      <div class="advice-line">底仓：<b>{{ state.data.base_position }}</b>；网格：<b>{{ state.data.grid }}</b></div>
      <div class="advice-meta">
        <template v-if="state.data.cross">{{ state.data.cross }}<br></template>
        <template v-if="state.data.dif != null">DIF {{ state.data.dif }} / </template>DEA {{ state.data.dea }}｜{{ state.data.updated }}（{{ state.data.code }}）
      </div>
      <div v-if="chartSvg" class="advice-chart" v-html="chartSvg"></div>
    </div>
  </Teleport>
</template>

<style scoped>
.advice-tooltip {
  position: absolute;
  z-index: 9999;
  background: #fff;
  border: 2px solid #d97706;
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  font-size: 13px;
  line-height: 1.6;
  min-width: 220px;
  max-width: 480px;
  pointer-events: none;
}
.advice-trend { font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #78350f; }
.advice-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px; }
.advice-header .advice-trend { margin-bottom: 0; }
.advice-badge { font-size: 11px; padding: 3px 10px; border-radius: 12px; color: #fff; font-weight: 700; white-space: nowrap; background: linear-gradient(135deg, #f59e0b, #d97706); }
.advice-line b { color: #b45309; }
.advice-meta { margin-top: 6px; padding-top: 6px; border-top: 1px solid #eee; color: #888; font-size: 12px; }
.advice-chart { margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee; width: 440px; max-width: 100%; }
</style>
