import argparse
import json
import math
import re
from pathlib import Path

from principle_checks import validate_principles


COLLECTIONS = ("chapters", "sources", "rules", "features", "acceptance", "questions", "decisions", "diagrams", "mockups", "goals", "contracts", "checks", "changes")
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
FEATURE_STATUSES = {"confirmed", "proposed", "pending", "excluded"}
RULE_STATUSES = {"confirmed", "proposed", "pending", "superseded"}
DELIVERY_STATUSES = {
    "engineering_review": {"pending", "reviewed"},
    "implementation": {"not_started", "in_progress", "implemented"},
    "testing": {"not_run", "in_progress", "passed", "failed"},
    "deployment": {"not_deployed", "deployed", "rolled_back"},
}
CHAPTER_KINDS = {"summary", "problem", "scope", "roles", "architecture", "journey", "data", "features", "interaction", "quality", "governance", "general"}
DEFAULT_KINDS = dict(zip(("C" + str(index).zfill(2) for index in range(1, 12)), ("summary", "problem", "scope", "roles", "architecture", "journey", "data", "features", "interaction", "quality", "governance")))


def _validate(model, handoff=False):
    errors, warnings = [], []

    def error(message):
        errors.append(message)

    def warning(message):
        warnings.append(message)

    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def strings(value, label):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            error(label + " 必須是文字陣列")
            return []
        if len(value) != len(set(value)):
            error(label + " 含重複值")
        return value

    if not isinstance(model, dict):
        return {"structure": "failed", "errors": ["頂層必須是物件"], "warnings": []}
    if model.get("schema_version") != "1.2":
        error("schema_version 必須是 1.2；舊資料需明確補五層、目標與確認範圍，不默認遷移。")
    project = model.get("project", {})
    if not isinstance(project, dict):
        error("project 必須是物件")
        project = {}
    for key in ("id", "title", "summary", "date", "profile", "disclaimer"):
        if not isinstance(project.get(key), str) or not project.get(key).strip():
            error("project." + key + " 不可空白")
    for key in ("mvp", "out_of_scope", "required_review_roles"):
        strings(project.get(key), "project." + key)
    required_types = project.get("required_diagram_types", ["architecture", "flow", "sequence"])
    strings(required_types, "project.required_diagram_types")
    if isinstance(required_types, list) and any(item not in {"architecture", "flow", "sequence", "state"} for item in required_types):
        error("required_diagram_types 非法")
    indexes = {}
    all_ids = set()
    for collection in COLLECTIONS:
        items = model.get(collection, []) if collection == "mockups" else model.get(collection)
        indexes[collection] = {}
        if not isinstance(items, list):
            error(collection + " 必須是陣列")
            continue
        for item in items:
            if not isinstance(item, dict):
                error(collection + " 的項目必須是物件")
                continue
            identifier = item.get("id")
            if not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier):
                error(collection + " 有不安全或空白ID")
                continue
            if identifier in all_ids:
                error("重複ID：" + identifier)
            all_ids.add(identifier)
            indexes[collection][identifier] = item

    def refs(item, key, collection):
        label = item.get("id", "?") + "." + key
        values = strings(item.get(key), label)
        for identifier in values:
            if identifier not in indexes[collection]:
                error(label + " 找不到 " + identifier)
        return values

    def text_fields(item, keys, allow_empty=False):
        for key in keys:
            value = item.get(key)
            if not isinstance(value, str) or (not allow_empty and not value.strip()):
                error(item.get("id", "?") + "." + key + " 必須是" + ("文字" if allow_empty else "非空文字"))

    def real_sources(source_ids):
        return bool(source_ids) and any(indexes["sources"].get(identifier, {}).get("kind") in {"document", "user_answer", "code_observation"} for identifier in source_ids)

    for source in indexes["sources"].values():
        text_fields(source, ("title", "locator"))
        if source.get("kind") not in {"document", "user_answer", "code_observation", "html_mockup", "example"} or not isinstance(source.get("authoritative"), bool):
            error(source["id"] + " 來源類型或權威欄位非法")
        if source.get("kind") == "example" and source.get("authoritative"):
            error(source["id"] + " 教學來源不能標為權威")

    for decision in indexes["decisions"].values():
        text_fields(decision, ("title", "answer", "owner", "date"))
        refs(decision, "source_refs", "sources")
        scopes = strings(decision.get("scope_ids"), decision["id"] + ".scope_ids")
        for identifier in scopes:
            if not any(identifier in indexes[collection] for collection in ("features", "rules", "goals", "contracts", "checks", "changes", "questions")):
                error(decision["id"] + " 未知決策範圍：" + identifier)

    for collection, statuses in (("features", FEATURE_STATUSES), ("rules", RULE_STATUSES)):
        for item in indexes[collection].values():
            text_fields(item, ("title",))
            if item.get("status") not in statuses:
                error(item["id"] + " 狀態非法")
            source_ids = refs(item, "source_refs", "sources")
            if not source_ids:
                warning(item["id"] + " 缺少來源")
            if item.get("status") == "confirmed":
                decision = indexes["decisions"].get(item.get("decision_id"))
                if not decision or item["id"] not in decision.get("scope_ids", []) or not real_sources(decision.get("source_refs", [])):
                    error(item["id"] + " 已確認需有涵蓋自身的決策及非教學來源")
            elif item.get("status") in {"proposed", "pending"}:
                warning(item["id"] + " 尚未核准")
            if collection == "rules":
                text_fields(item, ("statement", "kind", "stage"))
                refs(item, "feature_ids", "features")
            else:
                text_fields(item, ("story", "priority", "success"))
                if "delivery" in item:
                    for key, allowed_delivery_statuses in DELIVERY_STATUSES.items():
                        if item["delivery"].get(key) not in allowed_delivery_statuses:
                            error(item["id"] + ".delivery." + key + " 狀態非法")
                    for key, initial in (("engineering_review", "pending"), ("implementation", "not_started"), ("testing", "not_run"), ("deployment", "not_deployed")):
                        if item["delivery"].get(key) != initial and not item["delivery"].get(key + "_evidence"):
                            error(item["id"] + ".delivery." + key + " 狀態變更需獨立證據")
                for key in ("roles", "preconditions", "inputs", "steps", "errors", "recovery", "screen_ids"):
                    strings(item.get(key), item["id"] + "." + key)
                for key, target in (("rule_ids", "rules"), ("diagram_ids", "diagrams"), ("acceptance_ids", "acceptance")):
                    refs(item, key, target)
                if "mockup_ids" in item:
                    refs(item, "mockup_ids", "mockups")

    for item in indexes["acceptance"].values():
        text_fields(item, ("category", "given", "when", "then"))
        feature = indexes["features"].get(item.get("feature_id"))
        if not feature or item["id"] not in feature.get("acceptance_ids", []):
            error(item["id"] + " AC／FR引用不一致")
        if item.get("execution") not in {"not_run", "passed", "failed"}:
            error(item["id"] + " execution 非法")
        if item.get("execution") in {"passed", "failed"} and not item.get("evidence"):
            error(item["id"] + " 執行結果需證據")

    for question in indexes["questions"].values():
        text_fields(question, ("title", "context", "owner"))
        strings(question.get("options"), question["id"] + ".options")
        refs(question, "blocking_feature_ids", "features")
        source_ids = refs(question, "source_refs", "sources")
        if question.get("status") not in {"open", "answered"}:
            error(question["id"] + " 問題狀態非法")
        if question.get("status") == "answered" and (not question.get("answer") or not real_sources(source_ids)):
            error(question["id"] + " 已回答需結論及非教學來源")

    for chapter in indexes["chapters"].values():
        text_fields(chapter, ("title", "summary"), allow_empty=True)
        if chapter.get("kind", DEFAULT_KINDS.get(chapter["id"], "general")) not in CHAPTER_KINDS:
            error(chapter["id"] + " 章節kind非法")
        strings(chapter.get("paragraphs"), chapter["id"] + ".paragraphs")
        for key, target in (("feature_ids", "features"), ("rule_ids", "rules"), ("diagram_ids", "diagrams")):
            refs(chapter, key, target)
        if not chapter.get("paragraphs") and not any(chapter.get(key) for key in ("feature_ids", "rule_ids", "diagram_ids")):
            warning(chapter["id"] + " 章節待填")

    for diagram in indexes["diagrams"].values():
        text_fields(diagram, ("title", "purpose"))
        for key in ("reading_notes", "legend"):
            strings(diagram.get(key), diagram["id"] + "." + key)
        if diagram.get("orientation", "portrait") not in {"portrait", "landscape"}:
            error(diagram["id"] + " 插圖頁面方向非法")
        for key in ("font_size", "label_font_size"):
            if key in diagram and (not finite(diagram[key]) or not 10 <= diagram[key] <= 40):
                error(diagram["id"] + " 圖表字級非法")
        if diagram.get("type") not in {"architecture", "flow", "sequence", "state"}:
            error(diagram["id"] + " 圖類型非法")
        chapter = indexes["chapters"].get(diagram.get("chapter_id"))
        if not chapter or diagram["id"] not in chapter.get("diagram_ids", []):
            error(diagram["id"] + " 圖／章節引用不一致")
        refs(diagram, "feature_ids", "features")
        refs(diagram, "question_ids", "questions")
        width, height = diagram.get("width"), diagram.get("height")
        if not finite(width) or not finite(height) or width <= 0 or height <= 0:
            error(diagram["id"] + " 尺寸非法")
            continue
        nodes, local_ids = {}, set()
        for node in diagram.get("nodes", []):
            identifier = node.get("id")
            if not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier) or identifier in local_ids:
                error(diagram["id"] + " 節點ID非法或重複")
                continue
            local_ids.add(identifier)
            nodes[identifier] = node
            text_fields(node, ("label",))
            if node.get("shape") not in {"rect", "diamond", "text", "group"} or node.get("tone") not in {"blue", "green", "orange", "gray", "navy"}:
                error(diagram["id"] + "/" + identifier + " 節點樣式非法")
            if not all(finite(node.get(key)) for key in ("x", "y", "width", "height")):
                error(diagram["id"] + "/" + identifier + " 幾何非法")
            elif node["x"] < 0 or node["y"] < 0 or node["width"] <= 0 or node["height"] <= 0 or node["x"] + node["width"] > width or node["y"] + node["height"] > height:
                error(diagram["id"] + "/" + identifier + " 節點超出圖邊界")
        for edge in diagram.get("edges", []):
            identifier = edge.get("id")
            if not isinstance(identifier, str) or not SAFE_ID.fullmatch(identifier) or identifier in local_ids:
                error(diagram["id"] + " 連線ID非法或重複")
            local_ids.add(identifier)
            points = edge.get("points", [])
            if edge.get("style") not in {"flow", "return", "lifeline"}:
                error(diagram["id"] + " 連線樣式非法")
            if not isinstance(points, list) or len(points) < 2 or any(not isinstance(point, dict) or not finite(point.get("x")) or not finite(point.get("y")) or not 0 <= point["x"] <= width or not 0 <= point["y"] <= height for point in points):
                error(diagram["id"] + " 連線座標非法")
                continue
            if bool(edge.get("source")) != bool(edge.get("target")):
                error(diagram["id"] + " 連線須同時指定起訖節點")
            for key, point in (("source", points[0]), ("target", points[-1])):
                if edge.get(key):
                    node = nodes.get(edge[key])
                    if not node:
                        error(diagram["id"] + " 連線引用未知節點")
                    elif all(finite(node.get(item)) for item in ("x", "y", "width", "height")) and not (node["x"] <= point["x"] <= node["x"] + node["width"] and node["y"] <= point["y"] <= node["y"] + node["height"]):
                        error(diagram["id"] + " 連線起訖不在指定節點")
            if edge.get("label") and (not finite(edge.get("label_x")) or not finite(edge.get("label_y")) or not 0 <= edge["label_x"] <= width or not 0 <= edge["label_y"] <= height):
                error(diagram["id"] + " 連線標籤座標非法")

    for mockup in indexes["mockups"].values():
        text_fields(mockup, ("title", "version", "locator"))
        if mockup.get("source_ref") not in indexes["sources"] or indexes["sources"].get(mockup.get("source_ref"), {}).get("kind") != "html_mockup":
            error(mockup["id"] + " Mockup需引用html_mockup來源")
        if mockup.get("availability") not in {"read", "unavailable"} or mockup.get("confirmation") not in {"observed", "author_confirmed"}:
            error(mockup["id"] + " 判讀／確認狀態非法")
        if mockup.get("availability") == "unavailable":
            warning(mockup["id"] + " 未取得，只阻擋依賴它且尚未確認的事項")
        refs(mockup, "feature_ids", "features")
        refs(mockup, "confirmed_decision_ids", "decisions")
        for key in ("screen_ids", "observations", "limitations", "confirmed_scope"):
            strings(mockup.get(key), mockup["id"] + "." + key)
        if mockup.get("confirmation") == "author_confirmed" and (
            not mockup.get("confirmed_by") or not mockup.get("confirmed_on") or not mockup.get("confirmation_evidence") or not mockup.get("confirmed_scope")
        ):
            error(mockup["id"] + " 已驗證需責任人、日期、證據與具體範圍")
        if mockup.get("confirmed_decision_ids") and mockup.get("confirmation") != "author_confirmed":
            error(mockup["id"] + " 觀察不能標成核准決策")
        if mockup.get("availability") != "read" and mockup.get("confirmed_decision_ids"):
            error(mockup["id"] + " 未取得的Mockup不能以畫面觀察支撐核准")

    for feature in indexes["features"].values():
        for key, target, reverse in (("rule_ids", "rules", "feature_ids"), ("diagram_ids", "diagrams", "feature_ids"), ("mockup_ids", "mockups", "feature_ids")):
            for identifier in feature.get(key, []):
                if identifier in indexes[target] and feature["id"] not in indexes[target][identifier].get(reverse, []):
                    error(feature["id"] + " 雙向引用不一致：" + identifier)
        for identifier in feature.get("acceptance_ids", []):
            if identifier in indexes["acceptance"] and indexes["acceptance"][identifier].get("feature_id") != feature["id"]:
                error(feature["id"] + " AC歸屬不一致")
    for collection, key in (("rules", "rule_ids"), ("diagrams", "diagram_ids"), ("mockups", "mockup_ids")):
        for item in indexes[collection].values():
            for feature_id in item.get("feature_ids", []):
                if feature_id in indexes["features"] and item["id"] not in indexes["features"][feature_id].get(key, []):
                    error(item["id"] + " 反向引用不一致：" + feature_id)
    for chapter in indexes["chapters"].values():
        for identifier in chapter.get("diagram_ids", []):
            if identifier in indexes["diagrams"] and indexes["diagrams"][identifier].get("chapter_id") != chapter["id"]:
                error(chapter["id"] + " 圖歸屬不一致")

    if not isinstance(model.get("mappings"), list):
        error("mappings 必須是陣列")
    else:
        mapping_ids = set()
        for item in model["mappings"]:
            if item.get("source_ref") not in indexes["sources"] or not item.get("original_id"):
                error("原章節映射缺少來源或原ID")
            refs(item, "feature_ids", "features")
            identity = (item.get("source_ref"), item.get("original_id"))
            if identity in mapping_ids:
                error("重複原章節映射")
            mapping_ids.add(identity)
    reviews = model.get("reviews")
    if not isinstance(reviews, list):
        error("reviews 必須是陣列")
        reviews = []
    reviewed_roles = set()
    for review in reviews:
        if not isinstance(review.get("role"), str) or review.get("role") in reviewed_roles or review.get("status") not in {"pending", "approved"}:
            error("審閱角色重複或狀態非法")
        reviewed_roles.add(review.get("role"))
        source_ids = refs(review, "source_refs", "sources")
        if review.get("status") == "approved" and (not review.get("evidence") or not real_sources(source_ids)):
            error("已核准審閱需證據及非教學來源")

    included = [item for item in indexes["features"].values() if item.get("status") != "excluded"]
    core_ids = project.get("core_feature_ids", [item["id"] for item in included])
    strings(core_ids, "project.core_feature_ids")
    for identifier in core_ids:
        if identifier not in {item["id"] for item in included}:
            error("核心功能不在本期：" + identifier)
    if (set(core_ids) != {item["id"] for item in included} or not {"architecture", "flow", "sequence"}.issubset(required_types)) and not project.get("coverage_rationale"):
        error("裁減核心圖覆蓋或圖類型需附coverage_rationale，並由人工審閱確認")
    chapter_kinds = {chapter.get("kind", DEFAULT_KINDS.get(chapter["id"], "general")) for chapter in indexes["chapters"].values()}
    for collection, chapter_kind in (("sources", "summary"), ("acceptance", "quality"), ("reviews", "quality"), ("questions", "governance"), ("decisions", "governance"), ("mappings", "governance"), ("mockups", "features")):
        if model.get(collection) and chapter_kind not in chapter_kinds:
            error(collection + " 需要可呈現的 " + chapter_kind + " 章節（可自訂ID並指定kind）")
    for collection, key in (("features", "feature_ids"), ("rules", "rule_ids"), ("diagrams", "diagram_ids")):
        visible_ids = {identifier for chapter in indexes["chapters"].values() for identifier in chapter.get(key, [])}
        for identifier in indexes[collection]:
            if identifier not in visible_ids:
                error(identifier + " 尚未映射到正文可讀章節")
    blockers = validate_principles(model, indexes, error, warning)
    if not included:
        warning("尚未定義本期功能")
        blockers.append("缺少本期功能")
    for feature in included:
        if feature.get("status") != "confirmed":
            blockers.append(feature["id"] + " 尚未確認")
        if any(indexes["rules"].get(identifier, {}).get("status") != "confirmed" for identifier in feature.get("rule_ids", [])):
            blockers.append(feature["id"] + " 共用規則尚未確認")
        categories = {indexes["acceptance"].get(identifier, {}).get("category") for identifier in feature.get("acceptance_ids", [])}
        if not {"normal", "rejection"}.issubset(categories):
            blockers.append(feature["id"] + " 缺少正常／拒絕AC")
        if feature["id"] in core_ids and (not feature.get("diagram_ids")):
            blockers.append(feature["id"] + " 缺少核心圖覆蓋")
    for question in indexes["questions"].values():
        if question.get("status") == "open" and any(identifier in {item["id"] for item in included} for identifier in question.get("blocking_feature_ids", [])):
            blockers.append(question["id"] + " 本期阻擋問題未回答")
    types = {item.get("type") for item in indexes["diagrams"].values()}
    for diagram_type in required_types:
        if diagram_type not in types:
            blockers.append("缺少所需圖類型：" + diagram_type)
    for role in project.get("required_review_roles", []):
        if not any(item.get("role") == role and item.get("status") == "approved" for item in reviews):
            blockers.append(role + " 未人工核准")
    if handoff:
        errors.extend("開發交付：" + item for item in blockers)
    return {
        "structure": "passed" if not errors else "failed",
        "mode": "handoff" if handoff else "draft",
        "handoff_candidates": "blocked" if blockers or errors else "eligible_for_human_handoff",
        "handoff_blockers": blockers,
        "docx_render_review": {"status": "not_run"},
        "drawio_gui_review": {"status": "not_run"},
        "errors": errors,
        "warnings": warnings,
        "note": "結構檢查不驗證核准證據真實性；文件與Mockup判讀不等於產品UAT。",
    }


def validate(model, handoff=False):
    try:
        return _validate(model, handoff)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exception:
        return {
            "structure": "failed", "mode": "handoff" if handoff else "draft",
            "handoff_candidates": "blocked", "handoff_blockers": ["資料型別非法"],
            "docx_render_review": {"status": "not_run"}, "drawio_gui_review": {"status": "not_run"},
            "errors": ["資料型別非法：" + str(exception)], "warnings": [],
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        model = json.loads(args.input.read_text(encoding="utf-8"))
        report = validate(model, args.handoff)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exception:
        report = {"structure": "failed", "errors": [str(exception)], "warnings": []}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["structure"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
