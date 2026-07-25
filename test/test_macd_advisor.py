"""macd_advisor.classify 纯逻辑单测。

覆盖决策矩阵四象限 + 边界(DEA 持平、DEA=0、数据无效) + series 构建/类别下标。
"""
import unittest

import pandas as pd

import macd_advisor


class TestMacdClassify(unittest.TestCase):
    # ---- 四象限 ----
    def test_strong_up(self):
        """DEA 向上 + 0 轴以上 → 上升趋势(强)/重仓/启动"""
        r = macd_advisor.classify(dea_prev=0.5, dea_last=0.8, dif_last=1.0)
        self.assertEqual(r["trend"], "上升趋势(强)")
        self.assertEqual(r["base_position"], "重仓")
        self.assertEqual(r["grid"], "启动")

    def test_weak_up_repair(self):
        """DEA 向上 + 0 轴以下 → 上升趋势(弱/修复)/半仓以下/启动"""
        r = macd_advisor.classify(dea_prev=-0.8, dea_last=-0.5, dif_last=-0.4)
        self.assertEqual(r["trend"], "上升趋势(弱/修复)")
        self.assertEqual(r["base_position"], "半仓以下")
        self.assertEqual(r["grid"], "启动")

    def test_weak_down_top(self):
        """DEA 向下 + 0 轴以上 → 下降趋势(弱)/顶部反转/半仓以下/启动"""
        r = macd_advisor.classify(dea_prev=0.8, dea_last=0.5, dif_last=0.4)
        self.assertEqual(r["trend"], "下降趋势(弱)/顶部反转")
        self.assertEqual(r["base_position"], "半仓以下")
        self.assertEqual(r["grid"], "启动")

    def test_strong_down(self):
        """DEA 向下 + 0 轴以下 → 下降趋势(强)/清仓/停用"""
        r = macd_advisor.classify(dea_prev=-0.5, dea_last=-0.8, dif_last=-1.0)
        self.assertEqual(r["trend"], "下降趋势(强)")
        self.assertEqual(r["base_position"], "清仓")
        self.assertEqual(r["grid"], "停用")

    # ---- 边界 ----
    def test_dea_flat_treated_as_up(self):
        """DEA 持平(dea_last == dea_prev) 按向上处理"""
        r = macd_advisor.classify(dea_prev=0.5, dea_last=0.5, dif_last=0.6)
        self.assertEqual(r["base_position"], "重仓")

    def test_dif_zero_is_below_axis(self):
        """DIF == 0 视为 0 轴以下(> 0 才算以上)；向下→清仓"""
        r = macd_advisor.classify(dea_prev=0.2, dea_last=0.0, dif_last=0.0)
        self.assertEqual(r["base_position"], "清仓")
        self.assertEqual(r["grid"], "停用")

    def test_axis_uses_dif_not_dea(self):
        """0轴位置看 DIF：DEA向上且DEA>0，但DIF<0 → 半仓以下(cat1)，而非重仓"""
        r = macd_advisor.classify(dea_prev=0.3, dea_last=0.5, dif_last=-0.1)
        self.assertEqual(r["trend"], "上升趋势(弱/修复)")
        self.assertEqual(r["base_position"], "半仓以下")

    def test_none_input_returns_none(self):
        self.assertIsNone(macd_advisor.classify(None, 0.5, 0.5))
        self.assertIsNone(macd_advisor.classify(0.5, None, 0.5))

    def test_invalid_input_returns_none(self):
        self.assertIsNone(macd_advisor.classify("x", 0.5, 0.5))

    # ---- 金叉/死叉补充说明 ----
    def test_cross_bullish(self):
        r = macd_advisor.classify(dea_prev=0.5, dea_last=0.8, dif_last=1.0)
        self.assertIn("多头", r["cross"])

    def test_cross_bearish(self):
        r = macd_advisor.classify(dea_prev=0.5, dea_last=0.8, dif_last=0.6)
        self.assertIn("空头", r["cross"])

    def test_cross_empty_when_dif_none(self):
        r = macd_advisor.classify(dea_prev=0.5, dea_last=0.8, dif_last=None)
        self.assertEqual(r["cross"], "")


class TestIsIndexCode(unittest.TestCase):
    def test_shenzhen_index(self):
        self.assertTrue(macd_advisor._is_index_code("399001.SZ"))

    def test_stock_not_index(self):
        self.assertFalse(macd_advisor._is_index_code("002440.SZ"))

    def test_shanghai_index(self):
        self.assertTrue(macd_advisor._is_index_code("000001.SH"))


