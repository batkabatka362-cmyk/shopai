#!/usr/bin/env python3
"""ShopAI Test Runner — runs all tests and generates report."""
import sys
import os
import time
import unittest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_tests():
    start = time.monotonic()

    # Discover and run all tests
    loader = unittest.TestLoader()
    suite = loader.discover("tests", pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    elapsed = time.monotonic() - start

    # Summary
    print("\n" + "=" * 60)
    print("SHOPAI TEST REPORT")
    print("=" * 60)
    print(f"Tests run:    {result.testsRun}")
    print(f"Passed:       {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures:     {len(result.failures)}")
    print(f"Errors:       {len(result.errors)}")
    print(f"Time:         {elapsed:.2f}s")
    print(f"Status:       {'PASS' if result.wasSuccessful() else 'FAIL'}")
    print("=" * 60)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
