"""Finance Pack: curated ladder extractors for structured financial data.

Architecture: LadderWalker walks ranked source rungs (curated URLs + regex selectors
from config/finance_sources.yaml), validates required fields, and returns the first
rung that answers. FinanceRenderer produces fixed markdown output. Six extractor
functions call walk() and post-process for their field set.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml
import structlog

logger = structlog.get_logger()

_SOURCES_PATH = Path(__file__).resolve().parent.parent / "config" / "finance_sources.yaml"
_SOURCES: Optional[Dict[str, Any]] = None

# Stale ERP cache — Damodaran updates ~annually; hard-fail is wrong
_ERP_STALE_CACHE: Dict[str, Dict[str, Any]] = {}

CACHE_TTL = {
    "consensus": 21600,
    "insider": 21600,
    "corp_actions": 21600,
    "macro": 86400,
    "erp": 86400,
    "snapshot_us": 3600,
}


def _load_sources() -> Dict[str, Any]:
    global _SOURCES
    if _SOURCES is None:
        with open(_SOURCES_PATH, "r") as f:
            _SOURCES = yaml.safe_load(f)
    return _SOURCES


def _reload_sources() -> Dict[str, Any]:
    """Force-reload finance_sources.yaml (used after calibration edits)."""
    global _SOURCES
    _SOURCES = None
    return _load_sources()


class LadderExhausted(Exception):
    def __init__(self, endpoint: str, symbol: str, tried: List[str]):
        self.endpoint = endpoint
        self.symbol = symbol
        self.tried = tried
        super().__init__(f"{endpoint}/{symbol}: all rungs failed ({tried})")


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_field(text: str, selector: Dict[str, Any]) -> Optional[str]:
    """Apply a regex selector against raw text; return first capture group or None."""
    if selector.get("type") != "regex":
        return None
    pattern = selector.get("pattern", "")
    if not pattern:
        return None
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return None
    try:
        return m.group(1).strip()
    except IndexError:
        return m.group(0).strip()


def _parse_as_of(text: str, selector: Dict[str, Any]) -> Optional[str]:
    """Extract and normalise an as-of date string from raw text."""
    raw = _extract_field(text, selector)
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y",
                "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d",
                "%B %Y", "%b %Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    # Unix timestamp fallback (Yahoo Finance style)
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw)).date().isoformat()
        except Exception:
            pass
    # Return raw if unparseable — still better than nothing
    return raw


def _confidence(rung_name: str, as_of_str: Optional[str], freshness_max_days: int) -> str:
    if rung_name == "search_fallback":
        return "low"
    if as_of_str:
        try:
            as_of = date.fromisoformat(as_of_str)
            age = (date.today() - as_of).days
            if age <= freshness_max_days:
                return "high"
            return "medium"
        except Exception:
            pass
    return "medium"


# ---------------------------------------------------------------------------
# LadderWalker
# ---------------------------------------------------------------------------

class LadderWalker:
    """Walks curated source rungs, returns first rung that validates."""

    def __init__(self, fetch_service, search_service):
        self._fetch = fetch_service
        self._search = search_service

    async def walk(
        self,
        endpoint: str,
        market: str,
        symbol: str,
        required_fields: List[str],
        extra_selectors: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], str, str]:
        """Walk rungs, return (data_dict, rung_name, confidence)."""
        sources = _load_sources()
        rungs = sources.get(endpoint, {}).get(market)
        if not rungs:
            raise LadderExhausted(endpoint, symbol, [f"no rungs for {market}"])

        tried: List[str] = []
        for rung in rungs:
            rung_name = rung["name"]
            tried.append(rung_name)
            freshness = rung.get("freshness_max_days", 7)
            try:
                if rung_name == "search_fallback":
                    data, as_of = await self._search_rung(rung, symbol, required_fields)
                else:
                    data, as_of = await self._fetch_rung(rung, symbol, extra_selectors)

                missing = [f for f in required_fields if not data.get(f)]
                if missing:
                    logger.info("finance_ladder_miss", endpoint=endpoint, rung=rung_name,
                                symbol=symbol, missing=missing)
                    continue

                conf = _confidence(rung_name, as_of, freshness)
                data["_as_of"] = as_of
                data["_source"] = rung.get("url", rung_name).split("/")[2] if "url" in rung else rung_name
                logger.info("finance_ladder_hit", endpoint=endpoint, rung=rung_name,
                            symbol=symbol, confidence=conf)
                return data, rung_name, conf

            except Exception as exc:
                logger.warning("finance_ladder_rung_error", endpoint=endpoint, rung=rung_name,
                               symbol=symbol, error=str(exc))
                continue

        raise LadderExhausted(endpoint, symbol, tried)

    async def walk_merge(
        self,
        endpoint: str,
        market: str,
        symbol: str,
        required_fields: List[str],
        optional_fields: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], str, str]:
        """Walk all rungs and merge fields — for endpoints spanning multiple sources."""
        sources = _load_sources()
        rungs = sources.get(endpoint, {}).get(market)
        if not rungs:
            raise LadderExhausted(endpoint, symbol, [f"no rungs for {market}"])

        optional_fields = optional_fields or []
        merged: Dict[str, Any] = {}
        as_of: Optional[str] = None
        primary_rung: Optional[str] = None
        conf = "medium"
        tried: List[str] = []

        for rung in rungs:
            rung_name = rung["name"]
            if rung_name == "search_fallback":
                continue
            tried.append(rung_name)
            freshness = rung.get("freshness_max_days", 7)
            try:
                if rung.get("search_snippet"):
                    data, rung_as_of = await self._search_snippet_rung(rung, symbol, market)
                else:
                    data, rung_as_of = await self._fetch_rung(rung, symbol, market=market)

                for field, val in data.items():
                    if val and not merged.get(field):
                        merged[field] = val
                if rung_as_of and not as_of:
                    as_of = rung_as_of

                if primary_rung is None and all(merged.get(f) for f in required_fields):
                    primary_rung = rung_name
                    conf = _confidence(rung_name, rung_as_of, freshness)
            except Exception as exc:
                logger.warning(
                    "finance_ladder_rung_error",
                    endpoint=endpoint,
                    rung=rung_name,
                    symbol=symbol,
                    error=str(exc),
                )
                continue

        missing_required = [f for f in required_fields if not merged.get(f)]
        if missing_required:
            for rung in rungs:
                if rung.get("name") != "search_fallback":
                    continue
                tried.append("search_fallback")
                try:
                    need = missing_required + [f for f in optional_fields if not merged.get(f)]
                    data, rung_as_of = await self._search_rung(rung, symbol, need)
                    for field, val in data.items():
                        if val and not merged.get(field):
                            merged[field] = val
                    if rung_as_of and not as_of:
                        as_of = rung_as_of
                    if primary_rung is None and all(merged.get(f) for f in required_fields):
                        primary_rung = "search_fallback"
                        conf = "low"
                except Exception as exc:
                    logger.warning(
                        "finance_ladder_rung_error",
                        endpoint=endpoint,
                        rung="search_fallback",
                        symbol=symbol,
                        error=str(exc),
                    )
                break
            missing_required = [f for f in required_fields if not merged.get(f)]
            if missing_required:
                raise LadderExhausted(endpoint, symbol, tried)

        if primary_rung is None:
            primary_rung = tried[0] if tried else "merged"

        merged["_as_of"] = as_of
        rung_obj = next((r for r in rungs if r.get("name") == primary_rung), {})
        source_url = rung_obj.get("url", primary_rung)
        merged["_source"] = source_url.split("/")[2] if "://" in str(source_url) else primary_rung
        logger.info(
            "finance_ladder_merge_hit",
            endpoint=endpoint,
            symbol=symbol,
            primary_rung=primary_rung,
            fields=list(merged.keys()),
        )
        return merged, primary_rung, conf

    @staticmethod
    def _rung_format_vars(symbol: str, market: str) -> Dict[str, str]:
        sym = symbol.upper()
        mkt = market.upper()
        slug_map = {"IN": "india", "US": "united-states"}
        return {
            "symbol": sym,
            "country": mkt,
            "country_slug": slug_map.get(mkt, market.lower()),
        }

    def _format_rung_value(self, template: Any, symbol: str, market: str) -> Any:
        """Recursively format {symbol}/{country} placeholders in rung config values."""
        vars_ = self._rung_format_vars(symbol, market)
        if isinstance(template, str):
            return template.format(**vars_)
        if isinstance(template, dict):
            return {k: self._format_rung_value(v, symbol, market) for k, v in template.items()}
        if isinstance(template, list):
            return [self._format_rung_value(v, symbol, market) for v in template]
        return template

    async def _resolve_moneycontrol_sc_id(self, symbol: str) -> str:
        """Map NSE ticker (RELIANCE) to Moneycontrol scId (RI) via autosuggest."""
        sym = symbol.upper()
        if 1 <= len(sym) <= 5 and sym.isalpha():
            return sym
        url = (
            "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
            f"?classic=true&query={sym}&type=1&format=json"
        )
        resp = await self._fetch.request(
            "GET", url, headers={"Referer": "https://www.moneycontrol.com/"}, timeout=15000
        )
        text = resp.get("text", "") or ""
        if resp.get("status", 0) not in range(200, 300) or not text:
            raise ValueError(f"Moneycontrol autosuggest HTTP {resp.get('status')}")
        m = re.search(r'"link_src":"[^"]+/([A-Z]{1,5})"', text)
        if not m:
            raise ValueError(f"Moneycontrol scId not found for {sym}")
        return m.group(1)

    async def _fetch_rung(
        self,
        rung: Dict[str, Any],
        symbol: str,
        extra_selectors: Optional[Dict[str, Any]] = None,
        market: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        mkt = (market or symbol).upper()
        sym = symbol.upper()
        if rung.get("moneycontrol_sc_id"):
            sym = await self._resolve_moneycontrol_sc_id(symbol)
        vars_ = self._rung_format_vars(sym, mkt)
        url = rung["url"].format(**vars_)
        headers = dict(rung.get("headers", {}))
        method = (rung.get("method") or "GET").upper()
        json_body = self._format_rung_value(rung.get("json_body"), sym, mkt)
        resp = await self._fetch.request(
            method, url, headers=headers, json_body=json_body, timeout=20000
        )
        text = resp.get("text", "") or ""
        if not text or resp.get("status", 0) not in range(200, 300):
            raise ValueError(f"HTTP {resp.get('status')} from {url}")

        # Optional supplemental Moneycontrol estimate endpoints (same scId).
        for sup_key, sup_path in (rung.get("moneycontrol_supplements") or {}).items():
            sup_url = f"https://api.moneycontrol.com/mcapi/v1/stock/estimates/{sup_path}"
            sup_url = sup_url.format(symbol=sym, sc_id=sym)
            sup_resp = await self._fetch.request(
                "GET", sup_url, headers=headers, timeout=15000
            )
            sup_text = sup_resp.get("text", "") or ""
            if sup_resp.get("status", 0) in range(200, 300) and sup_text:
                text += "\n" + sup_text

        selectors = dict(rung.get("selectors", {}))
        if extra_selectors:
            selectors.update(extra_selectors)

        data: Dict[str, Any] = {}
        for field, sel in selectors.items():
            val = _extract_field(text, sel)
            if val:
                data[field] = val

        as_of_sel = rung.get("as_of")
        as_of = _parse_as_of(text, as_of_sel) if as_of_sel else None
        return data, as_of

    async def _search_snippet_rung(
        self,
        rung: Dict[str, Any],
        symbol: str,
        market: str,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Lightweight search rung — snippets only, no page extraction."""
        query = self._format_rung_value(rung["query"], symbol, market)
        result = await self._search.search(query, max_results=rung.get("max_results", 8))
        if not result.get("success"):
            raise ValueError(f"search failed: {result.get('error')}")
        results = result.get("results", [])
        if not results:
            raise ValueError("search returned no results")

        all_text = " ".join(
            f"{r.get('title', '')} {r.get('snippet', '')}" for r in results
        )
        data: Dict[str, Any] = {}
        for field, sel in (rung.get("selectors") or {}).items():
            val = _extract_field(all_text, sel)
            if val:
                data[field] = val
        if not data:
            raise ValueError("no fields extracted from search snippets")
        return data, None

    async def _search_rung(
        self,
        rung: Dict[str, Any],
        symbol: str,
        required_fields: List[str],
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        query = rung["query"].format(symbol=symbol.upper())
        result = await self._search.search(query, max_results=5)
        if not result.get("success"):
            raise ValueError(f"search failed: {result.get('error')}")

        results = result.get("results", [])
        if not results:
            raise ValueError("search returned no results")

        urls = [r["url"] for r in results[:3]]
        extracted = await self._search.deep_extract(
            urls=urls,
            content_mode="reader",
            max_text_length=6000,
            refine_query=query,
        )

        # Collect all text from successful extracts
        all_text = " ".join(
            r.get("content", "") for r in extracted.get("results", []) if r.get("success")
        )
        # Also include search snippets
        all_text += " ".join(r.get("snippet", "") for r in results)

        data: Dict[str, Any] = {}
        as_of: Optional[str] = None
        # Try to extract required fields from aggregated text using generic patterns
        for field in required_fields:
            val = _generic_extract(field, all_text)
            if val:
                data[field] = val

        return data, as_of


def _generic_extract(field: str, text: str) -> Optional[str]:
    """Best-effort extraction for search-rung text using field-name heuristics."""
    patterns = {
        "pt_mean": r'(?i)(?:target|mean)[^₹$\d]*([$₹]?\s*[\d,]+(?:\.\d+)?)',
        "pt_high": r'(?i)(?:high|maximum)[^₹$\d]*([$₹]?\s*[\d,]+(?:\.\d+)?)',
        "pt_low": r'(?i)(?:low|minimum)[^₹$\d]*([$₹]?\s*[\d,]+(?:\.\d+)?)',
        "analyst_count": r'(\d+)\s+(?:analyst|broker|recommendation)',
        "yield_10y": r'(?i)10.year[^%\d]*([\d.]+)\s*%',
        "cds_spread": r'(?i)CDS[^bpsd\d]*([\d.]+)\s*(?:bps?|basis)',
        "fx_usd_inr": r'(?i)USD[/.]?INR[^.\d]*([\d.]+)',
        "price": r'(?i)(?:price|trading)[^$₹\d]*([$₹]?\s*[\d,]+(?:\.\d+)?)',
        "erp_country": r'(?i)(?:ERP|equity risk)[^%\d]*([\d.]+)\s*%',
    }
    pattern = patterns.get(field)
    if not pattern:
        return None
    m = re.search(pattern, text, re.DOTALL)
    if m:
        try:
            return m.group(1).strip()
        except IndexError:
            return m.group(0).strip()
    return None


# ---------------------------------------------------------------------------
# FinanceRenderer — fixed markdown output shape
# ---------------------------------------------------------------------------

class FinanceRenderer:

    @staticmethod
    def render(
        endpoint: str,
        symbol: str,
        market: str,
        rung_name: str,
        source: str,
        as_of: Optional[str],
        confidence: str,
        fields: List[Tuple[str, str]],
        missing: List[Tuple[str, str]],
        degraded: bool = False,
    ) -> str:
        label = symbol.upper() if symbol else market.upper()
        header_parts = [f"## {endpoint} · {label} · {market.upper()}"]
        if degraded:
            header_parts.append("degraded: true")

        meta_parts = [f"source: {source}"]
        if as_of:
            meta_parts.append(f"as-of: {as_of}")
        meta_parts.append(f"confidence: {confidence}")
        meta = " · ".join(meta_parts)

        rows = [f"| field | value |", f"|---|---|"]
        for field, value in fields:
            rows.append(f"| {field} | {value} |")

        missing_lines = [f"MISSING: {field} — {reason}" for field, reason in missing]

        parts = ["\n".join(header_parts), meta, "\n".join(rows)]
        if missing_lines:
            parts.append("\n".join(missing_lines))

        return "\n\n".join(parts)

    @staticmethod
    def render_exhausted(
        endpoint: str,
        symbol: str,
        market: str,
        required_fields: List[str],
        tried: List[str],
    ) -> str:
        label = symbol.upper() if symbol else market.upper()
        header = f"## {endpoint} · {label} · {market.upper()}"
        meta = f"source: none · as-of: unknown · confidence: none"
        missing_lines = "\n".join(
            f"MISSING: {f} — ladder exhausted (tried: {', '.join(tried)})"
            for f in required_fields
        )
        return f"{header}\n{meta}\n\n{missing_lines}"


# ---------------------------------------------------------------------------
# FinanceService — top-level class wiring cache + extractors
# ---------------------------------------------------------------------------

class FinanceService:

    def __init__(self, fetch_service, search_service, cache_service):
        self._walker = LadderWalker(fetch_service, search_service)
        self._cache = cache_service
        self._renderer = FinanceRenderer()

    def _cache_key(self, endpoint: str, symbol: str, market: str) -> str:
        return f"finance:{endpoint}:{symbol.upper()}:{market.upper()}"

    async def _get_cached(self, key: str) -> Optional[str]:
        try:
            return await self._cache.get(key)
        except Exception:
            return None

    async def _set_cached(self, key: str, value: str, ttl: int) -> None:
        try:
            await self._cache.set(key, value, ttl=ttl)
        except Exception:
            pass

    # ---- consensus ---------------------------------------------------------

    async def consensus(self, symbol: str, market: str = "IN") -> Dict[str, Any]:
        key = self._cache_key("consensus", symbol, market)
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["pt_mean", "analyst_count"]
        currency = "₹" if market == "IN" else "$"
        try:
            data, rung, conf = await self._walker.walk(
                "consensus", market, symbol, required_fields=required
            )
            fields = [
                ("PT mean", f"{currency}{data.get('pt_mean', 'N/A')}"),
                ("PT high", f"{currency}{data.get('pt_high', 'N/A')}"),
                ("PT low", f"{currency}{data.get('pt_low', 'N/A')}"),
                ("analysts", data.get("analyst_count", "N/A")),
                ("FY EPS est", f"{currency}{data.get('fy_eps_1', 'N/A')}"),
            ]
            missing = [
                (f, "not extracted") for f in ["pt_high", "pt_low", "fy_eps_1"]
                if not data.get(f)
            ]
            md = self._renderer.render(
                "finance_consensus", symbol, market,
                rung, data["_source"], data["_as_of"], conf,
                fields, missing,
            )
        except LadderExhausted as e:
            md = self._renderer.render_exhausted(
                "finance_consensus", symbol, market,
                ["pt_mean", "pt_range", "analyst_count", "FY EPS est"], e.tried
            )

        await self._set_cached(key, md, CACHE_TTL["consensus"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- insider -----------------------------------------------------------

    async def insider(self, symbol: str, market: str = "IN") -> Dict[str, Any]:
        key = self._cache_key("insider", symbol, market)
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["transactions"]
        try:
            data, rung, conf = await self._walker.walk(
                "insider", market, symbol, required_fields=required
            )
            fields = [
                ("transactions (raw)", data.get("transactions", "N/A")),
                ("promoter pledge %", data.get("promoter_pledge", data.get("pledge_pct", "N/A"))),
            ]
            missing = [("pledge %", "not found")] if not data.get("promoter_pledge") and not data.get("pledge_pct") else []
            md = self._renderer.render(
                "finance_insider", symbol, market,
                rung, data["_source"], data["_as_of"], conf,
                fields, missing,
            )
        except LadderExhausted as e:
            md = self._renderer.render_exhausted(
                "finance_insider", symbol, market,
                ["transactions", "pledge %"], e.tried
            )

        await self._set_cached(key, md, CACHE_TTL["insider"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- corp_actions ------------------------------------------------------

    async def corp_actions(self, symbol: str, market: str = "IN") -> Dict[str, Any]:
        key = self._cache_key("corp_actions", symbol, market)
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["actions"]
        try:
            data, rung, conf = await self._walker.walk(
                "corp_actions", market, symbol, required_fields=required
            )
            fields = [
                ("actions (raw)", data.get("actions", "N/A")),
            ]
            md = self._renderer.render(
                "finance_corp_actions", symbol, market,
                rung, data["_source"], data["_as_of"], conf,
                fields, [],
            )
        except LadderExhausted as e:
            md = self._renderer.render_exhausted(
                "finance_corp_actions", symbol, market,
                ["action type", "announce date", "size/ratio"], e.tried
            )

        await self._set_cached(key, md, CACHE_TTL["corp_actions"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- macro -------------------------------------------------------------

    async def macro(self, country: str = "IN") -> Dict[str, Any]:
        key = self._cache_key("macro", "", country)
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["yield_10y"]
        optional = ["cds_spread", "fx_usd_inr", "fx_implied_vol"]
        try:
            data, rung, conf = await self._walker.walk_merge(
                "macro", country, country,
                required_fields=required,
                optional_fields=optional,
            )
            vol = data.get("fx_implied_vol")
            if vol and not str(vol).endswith("%"):
                vol = f"{vol}%"
            fields = [
                ("10Y sovereign yield", f"{data.get('yield_10y', 'N/A')}%"),
                ("CDS spread", f"{data.get('cds_spread', 'N/A')} bps"),
                ("FX USD/local", data.get("fx_usd_inr", "N/A")),
                ("FX implied vol", vol or "N/A"),
            ]
            missing = []
            if not data.get("cds_spread"):
                missing.append(("CDS spread", "not found"))
            if not data.get("fx_usd_inr"):
                missing.append(("FX spot", "not found on primary rung"))
            if not data.get("fx_implied_vol"):
                missing.append(("FX implied vol", "not found — search snippet rung missed"))
            md = self._renderer.render(
                "finance_macro", country, country,
                rung, data["_source"], data["_as_of"], conf,
                fields, missing,
            )
        except LadderExhausted as e:
            md = self._renderer.render_exhausted(
                "finance_macro", country, country,
                ["10Y yield", "CDS spread", "FX spot", "FX implied vol"], e.tried
            )

        await self._set_cached(key, md, CACHE_TTL["macro"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- erp ---------------------------------------------------------------

    async def erp(self, home: str = "IN", foreign: str = "US") -> Dict[str, Any]:
        key = self._cache_key("erp", foreign, home)
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["erp_country"]
        stale_key = f"{home}:{foreign}"
        try:
            data, rung, conf = await self._walker.walk(
                "erp", home, home, required_fields=required
            )
            _ERP_STALE_CACHE[stale_key] = {"data": data, "rung": rung, "conf": conf}
        except LadderExhausted as e:
            if stale_key in _ERP_STALE_CACHE:
                cached_erp = _ERP_STALE_CACHE[stale_key]
                data = cached_erp["data"]
                rung = cached_erp["rung"]
                conf = "medium"
                logger.info("finance_erp_stale_cache_hit", home=home, foreign=foreign)
            else:
                md = self._renderer.render_exhausted(
                    "finance_erp", home, foreign,
                    ["ERP home", "ERP mature", "country default spread"], e.tried
                )
                return {"success": True, "markdown": md, "cached": False}

        fields = [
            ("ERP home", f"{data.get('erp_country', 'N/A')}%"),
            ("ERP mature market", f"{data.get('erp_mature', 'N/A')}%"),
            ("country default spread", f"{data.get('default_spread', 'N/A')}%"),
            ("vintage", data.get("_as_of", "N/A")),
        ]
        missing = []
        if not data.get("erp_mature"):
            missing.append(("ERP mature", "not extracted — check Damodaran page structure"))
        if not data.get("default_spread"):
            missing.append(("default spread", "not extracted"))

        md = self._renderer.render(
            "finance_erp", f"{home}/{foreign}", foreign,
            rung, data["_source"], data["_as_of"], conf,
            fields, missing,
        )

        await self._set_cached(key, md, CACHE_TTL["erp"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- snapshot_us -------------------------------------------------------

    async def snapshot_us(self, symbol: str) -> Dict[str, Any]:
        key = self._cache_key("snapshot_us", symbol, "US")
        cached = await self._get_cached(key)
        if cached:
            return {"success": True, "markdown": cached, "cached": True}

        required = ["price"]
        try:
            data, rung, conf = await self._walker.walk(
                "snapshot_us", "US", symbol, required_fields=required
            )
            price = data.get("price", "N/A")
            # pct_off_52w selector captures 52-week high; convert to % below high.
            if data.get("pct_off_52w") and data.get("price"):
                try:
                    hi = float(str(data["pct_off_52w"]).replace(",", ""))
                    px = float(str(data["price"]).replace(",", ""))
                    if hi > 0:
                        data["pct_off_52w"] = f"{round((hi - px) / hi * 100, 2)}"
                except Exception:
                    pass
            mktcap = data.get("mktcap", "N/A")
            fields = [
                ("price", f"${price}"),
                ("mktcap", mktcap),
                ("% off 52w", f"{data.get('pct_off_52w', 'N/A')}%"),
                ("P/E", data.get("pe_ratio", "N/A")),
                ("shares outstanding", data.get("shares_outstanding", "N/A")),
            ]
            missing = [
                (f, "not extracted") for f, k in [
                    ("mktcap", "mktcap"), ("% off 52w", "pct_off_52w"),
                    ("P/E", "pe_ratio"), ("shares outstanding", "shares_outstanding"),
                ] if not data.get(k)
            ]
            md = self._renderer.render(
                "finance_snapshot_us", symbol, "US",
                rung, data["_source"], data["_as_of"], conf,
                fields, missing, degraded=True,
            )
        except LadderExhausted as e:
            md = self._renderer.render_exhausted(
                "finance_snapshot_us", symbol, "US",
                ["price", "mktcap", "% off 52w", "P/E", "shares outstanding"], e.tried
            )

        await self._set_cached(key, md, CACHE_TTL["snapshot_us"])
        return {"success": True, "markdown": md, "cached": False}

    # ---- ladder probe (for health check) -----------------------------------

    async def probe_ladder(self, endpoint: str, symbol: str, market: str) -> Dict[str, Any]:
        """Probe a single rung without returning structured data — for health checks."""
        sources = _load_sources()
        rungs = sources.get(endpoint, {}).get(market, [])
        results = []
        for rung in rungs:
            rung_name = rung["name"]
            if rung_name == "search_fallback" or rung.get("search_snippet"):
                results.append({"rung": rung_name, "status": "skipped"})
                continue
            try:
                sym = symbol.upper()
                if rung.get("moneycontrol_sc_id"):
                    sym = await self._walker._resolve_moneycontrol_sc_id(symbol)
                vars_ = self._walker._rung_format_vars(sym, market)
                url = rung["url"].format(**vars_)
                headers = rung.get("headers", {})
                method = (rung.get("method") or "GET").upper()
                json_body = self._walker._format_rung_value(rung.get("json_body"), sym, market)
                resp = await self._walker._fetch.request(
                    method, url, headers=headers, json_body=json_body, timeout=15000
                )
                ok = resp.get("status", 0) in range(200, 300)
                results.append({"rung": rung_name, "status": "ok" if ok else "http_error",
                                 "http_status": resp.get("status")})
            except Exception as exc:
                results.append({"rung": rung_name, "status": "error", "error": str(exc)})
        return {"endpoint": endpoint, "symbol": symbol, "market": market, "rungs": results}
