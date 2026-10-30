"""A small tabular report model shared by every report: one template renders them all and CSV export is free."""

from dataclasses import dataclass, field
from decimal import Decimal

from core.utils import csv_response


@dataclass
class Column:
    label: str
    kind: str = "money"  # text | money | number | percent | date


@dataclass
class Row:
    cells: list
    kind: str = "item"  # section | group | item | subtotal | total | grand | spacer | note
    level: int = 0
    url: str | None = None


@dataclass
class Report:
    title: str
    subtitle: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    wide: bool = False

    def section(self, label):
        self.rows.append(Row([label] + [None] * (len(self.columns) - 1), kind="section"))

    def group(self, label, level=0):
        self.rows.append(Row([label] + [None] * (len(self.columns) - 1), kind="group", level=level))

    def add(self, cells, kind="item", level=0, url=None):
        self.rows.append(Row(list(cells), kind=kind, level=level, url=url))

    def spacer(self):
        self.rows.append(Row([""] + [None] * (len(self.columns) - 1), kind="spacer"))

    def to_csv(self, filename):
        header = [c.label for c in self.columns]
        rows = []
        for row in self.rows:
            if row.kind == "spacer":
                continue
            cells = []
            for i, value in enumerate(row.cells):
                if i == 0 and row.level:
                    value = "  " * row.level + str(value)
                if isinstance(value, Decimal):
                    value = f"{value:.2f}"
                cells.append(value)
            rows.append(cells)
        return csv_response(filename, header, rows)
