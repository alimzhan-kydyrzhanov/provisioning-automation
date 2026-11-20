import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from provisioning.__main__ import SimClock
from provisioning.console import FakeConsole
from provisioning.store import Store
from provisioning.workflow import Engine

ORDERS = json.loads((Path(__file__).parent.parent / "data" / "sample_orders.json").read_text())


@pytest.fixture
def orders():
    return copy.deepcopy(ORDERS)


@pytest.fixture
def clock():
    return SimClock(datetime(2026, 11, 20, 9, 0))


@pytest.fixture
def engine(clock):
    return Engine(Store(), FakeConsole(), clock=clock)
