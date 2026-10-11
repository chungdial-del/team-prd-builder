from spec_tests import finite_number, pm_approved


def validate_principles(model, indexes, error, warning):
    blockers = []
    levels = model.get("explanation_levels")
    if not isinstance(levels, list) or len(levels) != 5 or {entry.get("level") for entry in levels if isinstance(entry, dict)} != {1, 2, 3, 4, 5}:
        error("explanation_levels必須明確列出L1至L5。")
    else:
        seen_chapters = set()
        for level in levels:
            if not all(isinstance(level.get(key), str) and level[key].strip() for key in ("title", "reader", "note")):
                error("五層解釋需標題、讀者及閱讀目的。")
            for identifier in level.get("chapter_ids", []):
                if identifier not in indexes["chapters"] or identifier in seen_chapters:
                    error("五層章節定位不明或重複：" + str(identifier))
                seen_chapters.add(identifier)
            if not level.get("chapter_ids"):
                error("每層必須定位到正文章節；缺口也需有位置。")
        if seen_chapters != set(indexes["chapters"]):
            error("所有正文章節都需五層定位。")
        order = {identifier: entry["level"] for entry in levels for identifier in entry.get("chapter_ids", [])}
        depths = [order.get(entry["id"], 0) for entry in model["chapters"]]
        if depths != sorted(depths):
            error("正文需由L1至L5排序；章節ID保持不變。")

    def references(item, key, collection):
        values = item.get(key)
        if not isinstance(values, list) or any(not isinstance(identifier, str) or identifier not in indexes[collection] for identifier in values):
            error(item["id"] + "." + key + "引用非法。")
            return []
        return values

    for collection in ("features", "rules", "goals", "contracts", "checks"):
        for item in indexes[collection].values():
            if item.get("status") == "confirmed" and not pm_approved(item, model):
                error(item["id"] + " 已確認需PM角色、核准範圍及正式核准來源。")
    for question in indexes["questions"].values():
        if question.get("status") == "answered" and not pm_approved(question, model):
            error(question["id"] + " 不確定事項的答案需PM決策。")
    for collection in ("goals", "contracts", "checks"):
        for item in indexes[collection].values():
            if item.get("status") not in {"confirmed", "proposed", "pending"} or not isinstance(item.get("title"), str) or not item["title"].strip():
                error(item["id"] + " 驗證項目標題或狀態非法。")
            references(item, "source_refs", "sources")
    for goal in indexes["goals"].values():
        references(goal, "feature_ids", "features")
        if not isinstance(goal.get("statement"), str) or not goal["statement"].strip():
            error(goal["id"] + " 目標不可空白。")
    for contract in indexes["contracts"].values():
        references(contract, "feature_ids", "features")
        references(contract, "rule_ids", "rules")
        goal = indexes["goals"].get(contract.get("goal_id"), {})
        if not goal or not set(contract.get("feature_ids", [])).issubset(goal.get("feature_ids", [])):
            error(contract["id"] + " 契約需對應目標與其功能。")
        spec = contract.get("spec", {})
        if contract.get("kind") == "number_range":
            if not isinstance(spec.get("field"), str) or not spec["field"].strip() or not finite_number(spec.get("minimum")) or not finite_number(spec.get("maximum")) or spec["minimum"] > spec["maximum"]:
                error(contract["id"] + " 數值契約需明確欄位及有限的上下界。")
        elif contract.get("kind") == "transition":
            if any(not isinstance(spec.get(key), list) or not spec[key] or any(not isinstance(value, str) or not value for value in spec[key]) or len(set(spec[key])) != len(spec[key]) for key in ("states", "events")):
                error(contract["id"] + " 狀態與事件清單非法。")
            seen = set()
            for transition in spec.get("transitions", []):
                pair = (transition.get("from"), transition.get("event"))
                if pair in seen or transition.get("from") not in spec.get("states", []) or transition.get("to") not in spec.get("states", []) or transition.get("event") not in spec.get("events", []):
                    error(contract["id"] + " 轉移非法或相同事件有多個結果。")
                seen.add(pair)
        else:
            error(contract["id"] + " 未支援的契約不可默認實作。")
    for case in indexes["checks"].values():
        contract = indexes["contracts"].get(case.get("contract_id"), {})
        acceptance_ids = references(case, "acceptance_ids", "acceptance")
        if not contract or case.get("goal_id") != contract.get("goal_id") or case.get("feature_id") not in contract.get("feature_ids", []):
            error(case["id"] + " 測試的目標、契約或功能不一致。")
        if not acceptance_ids or any(indexes["acceptance"][identifier].get("feature_id") != case.get("feature_id") for identifier in acceptance_ids):
            error(case["id"] + " 測試需對應同一功能的AC。")
        if not isinstance(case.get("input"), dict) or not isinstance(case.get("expected"), dict):
            error(case["id"] + " 輸入與獨立預期必須是JSON物件。")
        else:
            expected = case["expected"]
            if contract.get("kind") == "number_range" and (set(expected) != {"valid"} or not isinstance(expected.get("valid"), bool)):
                error(case["id"] + " 數值契約預期需明確布林valid。")
            if contract.get("kind") == "transition" and (set(expected) != {"allowed", "state"} or not isinstance(expected.get("allowed"), bool) or expected.get("state") not in contract.get("spec", {}).get("states", [])):
                error(case["id"] + " 狀態契約預期需布林allowed及已定義狀態。")
    for change in indexes["changes"].values():
        if change.get("kind") not in {"editorial", "addition", "removal", "semantic"} or change.get("status") not in {"recorded", "proposed", "approved", "rejected"}:
            error(change["id"] + " 變更類型或狀態非法。")
        for key in ("before", "after", "reason"):
            if not isinstance(change.get(key), str):
                error(change["id"] + " 變更需原文、提案與理由。")
        scope = change.get("scope_ids", [])
        if not scope or any(not any(identifier in collection for collection in indexes.values()) for identifier in scope):
            error(change["id"] + " 變更範圍未知。")
        if change.get("kind") != "editorial":
            if change.get("status") == "recorded":
                error(change["id"] + " 語意變更不得僅記錄後默認套用。")
            elif change.get("status") in {"approved", "rejected"} and not pm_approved(change, model):
                error(change["id"] + " 變更結論需PM決策。")
            elif change.get("status") == "proposed":
                blockers.append(change["id"] + " 變更待PM確認；未套用。")
    included = {identifier for identifier, item in indexes["features"].items() if item.get("status") != "excluded"}
    covered = {identifier for goal in indexes["goals"].values() for identifier in goal.get("feature_ids", [])}
    for identifier in included - covered:
        blockers.append(identifier + " 缺少目標追溯。")
    for goal in indexes["goals"].values():
        if goal.get("status") != "confirmed":
            blockers.append(goal["id"] + " 目標待PM確認。")
        if not any(case.get("goal_id") == goal["id"] for case in indexes["checks"].values()):
            blockers.append(goal["id"] + " 沒有可執行案例；需列缺口。")
    for collection in ("contracts", "checks"):
        for item in indexes[collection].values():
            if item.get("status") != "confirmed":
                blockers.append(item["id"] + " 規則或測試預期待PM確認。")
    if not indexes["checks"]:
        warning("尚未建立規格測試；不得聲稱已完成機器驗證。")
    return blockers
