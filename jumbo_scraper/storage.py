"""Escritura incremental a JSONL y CSV (segura para catálogos grandes)."""

from __future__ import annotations

import csv
import json
import os
from typing import Dict, List, Optional

from .parser import CSV_FIELDS


class Storage:
    """Escribe filas a medida que llegan, sin acumular todo en memoria."""

    def __init__(self, output_dir: str, write_csv: bool = True,
                 write_jsonl: bool = True, prefix: str = "jumbo_productos"):
        os.makedirs(output_dir, exist_ok=True)
        self.write_csv = write_csv
        self.write_jsonl = write_jsonl
        self.csv_path = os.path.join(output_dir, f"{prefix}.csv")
        self.jsonl_path = os.path.join(output_dir, f"{prefix}.jsonl")

        self._csv_file = None
        self._csv_writer: Optional[csv.DictWriter] = None
        self._jsonl_file = None
        self.rows_written = 0

    def __enter__(self) -> "Storage":
        if self.write_csv:
            self._csv_file = open(self.csv_path, "w", newline="", encoding="utf-8-sig")
            self._csv_writer = csv.DictWriter(
                self._csv_file, fieldnames=CSV_FIELDS, extrasaction="ignore"
            )
            self._csv_writer.writeheader()
        if self.write_jsonl:
            self._jsonl_file = open(self.jsonl_path, "w", encoding="utf-8")
        return self

    def write_rows(self, rows: List[Dict]) -> None:
        for row in rows:
            if self._csv_writer is not None:
                self._csv_writer.writerow(row)
            if self._jsonl_file is not None:
                self._jsonl_file.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.rows_written += 1
            if self.rows_written % 500 == 0:
                self.flush()

    def flush(self) -> None:
        if self._csv_file:
            self._csv_file.flush()
        if self._jsonl_file:
            self._jsonl_file.flush()

    def __exit__(self, *exc) -> None:
        self.flush()
        if self._csv_file:
            self._csv_file.close()
        if self._jsonl_file:
            self._jsonl_file.close()
