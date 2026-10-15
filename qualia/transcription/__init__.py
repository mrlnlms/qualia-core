"""Utilidades de transcrição estruturada, sem dependências de modelos."""

from .segments import assign_words, group_words, export_rows

__all__ = ["assign_words", "group_words", "export_rows"]
