# Jiale Trader Rating

Use this skill when a user asks an agent to generate rating input CSV files for
`construct_portfolio.py`.

The required output is a CSV with exactly two columns:

```csv
symbol,rating
BTC,0.42
AAPL,-0.18
```

`rating` must be a finite float in `[-1, 1]`. Positive ratings suggest long
bias, negative ratings suggest short bias. Ratings are technical-only research
signals, not financial advice.

## User Inputs

Before generating a rating file, ask the user for:

- The symbols they are interested in.
- The prediction horizon in hours, if they want something other than the
  default.

Defaults:

- `prediction_horizon_hours = 24`
- Candle interval is always `1h`
- Rating target is the agent's technical view for the next prediction horizon.

Normalize user symbols by trimming whitespace and uppercasing them. Preserve the
user-facing symbol in the output CSV unless a verified exchange symbol must use a
different canonical name.

## Market Verification And Candle Fetching

First check whether a dedicated Hyperliquid API skill/tool is available. If it
exists, load it and use it. If it does not exist, use the public REST fallback
below.

REST base:

```text
POST https://api.hyperliquid.xyz/info
Content-Type: application/json
```

Verify listed markets before rating:

- For ordinary Hyperliquid crypto perps, request perpetual metadata:

```json
{"type":"meta"}
```

Check the returned `universe` for the symbol.

- For trade[XYZ]/XYZ tradfi markets, request HIP-3 metadata with the XYZ DEX:

```json
{"type":"meta","dex":"xyz"}
```

Check the returned `universe` for the symbol.

- If a symbol exists on both ordinary Hyperliquid and XYZ, prefer ordinary
  Hyperliquid unless the user explicitly asked for the tradfi/XYZ market.

Fetch candles only after verification. Use hourly candles for the last
`4 * prediction_horizon_hours` hours:

```json
{
  "type": "candleSnapshot",
  "req": {
    "coin": "BTC",
    "interval": "1h",
    "startTime": 1710000000000,
    "endTime": 1710345600000
  }
}
```

For HIP-3 XYZ candles, prefix the coin with the DEX name:

```json
{
  "type": "candleSnapshot",
  "req": {
    "coin": "xyz:AAPL",
    "interval": "1h",
    "startTime": 1710000000000,
    "endTime": 1710345600000
  }
}
```

Use the latest completed hourly candle as the evaluation point. If the newest
candle is still in progress, drop it. Exclude a symbol if it is unlisted, has no
candles, or has too few candles to compute every signal below.

## Technical Signal System

Evaluate every symbol through the same technical system. Use hourly OHLCV
candles sorted oldest to newest.

Required candle fields:

- open
- high
- low
- close
- timestamp

For each raw technical signal, apply the same EWMA demeaning and z-score
normalization before converting it to a rating.

```python
def de_mean(
    df: pd.DataFrame,
    column_name: str,
    halflife: int = prediction_horizon_hours * 4,
    sigma_clipping: int = 3,
    inplace: bool = False,
) -> pd.DataFrame:
    out_col = column_name if inplace else f"{column_name}_demeaned"

    df[out_col] = (
        df[column_name] - df[column_name].ewm(halflife=halflife, adjust=False).mean()
    )

    vlt = np.sqrt(
        (df[out_col] ** 2).ewm(halflife=halflife, adjust=False, ignore_na=True).mean()
    )
    df[out_col] = np.clip(df[out_col] / (vlt + 1e-10), -sigma_clipping, sigma_clipping)

    return df
```

Convert a demeaned signal into a signal rating:

```python
signal_rating = float(np.clip(latest_demeaned_value / 3.0, -1.0, 1.0))
```

If the latest signal rating is not finite, drop only that signal for that symbol.
If no signal is valid for a symbol, exclude the symbol and report why.

### RSI Reversion

Use RSI as a mean-reversion signal and flip the sign.

Parameters:

```python
rsi_lookback = max(2, round(0.25 * prediction_horizon_hours))
```

