import argparse
import hashlib
import json
import math
from pathlib import Path


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def approval_fingerprint(item):
    if "spec" in item:
        keys = ("id", "kind", "goal_id", "feature_ids", "rule_ids", "source_refs", "spec")
    elif "expected" in item:
        keys = ("id", "goal_id", "feature_id", "contract_id", "acceptance_ids", "source_refs", "input", "expected")
    else:
        return None
    payload = json.dumps({key: item.get(key) for key in keys}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pm_approved(item, context):
    decisions = {entry["id"]: entry for entry in context.get("decisions", [])}
    sources = {entry["id"]: entry for entry in context.get("sources", [])}
    decision = decisions.get(item.get("decision_id"), {})
    return (
        item.get("status") in {"confirmed", "approved", "rejected", "answered"}
        and item.get("id") in decision.get("scope_ids", [])
        and decision.get("approver_role") == "PM"
        and bool(decision.get("owner"))
        and bool(decision.get("date"))
        and bool(decision.get("answer"))
        and (approval_fingerprint(item) is None or decision.get("approved_fingerprints", {}).get(item.get("id")) == approval_fingerprint(item))
        and any(sources.get(identifier, {}).get("kind") in {"user_answer", "document"}
                and sources.get(identifier, {}).get("authoritative") is True
                for identifier in decision.get("source_refs", []))
    )


def evaluate(contract, inputs):
    spec = contract["spec"]
    if contract["kind"] == "number_range":
        value = inputs.get(spec["field"])
        return {"valid": finite_number(value) and spec["minimum"] <= value <= spec["maximum"]}
    if contract["kind"] == "transition":
        state, event = inputs.get("state"), inputs.get("event")
        if state not in spec["states"] or event not in spec["events"]:
            raise ValueError("案例必須使用契約已列出的狀態及事件。")
        matches = [entry for entry in spec["transitions"] if entry["from"] == state and entry["event"] == event]
        if len(matches) > 1:
            raise ValueError("相同狀態及事件有多個結果。")
        return {"allowed": bool(matches), "state": matches[0]["to"] if matches else state}
    raise ValueError("不支援的契約類型；不得自行補實作。")


def run_suite(context, cases, example=False):
    contracts = {entry["id"]: entry for entry in context.get("contracts", [])}
    goals = {entry["id"]: entry for entry in context.get("goals", [])}
    features = {entry["id"]: entry for entry in context.get("features", [])}
    rules = {entry["id"]: entry for entry in context.get("rules", [])}
    if example and (not context.get("sources") or any(entry.get("kind") != "example" for entry in context["sources"])
                    or context.get("decisions") or any(entry.get("status") == "confirmed" for collection in (contracts, goals, features, rules) for entry in collection.values())
                    or any(entry.get("status") == "confirmed" for entry in cases)):
        raise ValueError("--example只能執行未聲稱人類核准的純合成範例。")
    results = []
    for case in cases:
        result = {key: case[key] for key in ("id", "goal_id", "feature_id", "acceptance_ids", "expected")}
        contract = contracts.get(case.get("contract_id"))
        goal = goals.get(case.get("goal_id"))
        feature = features.get(case.get("feature_id"))
        if not contract or not goal or not feature or case.get("goal_id") != contract.get("goal_id") or feature["id"] not in contract.get("feature_ids", []):
            result.update(status="failed", error="契約、目標或功能引用缺失。")
        else:
            dependencies = [case, contract, goal, feature] + [rules.get(identifier, {}) for identifier in contract.get("rule_ids", [])]
            questions = [entry["id"] for entry in context.get("questions", []) if entry.get("status") == "open" and feature["id"] in entry.get("blocking_feature_ids", [])]
            related_ids = {entry.get("id") for entry in dependencies}
            pending_changes = [entry["id"] for entry in context.get("changes", []) if entry.get("kind") != "editorial" and entry.get("status") == "proposed" and related_ids.intersection(entry.get("scope_ids", []))]
            if not example and (any(not pm_approved(entry, context) for entry in dependencies) or questions or pending_changes):
                result.update(status="blocked_pending_pm", blockers=questions + pending_changes, note="規格、預期或受影響事項尚未獲PM核准。")
            else:
                try:
                    actual = evaluate(contract, case["input"])
                    result.update(actual=actual, status="passed" if actual == case["expected"] else "failed")
                except (ValueError, TypeError, KeyError, OverflowError) as exception:
                    result.update(status="failed", error=str(exception))
        results.append(result)
    counts = {status: sum(entry["status"] == status for entry in results) for status in ("passed", "failed", "blocked_pending_pm")}
    goal_results = []
    for goal in goals.values():
        related = [entry for entry in results if entry["goal_id"] == goal["id"]]
        status = "not_covered" if not related else ("failed" if any(entry["status"] == "failed" for entry in related) else ("blocked_pending_pm" if any(entry["status"] == "blocked_pending_pm" for entry in related) else "passed"))
        goal_results.append({"goal_id": goal["id"], "status": status, "case_ids": [entry["id"] for entry in related]})
    passed = bool(results) and bool(goal_results) and all(entry["status"] == "passed" for entry in results + goal_results)
    status = "failed" if counts["failed"] else ("passed" if passed else "incomplete")
    return {"status": "example_only" if example and passed else status, "mode": "synthetic_example" if example else "spec_reference_model",
            "counts": counts, "goals": goal_results, "cases": results,
            "system_testing": "not_run", "note": "只驗證規格參考模型。未證明產品實作、未涵蓋的行為或PM核准真實性。"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--example", action="store_true")
    args = parser.parse_args()
    try:
        contract_path, case_path = args.directory / "contracts.json", args.directory / "cases.json"
        context = json.loads(contract_path.read_text(encoding="utf-8"))
        cases = json.loads(case_path.read_text(encoding="utf-8"))
        report = run_suite(context, cases, args.example)
        report["input_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (contract_path, case_path)}
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.write_text(serialized + "\n", encoding="utf-8")
        print(serialized)
        return 0 if report["status"] in {"passed", "example_only"} else 1
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exception:
        print(str(exception))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
