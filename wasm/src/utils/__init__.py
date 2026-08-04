"""Utility functions for the WebAssembly runtime."""

from .leb128 import decode_unsigned_leb128, decode_signed_leb128, encode_unsigned_leb128, encode_signed_leb128
from .config import WasmConfig, RuntimeConfig, CompilerConfig, WASIConfig, AinosConfig

__all__ = [
    "decode_unsigned_leb128",
    "decode_signed_leb128",
    "encode_unsigned_leb128",
    "encode_signed_leb128",
    "WasmConfig",
    "RuntimeConfig",
    "CompilerConfig",
    "WASIConfig",
    "AinosConfig",
]