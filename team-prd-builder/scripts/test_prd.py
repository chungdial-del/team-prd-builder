import copy
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from pathlib import Path

from build_prd import build
from inspect_mockup import inspect_file
from validate_prd import validate
from spec_tests import approval_fingerprint, evaluate, run_suite


ROOT = Path(__file__).resolve().parent.parent


class PrdTests(unittest.TestCase):
    def setUp(self):
        self.model = json.loads(ROOT.joinpath("assets/example.prd.json").read_text(encoding="utf-8"))

    def test_example_and_starter_are_drafts(self):
        for name in ("example.prd.json", "starter.prd.json"):
            model = json.loads(ROOT.joinpath("assets", name).read_text(encoding="utf-8"))
            self.assertEqual(validate(model)["errors"], [])
            self.assertEqual(validate(model)["handoff_candidates"], "blocked")
            self.assertTrue(validate(model, handoff=True)["errors"])

    def test_missing_and_duplicate_references(self):
        self.model["features"][0]["rule_ids"].append("BR-MISSING")
        self.assertTrue(validate(self.model)["errors"])
        self.model["features"][0]["rule_ids"].pop()
        self.model["features"].append(copy.deepcopy(self.model["features"][0]))
        self.assertTrue(any("重複ID" in item for item in validate(self.model)["errors"]))

    def test_bidirectional_trace(self):
        self.model["diagrams"][0]["feature_ids"].remove("FR-01")
        self.assertTrue(any("引用不一致" in item for item in validate(self.model)["errors"]))

    def test_confirmed_needs_real_decision(self):
        self.model["features"][0].update(status="confirmed", decision_id="D-01")
        self.model["decisions"] = [{"id": "D-01", "title": "確認", "scope_ids": ["FR-01"], "answer": "核准", "owner": "教學作者", "date": "2026-10-11", "source_refs": ["S-EXAMPLE"]}]
        self.assertTrue(any("非教學來源" in item for item in validate(self.model)["errors"]))

    def test_approved_review_requires_real_source(self):
        self.model["reviews"][0].update(status="approved", evidence="僅範例", source_refs=["S-EXAMPLE"])
        self.assertTrue(validate(self.model)["errors"])

    def test_execution_evidence(self):
        self.model["acceptance"][0]["execution"] = "passed"
        self.assertTrue(validate(self.model)["errors"])

    def test_delivery_status_needs_independent_evidence(self):
        self.model["features"][0]["delivery"] = {"engineering_review": "pending", "implementation": "implemented", "testing": "not_run", "deployment": "not_deployed"}
        self.assertTrue(validate(self.model)["errors"])
        self.model["features"][0]["delivery"]["implementation_evidence"] = "單元測試合成記錄，非真實產品實作"
        self.assertFalse(validate(self.model)["errors"])

    def test_nonfinite_graph_coordinates(self):
        self.model["diagrams"][0]["nodes"][0]["x"] = float("nan")
        self.assertTrue(validate(self.model)["errors"])

    def test_graph_bounds_and_ids(self):
        self.model["diagrams"][0]["nodes"][0]["x"] = -1
        self.assertTrue(validate(self.model)["errors"])
        self.model["diagrams"][0]["nodes"][0]["x"] = 30
        self.model["diagrams"][0]["id"] = "../unsafe"
        self.assertTrue(validate(self.model)["errors"])

    def test_malformed_arrays_fail_safely(self):
        self.model["diagrams"][0]["nodes"] = [None]
        self.assertEqual(validate(self.model)["structure"], "failed")

    def test_custom_chapter_ids_with_semantic_kind(self):
        self.model["chapters"][9].update(id="QUALITY", kind="quality")
        self.model["chapters"][10].update(id="DECISIONS", kind="governance")
        self.model["explanation_levels"][-1]["chapter_ids"] = ["QUALITY", "DECISIONS"]
        self.assertFalse(validate(self.model)["errors"])
        self.model["chapters"][9]["kind"] = "general"
        self.assertTrue(validate(self.model)["errors"])

    def test_non_core_coverage_requires_rationale(self):
        self.model["project"]["core_feature_ids"] = ["FR-01"]
        self.assertTrue(validate(self.model)["errors"])
        self.model["project"]["coverage_rationale"] = "測試用裁減示範；正式採用需人工確認"
        self.assertFalse(validate(self.model)["errors"])

    def test_hidden_feature_cannot_be_silently_omitted(self):
        self.model["chapters"][7]["feature_ids"].remove("FR-01")
        self.assertTrue(any("正文" in item for item in validate(self.model)["errors"]))

    def confirmed_model(self):
        model = copy.deepcopy(self.model)
        model["sources"].append({"id": "S-ANSWER", "title": "測試用核准記錄", "kind": "user_answer", "locator": "單元測試內的合成核准，非真實產品", "authoritative": True})
        scope_ids = [item["id"] for collection in ("features", "rules", "goals", "contracts", "checks") for item in model[collection] if item["status"] != "excluded"]
        model["decisions"] = [{"id": "D-CONFIRM", "title": "測試確認", "scope_ids": scope_ids, "answer": "單元測試用的確認", "owner": "測試", "approver_role": "PM", "date": "2026-10-11", "source_refs": ["S-ANSWER"]}]
        for item in model["features"] + model["rules"] + model["goals"] + model["contracts"] + model["checks"]:
            if item["id"] in scope_ids:
                item.update(status="confirmed", decision_id="D-CONFIRM")
        model["decisions"][0]["approved_fingerprints"] = {item["id"]: approval_fingerprint(item) for item in model["contracts"] + model["checks"]}
        for item in model["reviews"]:
            item.update(status="approved", evidence="單元測試合成資料，不是人類核准", source_refs=["S-ANSWER"])
        return model

    def test_handoff_machine_gate_and_local_blocker(self):
        model = self.confirmed_model()
        del model["mockups"]
        self.assertFalse(validate(model, handoff=True)["errors"])
        model["questions"][0]["blocking_feature_ids"].append("FR-01")
        self.assertTrue(any("阻擋" in item for item in validate(model, handoff=True)["errors"]))

    def test_export_editable_xml_and_same_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "deliverable"
            build(self.model, output)
            document = ET.parse(output / "diagrams.drawio").getroot()
            self.assertEqual(len(document.findall("diagram")), len(self.model["diagrams"]))
            for source in self.model["diagrams"]:
                single = ET.parse(output / "drawio" / (source["id"] + ".drawio")).getroot()
                self.assertEqual(len(single.findall("diagram")), 1)
                cells = {item.attrib["id"]: item for item in single.findall(".//mxCell")}
                self.assertEqual(sum(item.attrib.get("vertex") == "1" for item in cells.values()), len(source["nodes"]))
                self.assertEqual(sum(item.attrib.get("edge") == "1" for item in cells.values()), len(source["edges"]))
                for node in source["nodes"]:
                    geometry = cells[node["id"]].find("mxGeometry")
                    for key in ("x", "y", "width", "height"):
                        self.assertEqual(float(geometry.attrib[key]), node[key])
                for edge in source["edges"]:
                    geometry = cells[edge["id"]].find("mxGeometry")
                    if edge.get("label"):
                        offset = geometry.find("mxPoint[@as='offset']")
                        self.assertEqual(geometry.attrib["x"], "-1")
                        self.assertEqual(float(offset.attrib["x"]) + edge["points"][0]["x"], edge["label_x"])
                        self.assertEqual(float(offset.attrib["y"]) + edge["points"][0]["y"], edge["label_y"])
                svg = ET.parse(output / "diagrams" / (source["id"] + ".svg")).getroot()
                self.assertEqual(svg.attrib["viewBox"], "0 0 " + str(source["width"]) + " " + str(source["height"]))
                self.assertNotIn("image", ET.tostring(single, encoding="unicode").lower())
            self.assertEqual(json.loads((output / "prd.json").read_text()), self.model)
            self.assertFalse(list(output.rglob("*.html")))
            with ZipFile(output / "prd.docx") as package:
                self.assertEqual(len([name for name in package.namelist() if name.startswith("word/media/")]), len(self.model["diagrams"]))
                document_xml = ET.fromstring(package.read("word/document.xml"))
                text = " ".join(document_xml.itertext())
                namespace = {"word": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for fonts in document_xml.findall(".//word:rFonts", namespace):
                    self.assertEqual(fonts.attrib["{" + namespace["word"] + "}eastAsia"], "Arial Unicode MS")
                    self.assertNotIn("{" + namespace["word"] + "}eastAsiaTheme", fonts.attrib)
                for diagram in self.model["diagrams"]:
                    self.assertIn(diagram["id"], text)
                    self.assertIn(diagram["purpose"], text)
                    for note in diagram["reading_notes"] + diagram["legend"]:
                        self.assertIn(note, text)
            self.assertEqual(validate(self.model)["docx_render_review"]["status"], "not_run")
            with self.assertRaises(FileExistsError):
                build(self.model, output)
            build(self.model, output, overwrite=True)

    def test_mockup_script_not_executed_or_treated_as_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mockup.html"
            path.write_text('<title>方案</title><label for="qty">數量</label><input id="qty" required value="secret"><input type="password" value="credential"><button>驗證</button><a href="https://user:password@example.com/plan?token=secret">方案</a><script>DELETE_EVERYTHING()</script><style>INVISIBLE_STYLE</style>', encoding="utf-8")
            result = inspect_file(path)
            self.assertEqual(result["inspection"], "static_only")
            self.assertEqual(result["customer_approval"], "not_inferred")
            self.assertEqual(result["fields"][0]["label_hint"], "數量")
            self.assertEqual(result["fields"][0]["required_attribute"], True)
            self.assertEqual(result["actions"][0]["text"], "驗證")
            serialized = json.dumps(result)
            for omitted in ("DELETE_EVERYTHING", "INVISIBLE_STYLE", "credential", "token=secret", "user:password", '"value"'):
                self.assertNotIn(omitted, serialized)

    def test_docx_font_is_configurable_and_nonempty(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "deliverable"
            with self.assertRaises(ValueError):
                build(self.model, output, docx_font=" ")
            self.assertFalse(output.exists())
            build(self.model, output, docx_font="Microsoft JhengHei")
            with ZipFile(output / "prd.docx") as package:
                self.assertIn("Microsoft JhengHei", package.read("word/document.xml").decode("utf-8"))

    def add_mockup(self):
        self.model["sources"].append({"id": "S-HTML", "title": "HTML", "kind": "html_mockup", "locator": "作者提供的本地mockup", "authoritative": False})
        self.model["mockups"] = [{"id": "M-01", "title": "方案畫面", "version": "v1", "locator": "mockup.html #qty", "source_ref": "S-HTML", "availability": "read", "confirmation": "observed", "screen_ids": ["UI-PLAN"], "feature_ids": ["FR-01"], "confirmed_decision_ids": [], "observations": ["數量欄位有required屬性"], "limitations": ["未執行JS"], "confirmed_scope": []}]
        self.model["features"][0]["mockup_ids"] = ["M-01"]
        return self.model["mockups"][0]

    def test_optional_mockup_trace_and_missing_access_are_local(self):
        mockup = self.add_mockup()
        self.assertFalse(validate(self.model)["errors"])
        mockup["availability"] = "unavailable"
        self.assertFalse(validate(self.model)["errors"])
        self.assertTrue(any("未取得" in item for item in validate(self.model)["warnings"]))
        self.model["features"][0]["mockup_ids"] = []
        self.assertTrue(validate(self.model)["errors"])

    def test_verified_mockup_scope_does_not_auto_confirm_feature(self):
        mockup = self.add_mockup()
        mockup["confirmation"] = "author_confirmed"
        self.assertTrue(validate(self.model)["errors"])
        mockup.update(confirmed_by="作者", confirmed_on="2026-10-11", confirmation_evidence="作者提供的客戶確認紀錄", confirmed_scope=["數量欄位及驗證按鈕"])
        self.assertFalse(validate(self.model)["errors"])
        self.assertEqual(self.model["features"][0]["status"], "proposed")

    def test_html_observation_cannot_be_sole_approval_source(self):
        self.add_mockup()
        self.model["decisions"] = [{"id": "D-HTML", "title": "不當推定", "scope_ids": ["FR-01"], "answer": "HTML有按鈕", "owner": "測試", "date": "2026-10-11", "source_refs": ["S-HTML"]}]
        self.model["features"][0].update(status="confirmed", decision_id="D-HTML")
        self.assertTrue(validate(self.model)["errors"])

    def test_mockup_mapping_is_in_docx_without_html_output(self):
        self.add_mockup()
        with tempfile.TemporaryDirectory() as directory:
            build(self.model, directory)
            with ZipFile(Path(directory) / "prd.docx") as package:
                text = " ".join(ET.fromstring(package.read("word/document.xml")).itertext())
                self.assertIn("M-01", text)
                self.assertIn("未執行JS", text)
                self.assertIn("數量欄位有required屬性", text)
            self.assertFalse(list(Path(directory).rglob("*.html")))

    def test_five_levels_must_cover_ordered_chapters(self):
        self.model["explanation_levels"].pop()
        self.assertTrue(validate(self.model)["errors"])
        self.setUp()
        self.model["chapters"].reverse()
        self.assertTrue(any("L1至L5排序" in entry for entry in validate(self.model)["errors"]))

    def test_pm_role_and_authoritative_approval_are_required(self):
        model = self.confirmed_model()
        model["decisions"][0]["approver_role"] = "engineering"
        self.assertTrue(any("PM角色" in entry for entry in validate(model)["errors"]))
        model["decisions"][0]["approver_role"] = "PM"
        model["sources"][-1]["kind"] = "code_observation"
        self.assertTrue(validate(model)["errors"])

    def test_unconfirmed_cases_are_blocked_not_silently_passed(self):
        before = copy.deepcopy(self.model)
        result = run_suite(self.model, self.model["checks"])
        self.assertEqual(result["counts"]["passed"], 0)
        self.assertEqual(result["counts"]["blocked_pending_pm"], len(self.model["checks"]))
        illustrative = run_suite(self.model, self.model["checks"], example=True)
        self.assertEqual(illustrative["status"], "example_only")
        self.assertEqual(self.model, before)

    def test_formal_reference_model_and_independent_oracle(self):
        model = self.confirmed_model()
        self.assertEqual(run_suite(model, model["checks"])["status"], "passed")
        with self.assertRaises(ValueError):
            run_suite(model, model["checks"], example=True)
        model["checks"][0]["expected"]["valid"] = False
        self.assertEqual(run_suite(model, model["checks"])["counts"]["blocked_pending_pm"], 1)
        self.model["checks"][0]["expected"]["valid"] = False
        self.assertEqual(run_suite(self.model, self.model["checks"], example=True)["status"], "failed")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                build(model, directory, handoff=True)

    def test_contract_change_invalidates_stale_pm_approval(self):
        model = self.confirmed_model()
        model["contracts"][0]["spec"]["maximum"] = 200
        self.assertTrue(validate(model)["errors"])
        self.assertEqual(run_suite(model, model["checks"])["counts"]["blocked_pending_pm"], 5)

    def test_number_boundaries_and_invalid_values(self):
        contract = self.model["contracts"][0]
        for value, valid in [(0, True), (20, True), (-1, False), (21, False), ("", False), (True, False), (None, False), (float("nan"), False), (float("inf"), False)]:
            self.assertEqual(evaluate(contract, {"quantity": value}), {"valid": valid})

    def test_unknown_retry_rejected_without_state_change(self):
        contract = self.model["contracts"][-1]
        self.assertEqual(evaluate(contract, {"state": "unknown", "event": "retry"}), {"allowed": False, "state": "unknown"})
        self.assertEqual(evaluate(contract, {"state": "received", "event": "retry"}), {"allowed": False, "state": "received"})

    def test_machine_trace_and_expected_types_are_validated(self):
        self.model["checks"][0]["goal_id"] = "GO-RETRY"
        self.assertTrue(validate(self.model)["errors"])
        self.setUp()
        self.model["checks"][0]["expected"]["valid"] = 1
        self.assertTrue(validate(self.model)["errors"])

    def test_pending_semantic_change_blocks_related_contract(self):
        model = self.confirmed_model()
        model["changes"] = [{"id": "CH-01", "kind": "semantic", "status": "proposed", "scope_ids": ["BR-04"], "before": "未知不能重送", "after": "待PM裁決的相反提案", "reason": "合成測試，不套用"}]
        self.assertTrue(validate(model, handoff=True)["errors"])
        result = run_suite(model, model["checks"])
        self.assertEqual(result["counts"]["blocked_pending_pm"], 3)
        model["changes"][0]["status"] = "approved"
        self.assertTrue(validate(model)["errors"])

    def test_uncovered_goal_cannot_be_counted_as_passed(self):
        model = self.confirmed_model()
        cases = [entry for entry in model["checks"] if entry["goal_id"] != "GO-RETRY"]
        result = run_suite(model, cases)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["goals"][-1]["status"], "not_covered")

    def test_exported_runner_is_standalone_and_records_input_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build(self.model, output, example_tests=True)
            runner = output / "validation/run_spec_tests.py"
            report_path = output / "validation/cli-results.json"
            execution = subprocess.run([sys.executable, str(runner), "--example", "--output", str(report_path)], capture_output=True, text=True)
            self.assertEqual(execution.returncode, 0, execution.stdout)
            result = json.loads(report_path.read_text())
            self.assertEqual(result["status"], "example_only")
            self.assertEqual(set(result["input_sha256"]), {"contracts.json", "cases.json"})
            execution = subprocess.run([sys.executable, str(runner)], capture_output=True, text=True)
            self.assertEqual(execution.returncode, 1)
            self.assertEqual(json.loads(execution.stdout)["counts"]["passed"], 0)

    def test_unreadable_diagram_fails_without_partial_delivery(self):
        self.model["diagrams"][2]["font_size"] = 10
        self.model["diagrams"][2]["label_font_size"] = 10
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "deliverable"
            with self.assertRaises(ValueError):
                build(self.model, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
