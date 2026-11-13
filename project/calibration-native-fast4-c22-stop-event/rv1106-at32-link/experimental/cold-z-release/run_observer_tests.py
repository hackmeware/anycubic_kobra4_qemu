#!/usr/bin/env python3
"""Pure/mocked tests only. Never invoke observer.main or a firmware/client."""
import importlib
import sys
import unittest
suite = unittest.TestSuite()
for name in ('test_cold_release', 'test_runtime', 'test_adversarial'):
    module = importlib.import_module(name)
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, unittest.TestCase) and value.__module__ == name:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
