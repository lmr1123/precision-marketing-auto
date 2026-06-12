import unittest

from ui_app.text_plan_parser import parse_text_plans


class TextPlanParserTests(unittest.TestCase):
    def test_send_content_keeps_mini_program_url_without_unknown_field_warning(self):
        text = """计划名称: 【6月14日朋友圈】广佛省区上市9周年-肇云
发送渠道:会员通-发客户朋友圈
创建链接:https://precision.dslyy.com/admin#/marketingTemplate/edit?id=599702926159527936
计划区域: 省区
营销主题: 26年6月上市周年庆
场景类型: 促销营销
计划类型: 促销精准营销（大促&会员日）
计划开始时间: 2026-06-12 00:00:00
计划结束时间: 2026-06-21 23:59:59
发送时间: 2026-06-14 08:30:00
主消费营运区: 肇庆营运区、云浮营运区
执行员工: 肇云营运区
员工任务结束时间: 2026-06-21 23:59:59
发送内容: |
新品上市|满50元送50元券！汇元堂虫草洋参胶囊60粒139元，再送2张50元优惠券！红标正价商品满138元立减50元
更多商品到大参林门店选购→#小程序://大参林健康/0zlXowworfnAJea"""

        row = parse_text_plans(text)[0]

        self.assertIn("#小程序://大参林健康/0zlXowworfnAJea", row["send_content"])
        self.assertNotIn("__warnings", row)

    def test_unknown_field_after_multiline_content_still_warns(self):
        text = """计划名称: 测试计划
发送渠道:会员通-发客户朋友圈
营销主题: 其他
计划开始时间: 2026-10-01 00:00:00
计划结束时间: 2026-10-10 23:59:59
发送时间: 2026-10-02 08:30:00
发送内容: |
第一行
未支持字段: 需要人工确认"""

        row = parse_text_plans(text)[0]

        self.assertEqual(row["send_content"], "第一行")
        self.assertIn("未自动化字段“未支持字段”", row["__warnings"])


if __name__ == "__main__":
    unittest.main()
