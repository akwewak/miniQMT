#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""证券代码市场后缀补全测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import Methods


class TestStockCodeSuffix(unittest.TestCase):
    """覆盖沪深常见证券代码段的后缀补全。"""

    def test_add_xt_suffix_common_sh_sz_prefixes(self):
        cases = {
            # 沪市股票、B股、ETF/基金、可转债/可交换债、回购
            '510050': '510050.SH',
            '588000': '588000.SH',
            '600000': '600000.SH',
            '688001': '688001.SH',
            '900901': '900901.SH',
            '110001': '110001.SH',
            '113001': '113001.SH',
            '118001': '118001.SH',
            '132001': '132001.SH',
            '204001': '204001.SH',
            # 深市股票、B股、ETF/基金、可转债、回购
            '000001': '000001.SZ',
            '001979': '001979.SZ',
            '002594': '002594.SZ',
            '003816': '003816.SZ',
            '200001': '200001.SZ',
            '300750': '300750.SZ',
            '301001': '301001.SZ',
            '150001': '150001.SZ',
            '158001': '158001.SZ',
            '159915': '159915.SZ',
            '160105': '160105.SZ',
            '184801': '184801.SZ',
            '111001': '111001.SZ',
            '123456': '123456.SZ',
            '127001': '127001.SZ',
            '128001': '128001.SZ',
            '131810': '131810.SZ',
            # 北交所：一期仅自动识别 920 段，避免误判股转挂牌旧代码段
            '920118': '920118.BJ',
        }

        for raw_code, expected in cases.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(Methods.add_xt_suffix(raw_code), expected)

    def test_add_xt_suffix_normalizes_existing_suffix_and_prefix_style(self):
        cases = {
            '510050.sh': '510050.SH',
            ' 159915.sz ': '159915.SZ',
            'sh.510050': '510050.SH',
            'sz.159915': '159915.SZ',
            '920118.bj': '920118.BJ',
            'bj.920118': '920118.BJ',
            '830799.BJ': '830799.BJ',
        }

        for raw_code, expected in cases.items():
            with self.subTest(raw_code=raw_code):
                self.assertEqual(Methods.add_xt_suffix(raw_code), expected)

    def test_add_xt_suffix_keeps_unknown_code_for_validation(self):
        self.assertEqual(Methods.add_xt_suffix('ABC001'), 'ABC001')
        self.assertEqual(Methods.add_xt_suffix('700001'), '700001')
        self.assertEqual(Methods.add_xt_suffix('000920'), '000920.SZ')
        self.assertEqual(Methods.add_xt_suffix('830799'), '830799')
        self.assertEqual(Methods.add_xt_suffix('870001'), '870001')
        self.assertEqual(Methods.add_xt_suffix('430001'), '430001')
        self.assertEqual(Methods.add_xt_suffix('510050.BJ'), '510050.BJ')
        self.assertEqual(Methods.add_xt_suffix('sh.510050.xx'), 'SH.510050.XX')
        self.assertEqual(Methods.add_xt_suffix(''), '')
        self.assertIsNone(Methods.add_xt_suffix(None))


if __name__ == '__main__':
    unittest.main()
