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


if __name__ == "__main__":
    unittest.main(verbosity=2)
