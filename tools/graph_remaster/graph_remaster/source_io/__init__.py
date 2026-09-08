"""Replaceable source-format adapters and lossless extraction metadata."""

from .ipack_adapter import IpackAdapter, write_ipack_script

__all__ = ["IpackAdapter", "write_ipack_script"]
