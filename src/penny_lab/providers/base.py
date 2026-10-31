from typing import Protocol
from ..models import Bar


class CoverageError(RuntimeError):
    pass


class BarProvider(Protocol):
    def bars(self, symbols: list[str], start: str, end: str) -> list[Bar]: ...


class OTCProvider:
    def bars(self, symbols: list[str], start: str, end: str) -> list[Bar]:
        raise CoverageError("OTC provider not configured. Listed stocks are NOT an OTC substitute.")
