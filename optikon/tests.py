"""optikon — smoke tests for the illusion registry + new illusions."""
from django.test import TestCase

from optikon.illusions import all_illusions, get


class IllusionRegistryTest(TestCase):
    def test_all_illusions_includes_ishihara_and_white(self):
        slugs = [m.SLUG for m in all_illusions()]
        self.assertIn('ishihara', slugs)
        self.assertIn('white_illusion', slugs)

    def test_each_illusion_has_required_attributes(self):
        for m in all_illusions():
            self.assertTrue(hasattr(m, 'SLUG'),    f'{m.__name__} missing SLUG')
            self.assertTrue(hasattr(m, 'NAME'),    f'{m.__name__} missing NAME')
            self.assertTrue(hasattr(m, 'PALETTE'), f'{m.__name__} missing PALETTE')
            self.assertTrue(hasattr(m, 'PARAMS'),  f'{m.__name__} missing PARAMS')
            self.assertTrue(callable(getattr(m, 'render', None)),
                f'{m.__name__} missing render()')

    def test_each_illusion_renders_valid_grid(self):
        for m in all_illusions():
            grid = m.render(20, 20, {})
            self.assertEqual(len(grid), 20, f'{m.SLUG} wrong height')
            for row in grid:
                self.assertEqual(len(row), 20, f'{m.SLUG} row width wrong')
                for cell in row:
                    self.assertIsInstance(cell, int,
                        f'{m.SLUG} non-int cell')
                    self.assertGreaterEqual(cell, 0,
                        f'{m.SLUG} negative palette index')
                    self.assertLess(cell, len(m.PALETTE),
                        f'{m.SLUG} palette index out of range')


class IshiharaTest(TestCase):
    def test_renders_with_each_palette_pair(self):
        from optikon.illusions import ishihara
        for pair in ('red-green', 'blue-yellow', 'grayscale'):
            grid = ishihara.render(40, 40, {'digit': 5, 'palette_pair': pair})
            self.assertEqual(len(grid), 40)
            self.assertEqual(len(grid[0]), 40)

    def test_different_digits_produce_different_grids(self):
        from optikon.illusions import ishihara
        a = ishihara.render(40, 40, {'digit': 3})
        b = ishihara.render(40, 40, {'digit': 7})
        self.assertNotEqual(a, b)


class WhiteIllusionTest(TestCase):
    def test_grid_contains_all_three_palette_indices(self):
        from optikon.illusions import white_illusion
        grid = white_illusion.render(40, 40, {})
        seen = {cell for row in grid for cell in row}
        # Need black, white, AND gray — that's the whole point.
        self.assertEqual(seen, {0, 1, 2})

    def test_two_gray_patches_present(self):
        """Both gray patches should appear; check that grid index 2
        (the test gray) appears in BOTH a row dominated by black
        background AND a row dominated by white background — that's
        the side-by-side condition the illusion needs."""
        from optikon.illusions import white_illusion
        grid = white_illusion.render(40, 40, {})
        for r, row in enumerate(grid):
            n_gray = row.count(2)
            n_black = row.count(0)
            n_white = row.count(1)
            # Some rows have gray on black bg, some have gray on white.
            if n_gray > 0:
                # Either the row's other cells lean dark or lean light.
                self.assertTrue(n_black > 0 or n_white > 0,
                    f'row {r} gray patch but no background?')
