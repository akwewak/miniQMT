#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web1.0 网格配置弹窗静态回归测试。"""

import os
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB1_DIR = os.path.join(PROJECT_ROOT, "web1.0")


class TestWeb1GridDialogStatic(unittest.TestCase):
    def _read_web1_file(self, filename):
        with open(os.path.join(WEB1_DIR, filename), "r", encoding="utf-8") as f:
            return f.read()

    def test_grid_dialog_has_auto_toggle_and_deviation_placeholder(self):
        html = self._read_web1_file("index.html")

        self.assertIn('id="gridAutoToggleRow"', html)
        self.assertIn('id="gridAutoEnabled"', html)
        self.assertIn('id="gridAutoStatusLabel"', html)
        self.assertIn('id="gridCurrentPriceDeviation"', html)

    def test_grid_dialog_script_wires_enabled_api_and_deviation_calculation(self):
        script = self._read_web1_file("script.js")

        self.assertIn("/api/grid/session/${sessionId}/enabled", script)
        self.assertIn("function updateGridPriceDeviation", script)
        self.assertIn("function updateGridAutoToggleUI", script)
        self.assertIn("setGridSessionEnabled(activeSessionId", script)
        self.assertIn("centerPriceInput.addEventListener('input'", script)

    def test_grid_tooltip_uses_backend_ratios_without_double_scaling(self):
        script = self._read_web1_file("script.js")

        self.assertIn("snapshot.profit_ratio ?? stats.profit_ratio", script)
        self.assertIn("profitElement.textContent = formatGridPercent(profitRatio)", script)
        self.assertIn("stats.center_deviation_ratio", script)
        self.assertIn("stats.deviation_ratio", script)
        self.assertIn("formatGridPercent(deviation)", script)
        self.assertNotIn("Math.abs(profitRatio) <= 1 ? profitRatio * 100 : profitRatio", script)

    def test_top_auto_switches_are_split_and_wired(self):
        html = self._read_web1_file("index.html")
        script = self._read_web1_file("script.js")

        self.assertNotIn('id="globalAutoOperation"', html)
        self.assertNotIn('全局策略自动运行', html)
        self.assertIn('id="apiToken"', html)
        self.assertIn('id="simulationMode"', html)
        self.assertIn('允许自动止盈', html)
        self.assertIn('id="globalAllowGridTrading"', html)
        self.assertIn('允许自动网格', html)

        switch_order = [
            'id="apiToken"',
            'id="simulationMode"',
            'id="globalAllowGridTrading"',
            'id="globalAllowBuySell"',
        ]
        switch_positions = [html.index(marker) for marker in switch_order]
        self.assertEqual(switch_positions, sorted(switch_positions))
        self.assertIn('class="sp-switch flex-shrink-0" title="允许自动止盈"', html)
        self.assertIn("flex-nowrap", html)
        self.assertIn("overflow-x-auto", html)

        self.assertNotIn('setGlobalAutoOperation(event.target.checked)', script)
        self.assertNotIn('globalAutoOperation: elements.globalAutoOperation.checked', script)
        self.assertIn('globalAllowGridTrading: elements.globalAllowGridTrading.checked', script)
        self.assertIn('{ globalAllowGridTrading: gridTradingEnabled }', script)

    def test_global_auto_operation_is_periodically_synced(self):
        script = self._read_web1_file("script.js")

        self.assertIn("function syncMonitoringState", script)
        self.assertIn(
            "const backendMonitoring = statusData.settings?.isMonitoring ?? statusData.isMonitoring ?? false",
            script,
        )
        self.assertIn("syncMonitoringState(backendMonitoring, 'status')", script)
        self.assertIn("syncMonitoringState(monitoringInfo.isMonitoring, 'sse')", script)
        self.assertNotIn("window._initialMonitoringLoaded", script)

    def test_holdings_empty_row_removed_before_rendering_positions(self):
        script = self._read_web1_file("script.js")

        stale_check = "const hasStaleEmptyRow = Array.isArray(holdings)"
        cleanup = "querySelectorAll('tr:not([data-stock-code])').forEach(row => row.remove())"
        existing_rows = "const existingRows = {}"

        self.assertIn('data-empty-row="true"', script)
        self.assertIn(stale_check, script)
        self.assertIn(cleanup, script)
        self.assertLess(
            script.index(cleanup),
            script.index(existing_rows),
            "有持仓数据时必须先移除空状态占位行，再执行增量行更新"
        )


    def test_order_log_cache_key_includes_current_date(self):
        """下单日志重绘缓存键必须并入当前日期，否则跨日不刷新日期标签。

        日期分组标题由 formatLogDayLabel() 渲染为"今天/昨天"，取决于当前日期
        而非数据本身。缓存键只比数据时，跨过午夜且当日尚无新成交，
        updateLogs 会命中缓存跳过重绘，昨天的记录一直显示为"今天"。
        """
        script = self._read_web1_file("script.js")

        cache_key = "const logsStr = new Date().toDateString() + '|' + JSON.stringify(logEntries)"
        # 用 assertTrue 而非 assertIn：后者失败时会 dump 整个 script.js(160KB+)，淹没失败信息
        self.assertTrue(
            cache_key in script,
            "updateLogs 缓存键必须包含当前日期，否则跨日日期标签不刷新；"
            f"未找到: {cache_key}"
        )
        # 防回归：不得退回只比较数据的旧写法
        self.assertFalse(
            "const logsStr = JSON.stringify(logEntries);" in script,
            "缓存键退回了纯数据比较(const logsStr = JSON.stringify(logEntries);)，跨日重绘会再次失效"
        )
        # 缓存键必须在比较之前构造
        self.assertLess(
            script.index(cache_key),
            script.index("if (window._lastLogsStr === logsStr)"),
            "缓存键须先于比较构造"
        )

    def test_order_log_day_label_depends_on_current_date(self):
        """固化 formatLogDayLabel 对当前日期的依赖——这正是缓存键需含日期的前提。

        若其改为纯数据映射（不再读 new Date()），上面的缓存键要求即可放宽；
        本用例失败时应一并复查 test_order_log_cache_key_includes_current_date。
        """
        script = self._read_web1_file("script.js")

        start = script.index("function formatLogDayLabel(")
        end = script.index("function ", start + 1)
        body = script[start:end]

        for token in ("const today = new Date();", "return '今天'", "return '昨天'"):
            self.assertTrue(token in body, f"formatLogDayLabel 中未找到: {token}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
