from enum import StrEnum
from typing import TypeAlias

# Type aliases
OrderId: TypeAlias = str
Symbol: TypeAlias = str
ISIN: TypeAlias = str
SubscriptionId: TypeAlias = str


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatusEnum(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AccountType(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class ConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class BarInterval(StrEnum):
    ONE_MIN = "1min"
    FIVE_MIN = "5min"
    FIFTEEN_MIN = "15min"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
    ONE_WEEK = "1wk"  # ATS-129


class AssetClass(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"
    FOREX = "FOREX"
    FUTURE = "FUTURE"
    INDEX = "INDEX"  # ATS-128 — e.g. ^GSPC, ^IXIC
