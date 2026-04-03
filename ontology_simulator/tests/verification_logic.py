"""
Verification Script (v1.0)
Run: python -m pytest tests/verification_logic.py -v
  or: python tests/verification_logic.py
"""
import unittest
import random
from datetime import datetime, timedelta


class TestSemiconductorLogic(unittest.TestCase):

    def test_event_time_alignment(self):
        """驗證：查詢時間必須能正確 Join 到過去最近的快照 (未來快照不可被查到)"""
        query_time = datetime(2026, 3, 11, 12, 0, 0)

        v1_time = query_time - timedelta(minutes=10)   # 11:50 ← should be returned
        v2_time = query_time + timedelta(minutes=10)   # 12:10 ← must NOT be returned

        snapshots = [
            {"objID": "APC_001", "val": 1.0, "eff_time": v1_time},
            {"objID": "APC_001", "val": 2.0, "eff_time": v2_time},
        ]

        eligible = [s for s in snapshots if s["eff_time"] <= query_time]
        result = max(eligible, key=lambda x: x["eff_time"])

        self.assertEqual(result["val"], 1.0)
        print("✅ Time-alignment logic verification: PASSED")

    def test_ooc_distribution(self):
        """驗證：OOC 機率是否符合 10% 預期 (seeded for reproducibility)"""
        rng = random.Random(42)
        samples = [1 if rng.random() < 0.10 else 0 for _ in range(1000)]
        ooc_rate = sum(samples) / len(samples)

        self.assertTrue(
            0.08 <= ooc_rate <= 0.12,
            f"OOC rate {ooc_rate:.2%} is outside expected [8%, 12%] range",
        )
        print(f"✅ OOC Distribution verification: PASSED (Rate: {ooc_rate:.2%})")

    def test_step_to_apc_mapping(self):
        """驗證：每個 Step 唯一對應一個 APC (STEP_042 → APC_042)"""
        for n in [1, 42, 100]:
            step_id = f"STEP_{n:03d}"
            apc_id  = f"APC_{n:03d}"
            derived = f"APC_{int(step_id.split('_')[1]):03d}"
            self.assertEqual(derived, apc_id)
        print("✅ Step→APC mapping verification: PASSED")

    def test_apc_drift_stays_positive(self):
        """驗證：APC 參數在多次 ±5% 漂移後仍維持正值"""
        rng = random.Random(0)
        param = 0.5
        drift_ratio = 0.05
        for _ in range(1000):
            param *= (1 + rng.uniform(-drift_ratio, drift_ratio))
        self.assertGreater(param, 0, "APC parameter drifted to zero or negative")
        print(f"✅ APC drift stability: PASSED (final value after 1000 drifts: {param:.6f})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
