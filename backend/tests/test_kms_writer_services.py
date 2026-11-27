"""Validate every supported optional worker subset in a recovery manifest."""

import importlib.util
import itertools
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_optional_writer_subsets_are_ordered_unique_and_known():
    path = Path(__file__).resolve().parents[2] / "scripts/kms_rotation_operator.py"
    spec = importlib.util.spec_from_file_location("kms_writer_fixture", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"fcntl": MagicMock()} if sys.platform == "win32" else {}):
        spec.loader.exec_module(module)
    required = list(module.REQUIRED_WRITERS)
    optional = list(module.OPTIONAL_WRITERS)
    for length in range(len(optional) + 1):
        for subset in itertools.combinations(optional, length):
            assert module.valid_writer_services(required + list(subset))
    assert not module.valid_writer_services(required + [optional[0], optional[0]])
    assert not module.valid_writer_services(required + list(reversed(optional)))
    assert not module.valid_writer_services(required + ["unknown-worker"])
    assert not module.valid_writer_services(required[1:])
    assert not module.valid_writer_services(None)
