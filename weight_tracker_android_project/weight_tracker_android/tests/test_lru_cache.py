import unittest

from services.lru_cache import BoundedLRU


class BoundedLRUTests(unittest.TestCase):
    def test_evicts_least_recently_used_entry(self):
        cache = BoundedLRU(2)
        cache.set("a", 1)
        cache.set("b", 2)
        self.assertEqual(cache.get("a"), 1)  # Touch a; b is now least recent.
        cache.set("c", 3)
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)
        self.assertEqual(len(cache), 2)

    def test_updating_existing_key_does_not_grow_cache(self):
        cache = BoundedLRU(2)
        cache.set("a", 1)
        cache.set("a", 2)
        cache.set("b", 3)
        self.assertEqual(cache.get("a"), 2)
        self.assertEqual(len(cache), 2)

    def test_capacity_must_be_positive(self):
        with self.assertRaises(ValueError):
            BoundedLRU(0)

    def test_clear_and_pop(self):
        cache = BoundedLRU(2)
        cache.set("a", 1)
        self.assertEqual(cache.pop("a"), 1)
        cache.set("b", 2)
        cache.clear()
        self.assertEqual(len(cache), 0)


if __name__ == "__main__":
    unittest.main()
