"""P2 交互画像指纹：从系统页面 DOM/URL 指纹识别组件库与交互家族——
生成 InteractionProfile 草稿（新系统接入零手写画像）。

识别维度（全部来自 7 系统实战沉淀的铁证模式）：
- ui_library: ant-design / element-plus / generic（CSS 类名指纹）
- framework: frappe（data-fieldname/data-label 特征）/ generic
- 表单定位器序：frappe=data-fieldname 优先；zentao 类裸表单=name 优先
"""
from __future__ import annotations

import re

from app.adapters.manifest import (
    DropdownProfile,
    FormFillProfile,
    InteractionProfile,
    ModalSubmitProfile,
    RowActionProfile,
    RouteGuardProfile,
)


def fingerprint_page(dom: str, url: str = "") -> dict:
    """页面 DOM+URL → 指纹（ui_library/framework/特征类计数）。"""
    fp: dict = {"url": url}
    if re.search(r"ant-(modal|btn|dropdown|form|table)", dom):
        fp["ui_library"] = "ant-design"
    elif re.search(r"el-(dropdown|message-box|form|table)", dom):
        fp["ui_library"] = "element-plus"
    else:
        fp["ui_library"] = "generic"
    if "data-fieldname" in dom or "data-label=" in dom:
        fp["framework"] = "frappe"
    else:
        fp["framework"] = "generic"
    fp["has_table_rows"] = bool(re.search(r"<tr|table-row", dom))
    fp["has_name_inputs"] = bool(re.search(r"<input[^>]+name=", dom))
    return fp


def detect_profile(fp: dict) -> InteractionProfile:
    """指纹 → 画像草稿（每条规则都源自 7 系统实战铁证）。"""
    lib = fp.get("ui_library", "generic")
    framework = fp.get("framework", "generic")

    if lib == "ant-design":
        dropdown = DropdownProfile(
            engine="ant-design",
            menu_item_match="includes",   # 图标文本混入（JeecG 270 铁证）
            menu_item_click="trusted",    # React mousedown 委托
            mount_wait_ms=400)
        modal = ModalSubmitProfile(
            selector=".ant-modal-content, .ant-drawer-content",
            button_regex=r"保存|确定|提\s*交|同步",
            pick="last_visible",          # footer 多同名隐藏副本
            render_wait_ms=800)
        fill = FormFillProfile(
            framework="generic",
            field_locators=["placeholder", "form-item-label", "name-attr"],
            same_label_priority="modal_first")
    elif lib == "element-plus":
        dropdown = DropdownProfile(
            engine="element-plus",
            menu_item_match="includes",
            menu_item_click="trusted",    # el-dropdown trigger:hover 流入
            mount_wait_ms=500)
        modal = ModalSubmitProfile(
            selector=".el-message-box, .ant-modal-content",
            button_regex=r"确\s*定|保存|提\s*交",
            pick="first_visible",
            render_wait_ms=600)
        fill = FormFillProfile(
            framework="generic",
            field_locators=["placeholder", "form-item-label", "name-attr"],
            same_label_priority="modal_first")
    else:
        dropdown = DropdownProfile()
        modal = ModalSubmitProfile(
            selector=".modal, .o_modal, [role=dialog]",
            button_regex=r"保存|确定|Save|Confirm|OK",
            pick="first_visible")
        fill = FormFillProfile(
            framework=framework,
            field_locators=(["data-fieldname", "placeholder", "name-attr"]
                            if framework == "frappe"
                            else (["name-attr", "placeholder", "form-item-label"]
                                  if fp.get("has_name_inputs")
                                  else ["placeholder", "name-attr",
                                        "form-item-label"])),
            same_label_priority=("modal_first"
                                 if framework == "frappe" else "first"))

    return InteractionProfile(
        dropdown=dropdown,
        modal_submit=modal,
        form_fill=fill,
        row_action=RowActionProfile(
            anchor_match="insensitive" if lib == "ant-design" else "sensitive",
            scroll_into_view=bool(fp.get("has_table_rows"))),
        route_guard=RouteGuardProfile(
            async_set_route=(framework == "frappe"),
            normalize_new_suffix=(framework == "frappe")))
