import unittest
import io

from alphacairn.web import evaluate
from alphacairn.backtest import dataset_digest, parse_bars


class ResearchAdapterTests(unittest.TestCase):
    def test_line_endings_do_not_change_normalized_dataset_identity(self):
        lf = "date,open,close\n2020-01-01,100,101\n2020-01-02,102,103\n"
        crlf = lf.replace("\n", "\r\n")
        first = evaluate({"csv": lf, "lookback": 1})
        second = evaluate({"csv": crlf, "lookback": 1})
        self.assertEqual(first["data_sha256"], second["data_sha256"])
        self.assertNotEqual(first["input_text_sha256"], second["input_text_sha256"])
        self.assertEqual(
            first["data_sha256"], dataset_digest(parse_bars(io.StringIO(lf)))
        )

    def test_fixed_study_metrics_reconcile_to_the_simulator(self):
        report = evaluate({})
        self.assertEqual(report["bars"], 260)
        self.assertEqual(
            report["strategy_metrics"]["total_return"],
            report["strategy"]["total_return"],
        )
        self.assertEqual(
            report["strategy_metrics"]["maximum_drawdown"],
            report["strategy"]["max_drawdown"],
        )
        self.assertEqual(report["windows"], [])

