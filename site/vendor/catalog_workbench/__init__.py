"""catalog-workbench: the shell every catalog's static site shares (PEP 0003, docs/peps/0003-catalog-workbench.md).

A catalog (a parts catalog, an object library) hands the workbench a `Catalog` (contract.py) holding its data loader, its
kinds of record with their tabs, its home sections and its brand; the workbench draws the bar, the search menu, the
Account menu, the record page's tabs and writes every file. Stdlib only, and it names no catalog: an import-boundary
test (tests/site/test_workbench_boundary.py) fails when it does.
"""

__version__ = "0.3.0"  # the contract stays 0.x until the second catalog ships on it (docs/CONTRACT.md)
