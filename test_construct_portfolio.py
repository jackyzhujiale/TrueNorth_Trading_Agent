import csv
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from construct_portfolio import (
    PortfolioInputError,
    Position,
    RatedSymbol,
    construct_portfolio,
    main,
    read_ratings,
    write_positions,
)


class ConstructPortfolioTests(unittest.TestCase):
    def test_mixed_ratings_are_market_neutral(self):
        positions = construct_portfolio(
            [
                RatedSymbol("BTC", -0.8),
                RatedSymbol("ETH", -0.2),
                RatedSymbol("SOL", 0.3),
                RatedSymbol("XRP", 0.9),
            ]
        )

        positive_sum = sum(item.position for item in positions if item.position > 0)
        negative_sum = sum(item.position for item in positions if item.position < 0)
        net_sum = sum(item.position for item in positions)

        self.assertAlmostEqual(positive_sum, 1.0)
        self.assertAlmostEqual(negative_sum, -1.0)
        self.assertAlmostEqual(net_sum, 0.0)
        self.assertEqual([item.symbol for item in positions], ["BTC", "ETH", "SOL", "XRP"])

    def test_all_same_ratings_use_alphabetical_fallback(self):
        positions = construct_portfolio(
            [
                RatedSymbol("MSFT", 0.5),
                RatedSymbol("AAPL", 0.5),
                RatedSymbol("GOOG", 0.5),
            ]
        )

        self.assertEqual([item.symbol for item in positions], ["AAPL", "GOOG", "MSFT"])
        self.assertAlmostEqual(positions[0].position, 0.5)
        self.assertAlmostEqual(positions[1].position, 0.5)
        self.assertAlmostEqual(positions[2].position, -1.0)

    def test_all_long_under_mean_rule_uses_fallback(self):
        positions = construct_portfolio([RatedSymbol("B", 0.1), RatedSymbol("A", 0.1)])

        self.assertEqual([item.symbol for item in positions], ["A", "B"])
        self.assertAlmostEqual(positions[0].position, 1.0)
        self.assertAlmostEqual(positions[1].position, -1.0)

    def test_ties_at_mean_get_zero_distance_weight(self):
        positions = construct_portfolio(
            [
                RatedSymbol("LOW", -1.0),
                RatedSymbol("MID", 0.0),
                RatedSymbol("HIGH", 1.0),
            ]
        )
        position_by_symbol = {item.symbol: item.position for item in positions}

        self.assertAlmostEqual(position_by_symbol["LOW"], -1.0)
        self.assertAlmostEqual(position_by_symbol["MID"], 0.0)
        self.assertAlmostEqual(position_by_symbol["HIGH"], 1.0)

    def test_write_positions_outputs_expected_columns(self):
        output = io.StringIO()
        write_positions([Position("A", 0.25)], output)

        rows = list(csv.reader(io.StringIO(output.getvalue())))
        self.assertEqual(rows, [["symbol", "position"], ["A", "0.25"]])

    def test_rejects_fewer_than_two_rows(self):
        with self.assertRaisesRegex(PortfolioInputError, "at least 2"):
            self._read_csv("symbol,rating\nA,0.1\n")

    def test_rejects_missing_columns(self):
        with self.assertRaisesRegex(PortfolioInputError, "missing required"):
            self._read_csv("symbol,score\nA,0.1\nB,0.2\n")

    def test_rejects_duplicate_symbols(self):
        with self.assertRaisesRegex(PortfolioInputError, "duplicate symbol"):
            self._read_csv("symbol,rating\nA,0.1\nA,0.2\n")

    def test_rejects_out_of_range_rating(self):
        with self.assertRaisesRegex(PortfolioInputError, r"\[-1, 1\]"):
            self._read_csv("symbol,rating\nA,0.1\nB,1.1\n")

    def test_rejects_non_numeric_rating(self):
        with self.assertRaisesRegex(PortfolioInputError, "numeric float"):
            self._read_csv("symbol,rating\nA,0.1\nB,nope\n")

    def test_cli_writes_stdout_when_output_path_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "ratings.csv"
            input_path.write_text("symbol,rating\nA,-1\nB,1\n", encoding="utf-8")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                exit_code = main([str(input_path)])

        self.assertEqual(exit_code, 0)
        rows = list(csv.reader(io.StringIO(output.getvalue())))
        self.assertEqual(rows[0], ["symbol", "position"])
        self.assertEqual(rows[1:], [["A", "-1.0"], ["B", "1.0"]])

    def test_cli_writes_output_file_when_path_is_provided(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "ratings.csv"
            output_path = Path(tmp_dir) / "positions.csv"
            input_path.write_text("symbol,rating\nA,-1\nB,1\n", encoding="utf-8")

            exit_code = main([str(input_path), str(output_path)])

            rows = list(csv.reader(io.StringIO(output_path.read_text(encoding="utf-8"))))

        self.assertEqual(exit_code, 0)
        self.assertEqual(rows[0], ["symbol", "position"])
        self.assertEqual(rows[1:], [["A", "-1.0"], ["B", "1.0"]])

    def _read_csv(self, content):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "ratings.csv"
            path.write_text(content, encoding="utf-8")
            return read_ratings(path)


if __name__ == "__main__":
    unittest.main()
