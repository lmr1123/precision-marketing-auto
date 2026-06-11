import unittest

from ui_app.text_plan_parser import TextPlanParseError, parse_text_plans


class TextPlanParserTests(unittest.TestCase):
    def test_parse_single_plan_with_multiline_content(self):
        plans = parse_text_plans(
            """
            计划名称: 618会员通1对1-广佛
            发送渠道: 会员通-发客户消息
            营销主题: 其他、26年6月会员活动
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            主消费营运区: 广佛省区
            执行员工: 广佛省区
            推送内容: |
              第一行
              第二行
            1对1-小程序链接: pages/activity/index?id=618
            """
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["name"], "618会员通1对1-广佛")
        self.assertEqual(plans[0]["main_operating_area"], "广佛省区")
        self.assertEqual(plans[0]["push_content"], "第一行\n第二行")
        self.assertEqual(plans[0]["msg_mini_program_page_path"], "pages/activity/index?id=618")

    def test_parse_multiple_blocks(self):
        plans = parse_text_plans(
            """
            计划名称: A
            发送渠道: 短信
            营销主题: 其他
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            推送内容: A内容
            ---
            计划名称: B
            发送渠道: 会员通-发客户朋友圈
            营销主题: 其他
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            推送内容: B内容
            """
        )

        self.assertEqual([p["name"] for p in plans], ["A", "B"])

    def test_parse_target_field_aliases(self):
        plans = parse_text_plans(
            """
            计划名称: A
            发送渠道: 短信
            营销主题: 其他、26年6月会员活动
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            目标商品编码: 1001、1002
            已领或已使用券规则ID: 1-2001、1-2002
            推送内容: A内容
            """
        )

        self.assertEqual(plans[0]["purchase_target_product_code"], "1001、1002")
        self.assertEqual(plans[0]["coupon_ids_sheet_ref"], "1-2001、1-2002")

    def test_parse_combo_plan_with_separate_channel_content(self):
        plans = parse_text_plans(
            """
            计划名称: 短信加客户消息
            发送渠道: 短信、会员通-发客户消息
            营销主题: 其他、新店营销
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            短信内容: 【大参林】新店福利上线，欢迎到店咨询
            发送内容: |
              会员福利活动上线😁
              欢迎进店咨询健康服务与优惠信息
            """
        )

        self.assertEqual(plans[0]["sms_content"], "【大参林】新店福利上线，欢迎到店咨询")
        self.assertEqual(
            plans[0]["send_content"],
            "会员福利活动上线😁\n欢迎进店咨询健康服务与优惠信息",
        )

    def test_parse_smart_phone_activity_intro(self):
        plans = parse_text_plans(
            """
            计划名称: 智能电话测试
            发送渠道: 智能电话
            营销主题: 其他、新店营销
            计划开始时间: 2026-06-01 09:00:00
            计划结束时间: 2026-06-08 23:00:00
            发送时间: 2026-06-02 10:00:00
            主消费营运区: 广佛省区
            主消费门店文件路径: /tmp/stores.xlsx
            活动介绍: |
              您好，我是大参林药店员工。
              来电是想通知您门店会员福利活动上线。
            """
        )

        self.assertEqual(plans[0]["channels"], "智能电话")
        self.assertEqual(plans[0]["main_store_file_path"], "/tmp/stores.xlsx")
        self.assertIn("门店会员福利活动", plans[0]["activity_intro"])

    def test_reject_smart_phone_combo_channel(self):
        with self.assertRaises(TextPlanParseError) as ctx:
            parse_text_plans(
                """
                计划名称: 智能电话组合
                发送渠道: 智能电话、短信
                营销主题: 其他
                计划开始时间: 2026-06-01
                计划结束时间: 2026-06-08
                发送时间: 2026-06-02 10:00
                活动介绍: 测试内容
                """
            )

        self.assertIn("智能电话当前仅支持单渠道", str(ctx.exception))

    def test_parse_community_distribution_mode_aliases(self):
        plans = parse_text_plans(
            """
            计划名称: 社群导入门店
            发送渠道: 会员通-发送社群
            营销主题: 其他
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            分配方式: 选中门店
            发送内容: 社群内容
            """
        )

        self.assertEqual(plans[0]["distribution_mode"], "导入门店")

    def test_reject_invalid_community_distribution_mode(self):
        with self.assertRaises(TextPlanParseError) as ctx:
            parse_text_plans(
                """
                计划名称: 社群错误
                发送渠道: 会员通-发送社群
                营销主题: 其他
                计划开始时间: 2026-06-01
                计划结束时间: 2026-06-10
                发送时间: 2026-06-02 09:00
                社群任务分配方式: 指定门店分配
                发送内容: 社群内容
                """
            )

        self.assertIn("社群任务分配方式只支持", str(ctx.exception))

    def test_unknown_fields_become_review_warnings(self):
        plans = parse_text_plans(
            """
            计划名称: 未覆盖字段测试
            发送渠道: 短信
            营销主题: 其他
            计划开始时间: 2026-06-01
            计划结束时间: 2026-06-10
            发送时间: 2026-06-02 09:00
            暂未实现字段: 需要人工看
            复杂暂未实现字段: |
              第一行
              第二行
            短信内容: 【大参林】测试内容
            """
        )

        self.assertIn("未自动化字段“暂未实现字段”", plans[0]["__warnings"])
        self.assertIn("未自动化字段“复杂暂未实现字段”", plans[0]["__warnings"])
        self.assertEqual(plans[0]["sms_content"], "【大参林】测试内容")

    def test_required_field_error(self):
        with self.assertRaises(TextPlanParseError) as ctx:
            parse_text_plans(
                """
                计划名称: A
                发送渠道: 短信
                """
            )
        self.assertIn("缺少必填字段", str(ctx.exception))

    def test_content_field_error(self):
        with self.assertRaises(TextPlanParseError) as ctx:
            parse_text_plans(
                """
                计划名称: A
                发送渠道: 短信
                营销主题: 其他
                计划开始时间: 2026-06-01
                计划结束时间: 2026-06-10
                发送时间: 2026-06-02 09:00
                """
            )
        self.assertIn("缺少内容字段", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
