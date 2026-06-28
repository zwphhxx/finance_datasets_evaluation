"""PR-34 tests: live model evaluation runner.

Covers the prompt boundary (Gold Answer never reaches the model, no self-eval),
run orchestration over the Mock provider, graceful failure handling, best-effort
persistence to the dedicated live_run_responses table, dataset-version lookup,
and page wiring. No test performs a real outbound API call.
"""

import tempfile
import unittest
from pathlib import Path

from app.models.base import GenerationResult, ModelProvider, STATUS_FAILED, STATUS_MOCK
from app.models.registry import get_provider
from app.services import dataset_service as ds
from app.services import eval_runner as er
from app.db.repository import Repository
from src.ui.navigation import PAGES
from src.ui.page_config import PAGE_CONFIG_BY_KEY


_TMP = tempfile.TemporaryDirectory()
_DB_PATH = Path(_TMP.name) / "findueval_pr34.db"


def setUpModule():
    ds.initialize_database(_DB_PATH, force=True)


def tearDownModule():
    _TMP.cleanup()


def _sample_tasks(n=2):
    return ds.load_evaluation_data(_DB_PATH).tasks.head(n).to_dict("records")


class _FailingProvider(ModelProvider):
    """Always returns a structured failure (e.g. 401) — never raises."""

    name = "failing"

    def list_models(self, model_type="text", sub_type="chat"):
        raise NotImplementedError

    def generate_response(self, model_id, messages, *, temperature=0.2, max_tokens=2048, **kwargs):
        return GenerationResult(
            self.name, model_id, STATUS_FAILED,
            error_code="unauthorized", error_message="API Key 无效或缺失。",
        )


class PromptBoundaryTests(unittest.TestCase):
    def test_gold_answer_never_sent_to_model(self):
        task = {
            "case_id": "X-1",
            "task_type": "Revenue Verification",
            "scenario": "某公司收购尽调",
            "question": "请评估收入确认的合规性。",
            "context": "提供了近三年财报。",
            # 故意混入 Gold Answer 类字段，必须被白名单挡在外面。
            "core_conclusion": "GOLD-结论-不应外泄",
            "must_have_points": ["GOLD要点A", "GOLD要点B"],
            "unacceptable_errors": ["GOLD红线"],
            "key_evidence": "GOLD依据",
        }
        messages = er.build_messages(task)
        joined = " ".join(m["content"] for m in messages)
        for leak in ["GOLD-结论-不应外泄", "GOLD要点A", "GOLD红线", "GOLD依据"]:
            self.assertNotIn(leak, joined)
        # 任务可见字段应在 prompt 中。
        self.assertIn("某公司收购尽调", joined)
        self.assertIn("请评估收入确认的合规性。", joined)

    def test_system_prompt_avoids_self_eval_and_requires_evidence(self):
        messages = er.build_messages({"question": "Q"})
        system = messages[0]["content"]
        self.assertIn("依据", system)
        self.assertIn("核实", system)
        self.assertIn("不要对自己的回答进行打分", system)


class RunnerTests(unittest.TestCase):
    def test_run_over_mock_provider(self):
        provider = get_provider("mock")
        result = er.run_evaluation(provider, "mock/chat-base", _sample_tasks(2), max_tokens=128)
        self.assertEqual(result.mode, "mock")
        self.assertTrue(result.run_id.startswith("RUN-"))
        self.assertEqual(len(result.outcomes), 2)
        self.assertTrue(all(o.run_status == STATUS_MOCK for o in result.outcomes))
        self.assertTrue(all(o.success for o in result.outcomes))
        self.assertTrue(all(o.answer_length > 0 for o in result.outcomes))
        self.assertTrue(er.is_mock_result(result))

    def test_failure_does_not_crash_and_marks_unsuccessful(self):
        result = er.run_evaluation(_FailingProvider(), "any/model", _sample_tasks(1))
        outcome = result.outcomes[0]
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.run_status, STATUS_FAILED)
        self.assertEqual(outcome.error_code, "unauthorized")
        self.assertEqual(outcome.answer_length, 0)

    def test_single_task_run(self):
        provider = get_provider("mock")
        result = er.run_evaluation(provider, "mock/chat-base", _sample_tasks(1))
        self.assertEqual(len(result.outcomes), 1)


class PersistenceTests(unittest.TestCase):
    def test_persist_writes_to_live_run_table(self):
        provider = get_provider("mock")
        result = er.run_evaluation(provider, "mock/chat-base", _sample_tasks(2))
        ok = er.persist_run_result(result, db_path=_DB_PATH)
        self.assertTrue(ok)
        frame = Repository(_DB_PATH).list_df("live_run_responses")
        saved = frame[frame["run_id"] == result.run_id]
        self.assertEqual(len(saved), 2)
        # 不得保存认证信息。
        self.assertNotIn("Authorization", "".join(frame.columns))
        self.assertEqual(set(saved["run_mode"]), {"mock"})

    def test_persist_returns_false_without_database(self):
        provider = get_provider("mock")
        result = er.run_evaluation(provider, "mock/chat-base", _sample_tasks(1))
        missing = Path(_TMP.name) / "nope.db"
        self.assertFalse(er.persist_run_result(result, db_path=missing))

    def test_persist_does_not_touch_seed_model_responses(self):
        before = Repository(_DB_PATH).count("model_responses")
        provider = get_provider("mock")
        result = er.run_evaluation(provider, "mock/chat-base", _sample_tasks(2))
        er.persist_run_result(result, db_path=_DB_PATH)
        after = Repository(_DB_PATH).count("model_responses")
        # 真实评测结果写入独立表，绝不污染承载评分的 seed model_responses。
        self.assertEqual(before, after)


class ServiceAndWiringTests(unittest.TestCase):
    def test_list_dataset_versions(self):
        versions = ds.list_dataset_versions(_DB_PATH)
        self.assertIsInstance(versions, list)
        self.assertTrue(versions)

    def test_page_registered(self):
        self.assertIn("live_eval", PAGES)
        self.assertIn("live_eval", PAGE_CONFIG_BY_KEY)
        self.assertEqual(PAGE_CONFIG_BY_KEY["live_eval"].title, "真实模型评测")


if __name__ == "__main__":
    unittest.main()
