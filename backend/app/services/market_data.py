"""
Market Data Service - Real-time Stock Data via Alpha Vantage API

Provides live stock prices, technicals, fundamentals, and sentiment.
Used by agents for data-driven financial recommendations.
"""

import logging
import asyncio
import json
import ast
import time
from typing import Dict, Optional, List
from datetime import datetime
import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://www.alphavantage.co/query"
DEFAULT_MCP_PROTOCOL_VERSION = "2025-06-18"


class MarketDataService:
    """Fetch real-time market data from Alpha Vantage."""

    def __init__(self):
        self.api_key = settings.alpha_vantage_api_key
        self.mcp_url = settings.alpha_vantage_mcp_url
        self.mcp_session_id: Optional[str] = None
        self.mcp_protocol_version = DEFAULT_MCP_PROTOCOL_VERSION
        self._mcp_initialized = False
        self._mcp_tools: Optional[set[str]] = None
        if not self.api_key and not self.mcp_url:
            logger.warning("Alpha Vantage not configured. Market data unavailable.")

    def is_available(self) -> bool:
        """Check if market data service can operate (API key configured)."""
        return bool(self.mcp_url or self.api_key)

    def get_status(self) -> Dict:
        """Return service status for audit trail."""
        if not self.is_available():
            return {
                "available": False,
                "timestamp": datetime.utcnow().isoformat(),
                "reason": "Alpha Vantage not configured",
            }
        return {
            "available": True,
            "timestamp": datetime.utcnow().isoformat(),
            "reason": "OK",
            "mode": "mcp" if self.mcp_url else "rest",
        }

    async def _mcp_initialize(self) -> None:
        if self._mcp_initialized or not self.mcp_url:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "initialize",
            "params": {
                "protocolVersion": self.mcp_protocol_version,
                "clientInfo": {"name": "gs-project", "version": "1.0"},
                "capabilities": {},
            },
        }
        response = await self._mcp_request(payload, expect_session=True)
        if response.get("protocolVersion"):
            self.mcp_protocol_version = response["protocolVersion"]
        tools = await self._mcp_request(
            {
                "jsonrpc": "2.0",
                "id": int(time.time() * 1000) + 1,
                "method": "tools/list",
                "params": {},
            }
        )
        tool_names = {tool.get("name") for tool in tools.get("tools", []) if tool.get("name")}
        self._mcp_tools = tool_names if tool_names else None
        self._mcp_initialized = True

    async def _mcp_request(self, payload: Dict, expect_session: bool = False) -> Dict:
        if not self.mcp_url:
            raise RuntimeError("Alpha Vantage MCP URL not configured")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.mcp_protocol_version,
        }
        if self.mcp_session_id:
            headers["MCP-Session-Id"] = self.mcp_session_id

        async with aiohttp.ClientSession() as session:
            async with session.post(self.mcp_url, json=payload, headers=headers) as resp:
                if expect_session and not self.mcp_session_id:
                    session_id = resp.headers.get("MCP-Session-Id")
                    if session_id:
                        self.mcp_session_id = session_id

                content_type = resp.headers.get("Content-Type", "")
                if "text/event-stream" in content_type:
                    text = await resp.text()
                    data = self._parse_sse_payload(text)
                else:
                    data = await resp.json()

        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("result", {})

    def _parse_sse_payload(self, text: str) -> Dict:
        last_event = None
        for line in text.splitlines():
            if line.startswith("data:"):
                candidate = line.replace("data:", "", 1).strip()
                if not candidate:
                    continue
                try:
                    last_event = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        return last_event or {}

    async def _mcp_tools_call(self, name: str, arguments: Dict) -> Dict:
        await self._mcp_initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        return await self._mcp_request(payload)

    def _extract_tool_payload(self, result: Dict) -> Dict:
        if not result:
            return {}
        if "content" in result and isinstance(result["content"], list):
            text_chunks = []
            for entry in result["content"]:
                if isinstance(entry, dict) and entry.get("type") == "text":
                    text_chunks.append(entry.get("text", ""))
            text = "".join(text_chunks).strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    # Fall back to CSV parsing for simple two-line responses
                    if "," in text and "\n" in text:
                        lines = [line for line in text.splitlines() if line.strip()]
                        if len(lines) >= 2:
                            headers = [h.strip() for h in lines[0].split(",")]
                            values = [v.strip() for v in lines[1].split(",")]
                            if len(headers) == len(values):
                                return {headers[i]: values[i] for i in range(len(headers))}
                    return {"raw_text": text}
        if "data" in result and isinstance(result["data"], dict):
            return result["data"]
        return result

    async def _mcp_alpha_vantage_call(self, function_name: str, arguments: Dict) -> Dict:
        try:
            await self._mcp_initialize()
            if self._mcp_tools and function_name not in self._mcp_tools:
                return {}
            # MCP server requires TOOL_GET before TOOL_CALL
            await self._mcp_tools_call("TOOL_GET", {"tool_name": function_name})
            result = await self._mcp_tools_call(
                "TOOL_CALL",
                {"tool_name": function_name, "arguments": arguments},
            )
            return self._extract_tool_payload(result)
        except Exception as e:
            logger.warning(f"MCP tool call failed for {function_name}: {e}")
            return {}

    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get real-time stock quote.

        Args:
            symbol: Stock symbol (e.g., 'AAPL')

        Returns:
            {
                'symbol': 'AAPL',
                'price': 189.50,
                'change': 2.50,
                'change_percent': 1.33,
                'timestamp': '2025-02-26 16:00:00'
            }
        """
        if not self.is_available():
            return None

        try:
            data = {}
            if self.mcp_url:
                data = await self._mcp_alpha_vantage_call(
                    "GLOBAL_QUOTE",
                    {"symbol": symbol, "datatype": "json", "return_full_data": True},
                )
            if (not data or "Global Quote" not in data) and self.api_key:
                params = {
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": self.api_key,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(BASE_URL, params=params) as resp:
                        data = await resp.json()

            if "Global Quote" in data:
                quote = data["Global Quote"]
            elif isinstance(data, dict) and "symbol" in data and "price" in data:
                # MCP CSV fallback format
                quote = {
                    "01. symbol": data.get("symbol"),
                    "02. open": data.get("open"),
                    "03. high": data.get("high"),
                    "04. low": data.get("low"),
                    "05. price": data.get("price"),
                    "06. volume": data.get("volume"),
                    "07. latest trading day": data.get("latestDay"),
                    "08. previous close": data.get("previousClose"),
                    "09. change": data.get("change"),
                    "10. change percent": data.get("changePercent"),
                }
            else:
                logger.warning(f"No quote data for {symbol}")
                return None

            return {
                "symbol": symbol,
                "price": float(quote.get("05. price", 0)),
                "change": float(quote.get("09. change", 0)),
                "change_percent": float(quote.get("10. change percent", "0").rstrip("%")),
                "last_trading_day": quote.get("07. latest trading day"),
                "fetched_at": datetime.utcnow().isoformat(),  # When we fetched it
            }

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None

    async def get_company_info(self, symbol: str) -> Optional[Dict]:
        """
        Get company overview and fundamentals.

        Returns:
            {
                'name': 'Apple Inc.',
                'sector': 'Technology',
                'description': '...',
                'market_cap': 3000000000000,
                'pe_ratio': 28.5,
                'dividend_yield': 0.42
            }
        """
        if not self.is_available():
            return None

        try:
            data = {}
            if self.mcp_url:
                data = await self._mcp_alpha_vantage_call(
                    "OVERVIEW", {"symbol": symbol}
                )
            if (not data or "Name" not in data) and self.api_key:
                params = {
                    "function": "OVERVIEW",
                    "symbol": symbol,
                    "apikey": self.api_key,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(BASE_URL, params=params) as resp:
                        data = await resp.json()

            return {
                "name": data.get("Name"),
                "sector": data.get("Sector"),
                "industry": data.get("Industry"),
                "market_cap": int(data.get("MarketCapitalization", 0)),
                "pe_ratio": float(data.get("PERatio", 0)) if data.get("PERatio") != "None" else None,
                "dividend_yield": float(data.get("DividendYield", 0)) if data.get("DividendYield") else None,
                "52_week_high": float(data.get("52WeekHigh", 0)) if data.get("52WeekHigh") else None,
                "52_week_low": float(data.get("52WeekLow", 0)) if data.get("52WeekLow") else None,
            }

        except Exception as e:
            logger.error(f"Error fetching company info for {symbol}: {e}")
            return None

    async def calculate_portfolio_gains(
        self,
        holdings: List[Dict],  # [{'symbol': 'AAPL', 'quantity': 10, 'cost_basis': 150}]
    ) -> Dict:
        """
        Calculate portfolio gains/losses with live prices.

        Returns:
            {
                'total_cost': 1500.0,
                'total_value': 1895.0,
                'total_gain': 395.0,
                'gain_percent': 26.33,
                'holdings': [
                    {'symbol': 'AAPL', 'cost_basis': 150, 'price': 189.5, 'gain': 39.5, 'gain_percent': 26.33}
                ]
            }
        """
        results = []
        total_cost = 0
        total_value = 0

        for holding in holdings:
            symbol = holding.get("symbol", "").upper()
            quantity = holding.get("quantity", 0)
            cost_basis = holding.get("cost_basis", 0)

            if not symbol or not quantity or not cost_basis:
                continue

            # Get live price
            quote = await self.get_quote(symbol)
            if not quote:
                logger.warning(f"Could not fetch price for {symbol}")
                continue

            price = quote["price"]
            cost = cost_basis * quantity
            value = price * quantity
            gain = value - cost
            gain_percent = (gain / cost * 100) if cost > 0 else 0

            results.append({
                "symbol": symbol,
                "quantity": quantity,
                "cost_basis": cost_basis,
                "current_price": price,
                "total_cost": cost,
                "total_value": value,
                "gain": gain,
                "gain_percent": round(gain_percent, 2),
                "change_percent": quote["change_percent"],
            })

            total_cost += cost
            total_value += value

        total_gain = total_value - total_cost
        total_gain_percent = (total_gain / total_cost * 100) if total_cost > 0 else 0

        return {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_gain": round(total_gain, 2),
            "gain_percent": round(total_gain_percent, 2),
            "holdings": results,
        }

    async def get_technical_indicators(
        self,
        symbol: str,
        interval: str = "daily",
    ) -> Optional[Dict]:
        """
        Get RSI, MACD, and other technical indicators.

        Args:
            symbol: Stock symbol
            interval: 'daily', 'weekly', 'monthly'

        Returns:
            {
                'symbol': 'AAPL',
                'rsi': 72.5,
                'macd': 2.35,
                'macd_signal': 2.10,
                'sma_20': 185.5,
                'sma_50': 180.0,
                'interpretation': 'Overbought, consider taking profits'
            }
        """
        if not self.api_key:
            return None

        try:
            # Get RSI
            params = {
                "function": "RSI",
                "symbol": symbol,
                "interval": interval,
                "time_period": 14,
                "apikey": self.api_key,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(BASE_URL, params=params) as resp:
                    rsi_data = await resp.json()

            # Get MACD
            params["function"] = "MACD"
            async with aiohttp.ClientSession() as session:
                async with session.get(BASE_URL, params=params) as resp:
                    macd_data = await resp.json()

            # Get SMA
            params["function"] = "SMA"
            params["time_period"] = 20
            async with aiohttp.ClientSession() as session:
                async with session.get(BASE_URL, params=params) as resp:
                    sma_data = await resp.json()

            # Parse results
            result = {
                "symbol": symbol,
                "rsi": None,
                "macd": None,
                "sma_20": None,
            }

            # Extract latest values
            if "Technical Analysis: RSI" in rsi_data:
                latest = list(rsi_data["Technical Analysis: RSI"].values())[0]
                result["rsi"] = float(latest["RSI"])

            if "Technical Analysis: MACD" in macd_data:
                latest = list(macd_data["Technical Analysis: MACD"].values())[0]
                result["macd"] = float(latest["MACD"])
                result["macd_signal"] = float(latest["MACD_Signal"])

            if "Technical Analysis: SMA" in sma_data:
                latest = list(sma_data["Technical Analysis: SMA"].values())[0]
                result["sma_20"] = float(latest["SMA"])

            # Add interpretation
            if result["rsi"]:
                if result["rsi"] > 70:
                    result["interpretation"] = "🔴 Overbought - Consider taking profits"
                elif result["rsi"] < 30:
                    result["interpretation"] = "🟢 Oversold - Consider buying"
                else:
                    result["interpretation"] = "🟡 Neutral - Hold position"

            return result

        except Exception as e:
            logger.error(f"Error fetching technical indicators for {symbol}: {e}")
            return None