class TestCatIndex(unittest.TestCase):
    def test_four_quadrants(self):
        # 方向看 DEA，0轴看 DIF
        self.assertEqual(macd_advisor._cat_index(0.5, 0.8, 1.0), 0)    # 向上+DIF>0
        self.assertEqual(macd_advisor._cat_index(-0.8, -0.5, -0.4), 1)  # 向上+DIF<0
        self.assertEqual(macd_advisor._cat_index(0.8, 0.5, 0.4), 2)    # 向下+DIF>0
        self.assertEqual(macd_advisor._cat_index(-0.5, -0.8, -1.0), 3)  # 向下+DIF<0

    def test_axis_by_dif(self):
        """DEA>0 但 DIF<0，向上 → cat1(非0)"""
        self.assertEqual(macd_advisor._cat_index(0.3, 0.5, -0.1), 1)

    def test_dif_none_is_below(self):
        self.assertEqual(macd_advisor._cat_index(0.5, 0.8, None), 1)

    def test_cat_matches_classify(self):
        """_cat_index → CATEGORIES 与 classify 输出的 trend 一致"""
        cat = macd_advisor._cat_index(0.5, 0.8, 1.0)
        self.assertEqual(macd_advisor.CATEGORIES[cat]["trend"],
                         macd_advisor.classify(0.5, 0.8, 1.0)["trend"])


class TestBuildSeries(unittest.TestCase):
    def _frames(self, rows):
        """rows: [(date, o,h,l,c, dif, dea, hist)]"""
        hist = pd.DataFrame([
            {"stock_code": "T", "date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]}
            for r in rows
        ])
        ind = pd.DataFrame([
            {"stock_code": "T", "date": r[0], "macd": r[5], "macd_signal": r[6], "macd_hist": r[7]}
            for r in rows
        ])
        return hist, ind

    def test_basic_series(self):
        rows = [
            ("2026-07-20", 10, 11, 9.5, 10.5, 0.1, 0.05, 0.05),
            ("2026-07-21", 10.5, 11.5, 10, 11, 0.2, 0.1, 0.1),
        ]
        hist, ind = self._frames(rows)
        s = macd_advisor._build_series(hist, ind)
        self.assertEqual(len(s), 2)
        self.assertEqual(s[0]["d"], "2026-07-20")
        self.assertEqual(s[1]["c"], 11.0)
        # 两根都是 DEA 向上、0轴上 → cat 0
        self.assertEqual(s[1]["cat"], 0)

    def test_cat_labeled_per_day(self):
        """DEA 由上转下时类别切换"""
        rows = [
            ("2026-07-20", 10, 11, 9, 10.5, 0.5, 0.8, -0.3),   # prev=0.8(自身) up → cat0
            ("2026-07-21", 10.5, 11, 10, 10.2, 0.3, 0.5, -0.2),  # 0.5<0.8 向下,0轴上 → cat2
        ]
        hist, ind = self._frames(rows)
        s = macd_advisor._build_series(hist, ind)
        self.assertEqual(s[1]["cat"], 2)

    def test_limits_to_series_bars(self):
        rows = [(f"2026-{(i//28)+1:02d}-{(i%28)+1:02d}", 10, 11, 9, 10, 0.1, 0.05, 0.05)
                for i in range(macd_advisor.SERIES_BARS + 20)]
        hist, ind = self._frames(rows)
        s = macd_advisor._build_series(hist, ind)
        self.assertEqual(len(s), macd_advisor.SERIES_BARS)

    def test_empty_hist_returns_empty(self):
        _, ind = self._frames([("2026-07-20", 10, 11, 9, 10, 0.1, 0.05, 0.05)])
        self.assertEqual(macd_advisor._build_series(pd.DataFrame(), ind), [])

    def test_ma34_present(self):
        """>=34 根时最后一根应有 ma8/ma34；不足则为 None"""
        rows = [(f"2026-{(i//28)+1:02d}-{(i%28)+1:02d}", 10+i*0.1, 11+i*0.1, 9+i*0.1, 10+i*0.1, 0.1, 0.05, 0.05)
                for i in range(40)]
        hist, ind = self._frames(rows)
        s = macd_advisor._build_series(hist, ind)
        self.assertIn("ma8", s[-1])
        self.assertIn("ma34", s[-1])
        self.assertIsNotNone(s[-1]["ma8"])
        self.assertIsNotNone(s[-1]["ma34"])
        self.assertIsNone(s[0]["ma34"])  # 首根不足34不计算
        self.assertIsNone(s[0]["ma8"])   # 首根不足8不计算

    def test_skips_days_without_ohlc(self):
        """指标有该日但 OHLC 缺失 → 跳过"""
        hist = pd.DataFrame([{"stock_code": "T", "date": "2026-07-20", "open": 10, "high": 11, "low": 9, "close": 10}])
        ind = pd.DataFrame([
            {"stock_code": "T", "date": "2026-07-20", "macd": 0.1, "macd_signal": 0.05, "macd_hist": 0.05},
            {"stock_code": "T", "date": "2026-07-21", "macd": 0.2, "macd_signal": 0.1, "macd_hist": 0.1},
        ])
        s = macd_advisor._build_series(hist, ind)
        self.assertEqual(len(s), 1)


if __name__ == "__main__":
    unittest.main()
