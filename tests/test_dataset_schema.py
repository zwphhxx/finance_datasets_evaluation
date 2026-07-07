"""the dataset schema additions — taxonomy impacted dimensions and
the schema doc — are present, and the validator's new impacted-dimension check
catches invalid references. All assertions read live files; nothing hardcoded.
"""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from scripts.validate_dataset import validate_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class TaxonomyImpactedDimensionTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = _load(DATA_DIR / "label_taxonomy.yml")
        self.manifest = _load(DATA_DIR / "dataset_manifest.yml")
        self.rubric_dimensions = {
            dim["name"] for dim in self.manifest["rubric"]["dimensions"]
        }

    def test_every_label_declares_a_valid_impacted_dimension(self):
        labels = self.taxonomy["labels"]
        self.assertTrue(labels)
        for label in labels:
            self.assertIn("impacted_dimension", label, label.get("name"))
            self.assertIn(label["impacted_dimension"], self.rubric_dimensions, label["name"])

    def test_taxonomy_keeps_definition_and_data_direction(self):
        for label in self.taxonomy["labels"]:
            for field in ("name", "definition", "typical_signs", "data_direction"):
                self.assertTrue(str(label.get(field, "")).strip(), f"{label.get('name')}/{field}")


class ValidatorImpactedDimensionCheckTests(unittest.TestCase):
    def test_real_dataset_reports_impacted_dimension_pass(self):
        report = validate_dataset(DATA_DIR)
        self.assertTrue(report.is_valid, "; ".join(report.errors))
        self.assertTrue(any("影响维度" in line for line in report.passed))

    def test_invalid_impacted_dimension_is_flagged(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(DATA_DIR, data_dir)
            taxonomy_path = data_dir / "label_taxonomy.yml"
            taxonomy = _load(taxonomy_path)
            taxonomy["labels"][0]["impacted_dimension"] = "不存在的维度"
            with taxonomy_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(taxonomy, handle, allow_unicode=True)

            report = validate_dataset(
                data_dir,
                manifest_path=data_dir / "dataset_manifest.yml",
                taxonomy_path=taxonomy_path,
            )
            self.assertFalse(report.is_valid)
            self.assertTrue(any("影响维度不在评分标准维度范围内" in e for e in report.errors))


class SchemaDocTests(unittest.TestCase):
    def test_schema_doc_documents_logical_objects(self):
        doc = (PROJECT_ROOT / "docs" / "dataset_schema.md").read_text(encoding="utf-8")
        for obj in [
            "task_cases",
            "gold_answers",
            "rubrics",
            "model_responses",
            "score_records",
            "error_annotations",
            "improvement_actions",
        ]:
            self.assertIn(obj, doc)


if __name__ == "__main__":
    unittest.main()