Computation:

- Compute hourly close-to-close deltas.
- Compute average gains and losses over `rsi_lookback`.
- Compute RSI in `[0, 100]`.
- Raw signal:

```python
rsi_raw = 50.0 - rsi
```

Demean `rsi_raw`, scale to `[-1, 1]`, and use the latest value as
`rsi_rating`.

### MACD Reversion

Use MACD histogram as a mean-reversion signal and flip the sign.

Parameters:

```python
macd_fast = max(2, round(0.125 * prediction_horizon_hours))
macd_slow = max(macd_fast + 1, round(0.25 * prediction_horizon_hours))
macd_signal = max(2, round(0.125 * prediction_horizon_hours))
```

Computation:

- `fast_ema = close.ewm(span=macd_fast, adjust=False).mean()`
- `slow_ema = close.ewm(span=macd_slow, adjust=False).mean()`
- `macd_line = fast_ema - slow_ema`
- `signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()`
- `macd_hist = macd_line - signal_line`
- Raw signal:

```python
macd_raw = -macd_hist / (close + 1e-10)
```

Demean `macd_raw`, scale to `[-1, 1]`, and use the latest value as
`macd_rating`.

### SMI Reversion

Use Stochastic Momentum Index as a mean-reversion signal and flip the sign.

Parameters:

```python
smi_window = max(3, round(0.25 * prediction_horizon_hours))
smi_fast = max(2, round(0.125 * prediction_horizon_hours))
smi_slow = max(smi_fast + 1, round(0.25 * prediction_horizon_hours))
```

Computation:

- `highest_high = high.rolling(smi_window).max()`
- `lowest_low = low.rolling(smi_window).min()`
- `midpoint = (highest_high + lowest_low) / 2`
- `distance = close - midpoint`
- `range_half = (highest_high - lowest_low) / 2`
- Smooth `distance` twice using EMA spans `smi_fast` then `smi_slow`.
- Smooth `range_half` twice using EMA spans `smi_fast` then `smi_slow`.
- `smi = 100 * smoothed_distance / (smoothed_range_half + 1e-10)`
- Raw signal:

```python
smi_raw = -smi
```

Demean `smi_raw`, scale to `[-1, 1]`, and use the latest value as
`smi_rating`.

## Final Symbol Rating

For each verified symbol:

```python
rating = mean([rsi_rating, macd_rating, smi_rating])
rating = float(np.clip(rating, -1.0, 1.0))
```

Use a simple average across valid signal ratings. Do not change signal weights
symbol-by-symbol. Every rated symbol must pass through the same signal system.

## Output And Reporting

Write the rating CSV with exactly:

```csv
symbol,rating
```

Do not include signal details, comments, timestamps, or extra columns in the CSV
used by `construct_portfolio.py`.

In the user-facing response, report:

- Output CSV path.
- Prediction horizon used.
- Symbols successfully rated.
- Symbols excluded and exact reasons.
- Data source used for each rated symbol: Hyperliquid or XYZ.
- Reminder that ratings are technical-only, not financial advice.

If fewer than 2 symbols can be rated, do not write a portfolio input CSV. Report
the blocking reason and the excluded symbols instead.

## Validation Checklist

Before finishing, verify:

- The output CSV has only `symbol,rating`.
- Every rating is a finite float in `[-1, 1]`.
- At least 2 symbols are present.
- Every output symbol was verified as listed on Hyperliquid or XYZ.
- Every output symbol had enough completed hourly candles for RSI, MACD, and SMI.
- The file can be consumed by:

```bash
python3 construct_portfolio.py <input.csv>
```

## Primary References

- Hyperliquid API docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Hyperliquid info endpoint and candle snapshot docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Hyperliquid perpetual metadata docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- trade[XYZ] architecture docs: https://docs.trade.xyz/
- trade[XYZ] trading overview: https://docs.trade.xyz/trading/overview
