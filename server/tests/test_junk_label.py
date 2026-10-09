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


class TestQueryLikeWords:
    """P2-12 Odoo 噪声：onchange/web_read/mail thread 轮询/render 资产
    是表单联动与聊天轮询 RPC（POST 形态但无业务语义）——查询型词表
    须覆盖，否则 from-run 反哺与 generate_assertions 都生成噪声断言。"""

    def test_odoo_noise_templates(self):
        from app.learning.outcome import _QUERY_LIKE_KEYS
        for t in ("/web/dataset/call_kw/sale.order/onchange",
                  "/web/dataset/call_kw/sale.order/web_read",
                  "/mail/thread/data", "/mail/thread/messages",
                  "/web/dataset/call_kw/ir.ui.view/render_public_asset",
                  "/web/dataset/call_kw/account.move/get_views"):
            assert any(k in t for k in _QUERY_LIKE_KEYS), t

    def test_real_write_not_matched(self):
        from app.learning.outcome import _QUERY_LIKE_KEYS
        for t in ("/web/dataset/call_kw/sale.order/web_save",
                  "/web/dataset/call_kw/res.partner/web_save",
                  "/web/dataset/call_button"):
            assert not any(k in t for k in _QUERY_LIKE_KEYS), t
