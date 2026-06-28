#!/usr/bin/env python3
"""Construct a market-neutral long/short portfolio from symbol ratings."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO


class PortfolioInputError(ValueError):
    """Raised when the input CSV cannot be converted into a portfolio."""


@dataclass(frozen=True)
class RatedSymbol:
    symbol: str
    rating: float


@dataclass(frozen=True)
class Position:
    symbol: str
    position: float


def read_ratings(path: str | Path) -> list[RatedSymbol]:
    with open(path, newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise PortfolioInputError("input CSV must contain a header row")

        required_columns = {"symbol", "rating"}
        missing_columns = sorted(required_columns - set(reader.fieldnames))
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise PortfolioInputError(f"input CSV is missing required column(s): {missing}")

        seen_symbols: set[str] = set()
        ratings: list[RatedSymbol] = []
        for row_number, row in enumerate(reader, start=2):
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                raise PortfolioInputError(f"row {row_number}: symbol must not be empty")
            if symbol in seen_symbols:
                raise PortfolioInputError(f"row {row_number}: duplicate symbol {symbol!r}")
            seen_symbols.add(symbol)

            raw_rating = (row.get("rating") or "").strip()
            try:
                rating = float(raw_rating)
            except ValueError as exc:
                raise PortfolioInputError(
                    f"row {row_number}: rating must be a numeric float"
                ) from exc

            if not math.isfinite(rating):
                raise PortfolioInputError(f"row {row_number}: rating must be finite")
            if rating < -1.0 or rating > 1.0:
                raise PortfolioInputError(
                    f"row {row_number}: rating must be within [-1, 1]"
                )

            ratings.append(RatedSymbol(symbol=symbol, rating=rating))

    if len(ratings) < 2:
        raise PortfolioInputError("input CSV must contain at least 2 symbols")

    return ratings


def construct_portfolio(ratings: Iterable[RatedSymbol]) -> list[Position]:
    sorted_ratings = sorted(ratings, key=lambda item: (item.rating, item.symbol))
    if len(sorted_ratings) < 2:
        raise PortfolioInputError("input must contain at least 2 symbols")

    mean_rating = sum(item.rating for item in sorted_ratings) / len(sorted_ratings)
    longs = [item for item in sorted_ratings if item.rating >= mean_rating]
    shorts = [item for item in sorted_ratings if item.rating < mean_rating]
    all_same_rating = all(item.rating == sorted_ratings[0].rating for item in sorted_ratings)

    if all_same_rating or not longs or not shorts:
        return _fallback_portfolio(sorted_ratings)

    position_by_symbol: dict[str, float] = {}
    position_by_symbol.update(
        _normalize_side(
            ((item.symbol, item.rating - mean_rating) for item in longs),
            target_sum=1.0,
        )
    )
    position_by_symbol.update(
        _normalize_side(
            ((item.symbol, mean_rating - item.rating) for item in shorts),
            target_sum=-1.0,
        )
    )

    return [
        Position(symbol=item.symbol, position=position_by_symbol[item.symbol])
        for item in sorted_ratings
    ]


def write_positions(positions: Iterable[Position], output: TextIO) -> None:
    writer = csv.writer(output)
    writer.writerow(["symbol", "position"])
    for item in positions:
        writer.writerow([item.symbol, item.position])


def _fallback_portfolio(ratings: Iterable[RatedSymbol]) -> list[Position]:
    sorted_by_symbol = sorted(ratings, key=lambda item: item.symbol)
    short_symbol = sorted_by_symbol[-1].symbol
    long_position = 1.0 / (len(sorted_by_symbol) - 1)

    return [
        Position(
            symbol=item.symbol,
            position=-1.0 if item.symbol == short_symbol else long_position,
        )
        for item in sorted_by_symbol
    ]


def _normalize_side(
    raw_weights: Iterable[tuple[str, float]], target_sum: float
) -> dict[str, float]:
    weights = [(symbol, max(weight, 0.0)) for symbol, weight in raw_weights]
    if not weights:
        return {}

    total_weight = sum(weight for _, weight in weights)
    if total_weight == 0.0:
        positions = [(symbol, target_sum / len(weights)) for symbol, _ in weights]
        residual_index = len(positions) - 1
    else:
        positions = [
            (symbol, target_sum * weight / total_weight) for symbol, weight in weights
        ]
        residual_index = max(range(len(weights)), key=lambda index: weights[index][1])

    if len(positions) == 1:
        symbol, _ = positions[0]
        return {symbol: target_sum}

    residual_symbol, _ = positions[residual_index]
    previous_sum = math.fsum(
        position for index, (_, position) in enumerate(positions) if index != residual_index
    )
    positions[residual_index] = (residual_symbol, target_sum - previous_sum)
    return dict(positions)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construct a market-neutral portfolio from a symbol/rating CSV."
    )
    parser.add_argument("input_csv", help="CSV file containing symbol and rating columns")
    parser.add_argument(
        "output_csv",
        nargs="?",
        help="Optional output CSV path. If omitted, output is written to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        ratings = read_ratings(args.input_csv)
        positions = construct_portfolio(ratings)
        if args.output_csv:
            with open(args.output_csv, "w", newline="") as output_file:
                write_positions(positions, output_file)
        else:
            write_positions(positions, sys.stdout)
    except (OSError, PortfolioInputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
