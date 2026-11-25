"""K2: 10 kolejnych zmian widocznych w widoku (odpytywanie co 2 s) w ciągu 5 s od odebrania."""
import pytest

from parking.service import ParkingService
from simulator.k2 import CHANGES, measure_k2


@pytest.mark.wolny
def test_K2_ten_changes_visible_within_5_s(db):
    rows = measure_k2(ParkingService(db))
    assert len(rows) == len(CHANGES) == 10
    assert all(r.ok for r in rows), [(r.spot, r.delay_s) for r in rows]
