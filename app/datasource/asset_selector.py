"""
app/datasource/asset_selector.py

AssetSelector — scores stocks and crypto based on market status.

Logic:
  - When market is open: US_EQUITY + CRYPTO (Total Top N).
  - When market is closed: CRYPTO only (Top N).
  - Scores symbols by liquid, moving, volatile opportunity instead of raw size.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from math import floor
from typing import Any

import numpy as np
import pandas as pd
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from alpaca.data.requests import (
    StockBarsRequest,
    CryptoBarsRequest,
    StockLatestQuoteRequest,
    CryptoLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame

from app.datasource.alpaca_gateway import AlpacaGateway
from app.core.dynamic_risk import (
    dynamic_trade_budget,
    dynamic_crypto_liquidity_floor,
    dynamic_stock_liquidity_floor,
)
from app.utils.logger import logger
from app.utils.safe_number import safe_float
from config.settings import (
    DEFAULT_STOCK_UNIVERSE,
    DEFAULT_CRYPTO_UNIVERSE,
    ASSET_SELECTOR_TOP_N,
    SCORE_WEIGHT_VOLUME,
    SCORE_WEIGHT_MOMENTUM,
    SCORE_WEIGHT_VOLATILITY_EXPANSION,
    SCORE_WEIGHT_DOLLAR_VOLUME,
    SCORE_WEIGHT_TREND_STRENGTH,
    SCORE_WEIGHT_AFFORDABILITY,
    MAX_DOLLAR_PER_TRADE,
    ALLOW_FRACTIONAL_STOCK_QTY,
)
from config.risk_limits import (
    MAX_SPREAD_PCT,
    MAX_CRYPTO_SPREAD_PCT,
    MIN_AVG_DAILY_VOLUME,
    MIN_CRYPTO_DAILY_DOLLAR_VOLUME,
)


ASSET_SELECTOR_LOOKBACK_DAYS = 20
MAX_DYNAMIC_CRYPTO_SYMBOLS = 60
MAX_DYNAMIC_STOCK_SYMBOLS = 1200
STABLECOIN_BASES: frozenset[str] = frozenset({"USDC", "USDT", "USDG"})


class BaseAssetSelector(ABC):
    @abstractmethod
    def get_top_n_assets(self, n: int) -> list[str]:
        pass


class AlpacaAssetSelector(BaseAssetSelector):
    """
    Unified selector for Stocks and Crypto.
    """

    def __init__(self, gateway: AlpacaGateway) -> None:
        self._stock_client = gateway.stock_data_client
        self._crypto_client = gateway.crypto_data_client
        self._trading_client = gateway.trading_client
        self._last_top_n: list[str] = []
        self._last_score_had_metrics = False

    def get_top_n_assets(self, n: int = ASSET_SELECTOR_TOP_N) -> list[str]:
        try:
            # 1. Check if market is open
            clock = self._trading_client.get_clock()
            is_open = clock.is_open
            
            crypto_universe = self._crypto_universe()
            universe = list(crypto_universe)
            if is_open:
                logger.info("Market is OPEN. Scoring Stocks + Crypto.")
                stock_universe = self._stock_universe()
                universe += stock_universe
                logger.info(
                    "AssetSelector stock universe size={} (default+dynamic)",
                    len(stock_universe),
                )
            else:
                logger.info("Market is CLOSED. Scoring Crypto ONLY.")

            balance_context = self._balance_context()
            
            # 2. Compute hard/soft ranked candidates
            hard_scores, soft_scores = self._compute_ranked_candidates(universe, balance_context)
            if hard_scores.empty and soft_scores.empty:
                if self._last_score_had_metrics:
                    logger.warning(
                        "AssetSelector: no symbols passed hard liquidity/tradability gates."
                    )
                    return self._last_top_n[:n] if self._last_top_n else []
                return self._fallback(n, universe)

            hard_ranked = hard_scores.sort_values("score", ascending=False).index.tolist()
            soft_ranked = soft_scores.sort_values("score", ascending=False).index.tolist()
            top_n = self._fill_from_universe(hard_ranked + soft_ranked, [], n)
            if len(hard_ranked) < n and soft_ranked:
                logger.warning(
                    "AssetSelector: only {} hard-pass symbols; filled with {} soft-pass symbols.",
                    len(hard_ranked),
                    max(len(top_n) - len(hard_ranked), 0),
                )

            self._last_top_n = top_n
            logger.info("AssetSelector: top {} selected: {}", n, top_n)
            return top_n

        except Exception as exc:  # noqa: BLE001
            logger.error("AssetSelector failed: {}. Using fallback.", exc)
            return self._fallback(n, DEFAULT_CRYPTO_UNIVERSE)

    def _compute_scores(
        self,
        universe: list[str],
        balance_context: dict[str, float | None] | None = None,
    ) -> pd.DataFrame:
        hard_scores, _ = self._compute_ranked_candidates(universe, balance_context)
        return hard_scores

    def _compute_ranked_candidates(
        self,
        universe: list[str],
        balance_context: dict[str, float | None] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        universe = self._dedupe(universe)
        stocks = [s for s in universe if "/" not in s]
        cryptos = [s for s in universe if "/" in s]
        
        bars_map = {}
        if stocks:
            bars_map.update(self._fetch_stock_bars(stocks, days=ASSET_SELECTOR_LOOKBACK_DAYS))
        if cryptos:
            bars_map.update(self._fetch_crypto_bars(cryptos, days=ASSET_SELECTOR_LOOKBACK_DAYS))
            
        if not bars_map:
            self._last_score_had_metrics = False
            return pd.DataFrame()

        quote_map = {}
        if stocks:
            try:
                quote_map.update(self._fetch_stock_quotes(stocks))
            except Exception as exc:  # noqa: BLE001
                logger.warning("AssetSelector stock quote fetch failed: {}", exc)
        if cryptos:
            try:
                quote_map.update(self._fetch_crypto_quotes(cryptos))
            except Exception as exc:  # noqa: BLE001
                logger.warning("AssetSelector crypto quote fetch failed: {}", exc)

        hard_rows = []
        soft_rows = []
        metrics_seen = 0
        rejected = 0
        for symbol, df in bars_map.items():
            if df.empty or len(df) < 2:
                continue
            row = self._compute_symbol_metrics(symbol, df)
            if row:
                metrics_seen += 1
                row.update(quote_map.get(symbol, {}))
                tradability = self._tradability(
                    symbol,
                    row.get("spot_price"),
                    balance_context,
                )
                liquidity = self._liquidity_gate(symbol, row, balance_context)
                if not tradability["can_trade"]:
                    rejected += 1
                    logger.debug(
                        "AssetSelector skipping {}: price={} budget={} min_notional={} liquidity={}",
                        symbol,
                        tradability["spot_price"],
                        tradability["trade_budget"],
                        tradability["min_trade_notional"],
                        liquidity["reason"],
                    )
                    continue
                row.update(tradability)
                row.update(liquidity)
                if liquidity["is_liquid"]:
                    hard_rows.append(row)
                elif self._is_soft_liquidity_reason(str(liquidity.get("reason", ""))):
                    # Keep symbol available as lower-priority fallback instead of emptying the universe.
                    row["soft_liquidity_reason"] = liquidity.get("reason", "")
                    soft_rows.append(row)
                else:
                    rejected += 1
                    logger.debug(
                        "AssetSelector hard-liquidity skip {}: {}",
                        symbol,
                        liquidity.get("reason", ""),
                    )
                    continue

        self._last_score_had_metrics = metrics_seen > 0

        if not hard_rows and not soft_rows:
            if metrics_seen:
                logger.warning(
                    "AssetSelector: rejected {}/{} scored symbols with hard gates.",
                    rejected,
                    metrics_seen,
                )
            empty = pd.DataFrame()
            return empty, empty

        hard_metrics = self._score_rows(hard_rows)
        soft_metrics = self._score_rows(soft_rows)
        return hard_metrics, soft_metrics

    def _score_rows(self, rows: list[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        metrics = pd.DataFrame(rows).set_index("symbol")
        for col in [
            "recent_volume",
            "price_momentum",
            "vol_expansion",
            "dollar_volume",
            "trend_strength",
            "affordability",
        ]:
            metrics[col] = (
                pd.to_numeric(metrics[col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
            )
            metrics[f"{col}_n"] = metrics[col].rank(pct=True, method="average")

        metrics["score"] = (
            SCORE_WEIGHT_VOLUME             * metrics["recent_volume_n"]
            + SCORE_WEIGHT_MOMENTUM         * metrics["price_momentum_n"]
            + SCORE_WEIGHT_VOLATILITY_EXPANSION * metrics["vol_expansion_n"]
            + SCORE_WEIGHT_DOLLAR_VOLUME    * metrics["dollar_volume_n"]
            + SCORE_WEIGHT_TREND_STRENGTH   * metrics["trend_strength_n"]
            + SCORE_WEIGHT_AFFORDABILITY    * metrics["affordability_n"]
        )
        return metrics[["score", "spot_price", "trade_budget", "tradable_qty", "min_trade_notional"]]

    def _is_soft_liquidity_reason(self, reason: str) -> bool:
        text = str(reason).lower()
        return "dollar_volume_low" in text or "stock_volume_low" in text

    def _compute_symbol_metrics(self, symbol: str, df: pd.DataFrame) -> dict | None:
        try:
            closes = df["close"].astype(float)
            highs = df["high"].astype(float) if "high" in df else closes
            lows = df["low"].astype(float) if "low" in df else closes
            volumes = df["volume"].astype(float)
            if len(closes) < 5:
                return None

            recent_window = min(5, len(volumes))
            prior_window = min(10, max(len(volumes) - recent_window, 1))
            recent_volume_avg = safe_float(volumes.tail(recent_window).mean(), 0.0) or 0.0
            prior_volume_avg = safe_float(
                volumes.iloc[-(recent_window + prior_window):-recent_window].mean(),
                recent_volume_avg,
            ) or recent_volume_avg
            recent_volume = recent_volume_avg / prior_volume_avg if prior_volume_avg > 0 else recent_volume_avg
            
            momentum_window = min(10, len(closes) - 1)
            momentum_base = closes.iloc[-(momentum_window + 1)]
            raw_momentum = (closes.iloc[-1] - momentum_base) / momentum_base if momentum_base > 0 else 0.0
            rsi = self._rsi(closes)
            rsi_penalty = self._rsi_penalty(rsi)
            price_momentum = max(raw_momentum, 0.0) * rsi_penalty
            
            returns = closes.pct_change().dropna()
            if len(returns) >= 4:
                half = len(returns) // 2
                vol_recent = returns.iloc[half:].std()
                vol_prior  = returns.iloc[:half].std()
                vol_expansion = (vol_recent / vol_prior) if vol_prior > 0 else 1.0
            else:
                vol_expansion = 1.0

            dollar_volume = safe_float((closes.tail(recent_window) * volumes.tail(recent_window)).mean(), 0.0) or 0.0
            trend_consistency = float((returns > 0).sum()) / len(returns) if len(returns) > 0 else 0.5
            trend_strength = self._trend_strength(
                closes=closes,
                highs=highs,
                lows=lows,
                trend_consistency=trend_consistency,
                rsi=rsi,
            )

            return {
                "symbol": symbol,
                "spot_price": safe_float(closes.iloc[-1], 0.0) or 0.0,
                "avg_daily_volume": safe_float(volumes.tail(recent_window).mean(), 0.0) or 0.0,
                "recent_volume": recent_volume,
                "price_momentum": price_momentum,
                "vol_expansion": vol_expansion,
                "dollar_volume": dollar_volume,
                "trend_strength": trend_strength,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("AssetSelector metric calculation failed for {}: {}", symbol, exc)
            return None

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_stock_bars(self, symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
        start = datetime.now(tz=timezone.utc) - timedelta(days=days + 5)
        req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start, limit=days + 5)
        res = self._stock_client.get_stock_bars(req)
        return self._parse_barset(res, symbols)

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_crypto_bars(self, symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
        start = datetime.now(tz=timezone.utc) - timedelta(days=days + 5)
        req = CryptoBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start)
        res = self._crypto_client.get_crypto_bars(req)
        return self._parse_barset(res, symbols)

    def _parse_barset(self, bars_result, symbols: list[str]) -> dict[str, pd.DataFrame]:
        result: dict[str, pd.DataFrame] = {}
        data = bars_result.data if hasattr(bars_result, "data") else {}
        for sym in symbols:
            bar_list = data.get(sym, [])
            if not bar_list:
                continue
            records = [
                {
                    "timestamp": b.timestamp,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in bar_list
            ]
            df = pd.DataFrame(records)
            if not df.empty:
                df.set_index("timestamp", inplace=True)
                df.index = pd.to_datetime(df.index, utc=True)
                result[sym] = df.sort_index()
        return result

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_stock_quotes(self, symbols: list[str]) -> dict[str, dict]:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        res = self._stock_client.get_stock_latest_quote(req)
        return self._parse_quotes(res, symbols)

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3), reraise=True)
    def _fetch_crypto_quotes(self, symbols: list[str]) -> dict[str, dict]:
        req = CryptoLatestQuoteRequest(symbol_or_symbols=symbols)
        res = self._crypto_client.get_crypto_latest_quote(req)
        return self._parse_quotes(res, symbols)

    def _parse_quotes(self, quote_result, symbols: list[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        data = quote_result.data if hasattr(quote_result, "data") else quote_result
        for symbol in symbols:
            quote = self._symbol_payload(data, symbol)
            if not quote:
                continue
            bid = safe_float(self._field(quote, "bid_price")) or 0.0
            ask = safe_float(self._field(quote, "ask_price")) or 0.0
            if ask <= 0:
                continue
            spread = max(ask - bid, 0.0)
            result[symbol] = {
                "bid": bid,
                "ask": ask,
                "spread_pct": spread / ask,
            }
        return result

    def _fallback(self, n: int, universe: list[str]) -> list[str]:
        if self._last_top_n: return self._last_top_n[:n]
        return self._dedupe(universe)[:n]

    def _fill_from_universe(self, ranked: list[str], universe: list[str], n: int) -> list[str]:
        filled = self._dedupe(ranked)
        seen = {symbol.replace("/", "").replace("-", "") for symbol in filled}
        for symbol in self._dedupe(universe):
            key = symbol.replace("/", "").replace("-", "")
            if key in seen:
                continue
            filled.append(symbol)
            seen.add(key)
            if len(filled) >= n:
                break
        return filled[:n]

    def _crypto_universe(self) -> list[str]:
        dynamic = self._fetch_tradable_crypto_symbols()
        return self._dedupe_crypto_bases(self._dedupe(list(DEFAULT_CRYPTO_UNIVERSE) + dynamic))

    def _stock_universe(self) -> list[str]:
        dynamic = self._fetch_tradable_stock_symbols()
        return self._dedupe(list(DEFAULT_STOCK_UNIVERSE) + dynamic)

    def _balance_context(self) -> dict[str, float | None]:
        try:
            account = self._trading_client.get_account()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AssetSelector account balance fetch failed: {}", exc)
            return {
                "buying_power": None,
                "trade_budget": MAX_DOLLAR_PER_TRADE,
            }

        buying_power = (
            safe_float(getattr(account, "buying_power", None))
            or safe_float(getattr(account, "cash", None))
            or safe_float(getattr(account, "portfolio_value", None))
        )
        if buying_power is None or buying_power <= 0:
            return {
                "buying_power": buying_power,
                "trade_budget": 0.0,
            }

        account_context = {"buying_power": buying_power}
        return {
            "buying_power": buying_power,
            "trade_budget": dynamic_trade_budget(account_context),
        }

    def _tradability(
        self,
        symbol: str,
        spot_price: Any,
        balance_context: dict[str, float | None] | None,
    ) -> dict[str, float | bool | None]:
        price = safe_float(spot_price, 0.0) or 0.0
        budget = safe_float((balance_context or {}).get("trade_budget"), MAX_DOLLAR_PER_TRADE) or 0.0
        min_qty = 0.0001 if "/" in str(symbol) else (0.0001 if ALLOW_FRACTIONAL_STOCK_QTY else 1.0)
        min_trade_notional = price * min_qty if price > 0 else 0.0

        if price <= 0 or budget <= 0:
            tradable_qty = 0.0
        elif "/" in str(symbol):
            tradable_qty = floor((budget / price) * 10_000) / 10_000
        elif ALLOW_FRACTIONAL_STOCK_QTY:
            tradable_qty = floor((budget / price) * 10_000) / 10_000
        else:
            tradable_qty = float(int(budget / price))

        can_trade = tradable_qty >= min_qty and min_trade_notional <= budget
        lots_affordable = tradable_qty / min_qty if min_qty > 0 else 0.0
        affordability = float(np.clip(lots_affordable / 5.0, 0.0, 1.0))

        return {
            "can_trade": can_trade,
            "spot_price": price,
            "trade_budget": budget,
            "tradable_qty": tradable_qty,
            "min_trade_notional": min_trade_notional,
            "affordability": affordability,
        }

    def _fetch_tradable_crypto_symbols(self) -> list[str]:
        try:
            assets = self._trading_client.get_all_assets()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AssetSelector crypto asset discovery failed: {}", exc)
            return []

        if not isinstance(assets, (list, tuple)):
            return []

        symbols: list[str] = []
        for asset in assets:
            if not self._is_tradable_crypto(asset):
                continue
            symbol = self._normalize_crypto_symbol(getattr(asset, "symbol", ""))
            if symbol and self._is_useful_crypto_symbol(symbol):
                symbols.append(symbol)
            if len(symbols) >= MAX_DYNAMIC_CRYPTO_SYMBOLS:
                break
        return symbols

    def _fetch_tradable_stock_symbols(self) -> list[str]:
        try:
            assets = self._trading_client.get_all_assets()
        except Exception as exc:  # noqa: BLE001
            logger.debug("AssetSelector stock asset discovery failed: {}", exc)
            return []

        if not isinstance(assets, (list, tuple)):
            return []

        symbols: list[str] = []
        for asset in assets:
            if not self._is_tradable_stock(asset):
                continue
            symbol = str(getattr(asset, "symbol", "") or "").upper()
            if not symbol or "/" in symbol:
                continue
            symbols.append(symbol)
            if len(symbols) >= MAX_DYNAMIC_STOCK_SYMBOLS:
                break
        return symbols

    def _liquidity_gate(
        self,
        symbol: str,
        row: dict,
        balance_context: dict[str, float | None] | None = None,
    ) -> dict[str, bool | str | float]:
        spread_pct = safe_float(row.get("spread_pct"))
        is_crypto = "/" in str(symbol)
        max_spread = MAX_CRYPTO_SPREAD_PCT if is_crypto else MAX_SPREAD_PCT
        buying_power = safe_float((balance_context or {}).get("buying_power"))
        account_ctx = {"buying_power": buying_power} if buying_power is not None else None

        if spread_pct is None:
            return {"is_liquid": False, "reason": "quote_unavailable"}
        if spread_pct > max_spread:
            return {
                "is_liquid": False,
                "reason": f"spread_too_wide:{spread_pct:.4f}>{max_spread:.4f}",
            }

        if is_crypto:
            dollar_volume = safe_float(row.get("dollar_volume"), 0.0) or 0.0
            min_dollar_volume = dynamic_crypto_liquidity_floor(account_ctx)
            min_dollar_volume = max(min_dollar_volume, MIN_CRYPTO_DAILY_DOLLAR_VOLUME * 0.05)
            if dollar_volume < min_dollar_volume:
                return {
                    "is_liquid": False,
                    "reason": f"crypto_dollar_volume_low:{dollar_volume:.0f}<{min_dollar_volume:.0f}",
                }
        else:
            volume = safe_float(row.get("avg_daily_volume"), 0.0) or 0.0
            min_volume = dynamic_stock_liquidity_floor(account_ctx)
            min_volume = max(min_volume, MIN_AVG_DAILY_VOLUME * 0.2)
            if volume < min_volume:
                return {
                    "is_liquid": False,
                    "reason": f"stock_volume_low:{volume:.0f}<{min_volume:.0f}",
                }

        return {"is_liquid": True, "reason": ""}

    def _is_tradable_crypto(self, asset: Any) -> bool:
        asset_class = str(self._value(getattr(asset, "asset_class", ""))).lower()
        status = str(self._value(getattr(asset, "status", "active"))).lower()
        if "crypto" not in asset_class:
            return False
        if status not in {"active", ""}:
            return False
        return bool(getattr(asset, "tradable", True))

    def _is_tradable_stock(self, asset: Any) -> bool:
        asset_class = str(self._value(getattr(asset, "asset_class", ""))).lower()
        status = str(self._value(getattr(asset, "status", "active"))).lower()
        if "us_equity" not in asset_class:
            return False
        if status not in {"active", ""}:
            return False
        return bool(getattr(asset, "tradable", True))

    def _normalize_crypto_symbol(self, symbol: Any) -> str:
        text = str(symbol or "").upper().replace("-", "/")
        if not text:
            return ""
        if "/" in text:
            return text
        for quote in ("USDT", "USD"):
            if text.endswith(quote) and len(text) > len(quote):
                return f"{text[:-len(quote)]}/{quote}"
        return ""

    def _is_useful_crypto_symbol(self, symbol: str) -> bool:
        parts = str(symbol).upper().split("/")
        if len(parts) != 2:
            return False
        base, quote = parts
        if base in STABLECOIN_BASES:
            return False
        return quote in {"USD", "USDC", "USDT"}

    def _dedupe_crypto_bases(self, symbols: list[str]) -> list[str]:
        selected: dict[str, str] = {}
        quote_rank = {"USD": 0, "USDC": 1, "USDT": 2}

        for symbol in symbols:
            parts = str(symbol).upper().split("/")
            if len(parts) != 2:
                continue
            base, quote = parts
            if base in STABLECOIN_BASES:
                continue
            current = selected.get(base)
            if current is None:
                selected[base] = f"{base}/{quote}"
                continue
            current_quote = current.split("/", 1)[1]
            if quote_rank.get(quote, 99) < quote_rank.get(current_quote, 99):
                selected[base] = f"{base}/{quote}"

        return list(selected.values())

    def _trend_strength(
        self,
        closes: pd.Series,
        highs: pd.Series,
        lows: pd.Series,
        trend_consistency: float,
        rsi: float | None,
    ) -> float:
        lookback = min(20, len(closes))
        recent_high = safe_float(highs.tail(lookback).max())
        recent_low = safe_float(lows.tail(lookback).min())
        latest = safe_float(closes.iloc[-1])
        if latest is None or recent_high is None or recent_low is None or recent_high <= recent_low:
            breakout_score = 0.5
        else:
            range_position = (latest - recent_low) / (recent_high - recent_low)
            breakout_score = float(np.clip(1.0 - abs(range_position - 0.82) / 0.82, 0.0, 1.0))

        rsi_score = 0.5 if rsi is None else self._rsi_penalty(rsi)
        return (
            0.50 * float(np.clip(trend_consistency, 0.0, 1.0))
            + 0.30 * breakout_score
            + 0.20 * rsi_score
        )

    def _rsi(self, closes: pd.Series, period: int = 14) -> float | None:
        if len(closes) <= period:
            return None
        delta = closes.diff().dropna()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)
        avg_gain = safe_float(gains.tail(period).mean(), 0.0) or 0.0
        avg_loss = safe_float(losses.tail(period).mean(), 0.0) or 0.0
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _rsi_penalty(self, rsi: float | None) -> float:
        if rsi is None:
            return 0.8
        if 45.0 <= rsi <= 70.0:
            return 1.0
        if 35.0 <= rsi < 45.0 or 70.0 < rsi <= 78.0:
            return 0.7
        return 0.35

    def _dedupe(self, symbols: list[str]) -> list[str]:
        result = []
        seen = set()
        for symbol in symbols:
            if not symbol:
                continue
            key = str(symbol).upper().replace("/", "").replace("-", "")
            if key in seen:
                continue
            seen.add(key)
            result.append(str(symbol).upper())
        return result

    def _value(self, value: Any) -> str:
        return str(value.value) if hasattr(value, "value") else str(value)

    def _symbol_payload(self, data: object, symbol: str):
        if not isinstance(data, dict):
            return data
        if symbol in data:
            return data[symbol]

        wanted = symbol.upper().replace("/", "")
        for key, value in data.items():
            if str(key).upper().replace("/", "") == wanted:
                return value
        return None

    def _field(self, payload: object, name: str):
        if isinstance(payload, dict):
            return payload.get(name)
        return getattr(payload, name, None)
