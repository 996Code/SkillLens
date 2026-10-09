"""P1-6/8 自愈提案垃圾防线（95 积压实证）：LLM 网关配额错误消息/
模板占位符/幻觉指令词会流进 proposed 池（`*操作Token额度不足！`×10、
`SAL-ORD-.YYYY.-`×12、`Check again`×9 等）——确定性词表在生成时拦截，
不依赖人工 reject（防再生）。"""
import pytest

from app.replay.repair import is_junk_label


class TestJunkLabel:
    def test_gateway_quota_error(self):
        """LLM 网关配额错误消息（10-06 污染源头形态）。"""
        assert is_junk_label("*操作Token额度不足！")
        assert is_junk_label("Token额度不足")

    def test_template_placeholder(self):
        """模板占位符（ERPNext 订单号 .YYYY. 形态×12）。"""
        assert is_junk_label("SAL-ORD-.YYYY.-")

    def test_model_instruction(self):
        """模型幻觉指令（非页面元素名）×13。"""
        assert is_junk_label("Check again")
        assert is_junk_label("未找到匹配元素")
        assert is_junk_label("开始执行")
        assert is_junk_label("[继续]")

    def test_empty(self):
        assert is_junk_label("")
        assert is_junk_label("   ")

    def test_legit_labels_pass(self):
        """真实 UI 元素名不误杀（合法同义改名是自愈的正路）。"""
        for ok in ("Save", "New", "Customer", "查询", "新建", "编辑",
                   "保存数据库", "保存草稿", "登 录", "准客户", "提交表单"):
            assert not is_junk_label(ok), ok
