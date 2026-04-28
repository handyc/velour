"""Ledger tests — coords + engines + view smoke."""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from ledger.engine import (
    ArithmeticFormulaLanguage,
    ExcelFormulaLanguage,
    LANGUAGES,
    evaluate_cell,
)
from ledger.models import (
    Cell,
    FormulaLanguage,
    Sheet,
    Workbook,
    col_to_letter,
    letter_to_col,
)


class CoordTests(SimpleTestCase):
    def test_col_to_letter_basic(self):
        self.assertEqual(col_to_letter(0), 'A')
        self.assertEqual(col_to_letter(25), 'Z')
        self.assertEqual(col_to_letter(26), 'AA')
        self.assertEqual(col_to_letter(27), 'AB')
        self.assertEqual(col_to_letter(701), 'ZZ')
        self.assertEqual(col_to_letter(702), 'AAA')

    def test_letter_to_col_inverse(self):
        for c in [0, 1, 25, 26, 27, 100, 701, 702]:
            self.assertEqual(letter_to_col(col_to_letter(c)), c)


class ArithmeticEngineTests(SimpleTestCase):
    def setUp(self):
        self.engine = ArithmeticFormulaLanguage()

    def test_simple_sum(self):
        self.assertEqual(self.engine.evaluate('1+2', {}), 3)

    def test_cell_refs_substituted(self):
        self.assertEqual(
            self.engine.evaluate('A1+A2', {'A1': '5', 'A2': '7'}),
            12,
        )

    def test_missing_ref_treated_as_zero(self):
        self.assertEqual(self.engine.evaluate('A1+1', {}), 1)

    def test_rejects_nonarithmetic(self):
        with self.assertRaises(ValueError):
            self.engine.evaluate('1+__import__("os")', {})


class ExcelEngineTests(SimpleTestCase):
    def setUp(self):
        self.engine = ExcelFormulaLanguage()

    def test_simple_sum_formula(self):
        result = self.engine.evaluate('1+2', {})
        self.assertEqual(int(result), 3)


class RegistryTests(SimpleTestCase):
    def test_registry_has_excel_and_arith(self):
        self.assertIn('excel', LANGUAGES)
        self.assertIn('arith', LANGUAGES)

    def test_evaluate_cell_returns_value_and_no_error(self):
        v, err = evaluate_cell('1+2', {}, language_slug='arith')
        self.assertEqual(v, 3)
        self.assertIsNone(err)

    def test_evaluate_cell_returns_error_on_bad_formula(self):
        v, err = evaluate_cell('totally not arithmetic', {}, language_slug='arith')
        self.assertIsNone(v)
        self.assertIsNotNone(err)


class WorkbookModelTests(TestCase):
    def test_slug_unique_on_collision(self):
        a = Workbook.objects.create(title='Same Title')
        b = Workbook.objects.create(title='Same Title')
        self.assertEqual(a.slug, 'same-title')
        self.assertNotEqual(a.slug, b.slug)


class CellModelTests(TestCase):
    def setUp(self):
        wb = Workbook.objects.create(title='cells')
        self.sheet = Sheet.objects.create(workbook=wb, name='Sheet1', order=0)

    def test_a1_property(self):
        c = Cell.objects.create(sheet=self.sheet, row=0, col=0, value='1')
        self.assertEqual(c.a1, 'A1')
        c2 = Cell.objects.create(sheet=self.sheet, row=9, col=27, value='2')
        self.assertEqual(c2.a1, 'AB10')

    def test_is_formula(self):
        c = Cell.objects.create(sheet=self.sheet, row=0, col=1, value='=1+2')
        self.assertTrue(c.is_formula())
        c2 = Cell.objects.create(sheet=self.sheet, row=0, col=2, value='42')
        self.assertFalse(c2.is_formula())


class ViewSmokeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw')
        self.client.force_login(self.user)
        FormulaLanguage.objects.create(slug='excel', name='Excel-compatible')

    def test_list_renders(self):
        resp = self.client.get(reverse('ledger:list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ledger')

    def test_new_creates_workbook_with_sheet(self):
        resp = self.client.post(reverse('ledger:new'), {'title': 'Budget'})
        self.assertEqual(resp.status_code, 302)
        wb = Workbook.objects.get(title='Budget')
        self.assertEqual(wb.owner, self.user)
        self.assertEqual(wb.sheets.count(), 1)
        self.assertEqual(wb.formula_language.slug, 'excel')

    def test_detail_renders_grid(self):
        wb = Workbook.objects.create(title='detail-test', owner=self.user)
        Sheet.objects.create(workbook=wb, name='Sheet1', order=0)
        resp = self.client.get(reverse('ledger:detail', args=[wb.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<table class="ledger-grid">', html=False)

    def test_set_cell_plain_value(self):
        wb = Workbook.objects.create(title='set-cell', owner=self.user)
        sh = Sheet.objects.create(workbook=wb, name='Sheet1', order=0)
        resp = self.client.post(
            reverse('ledger:api_set_cell', args=[wb.slug, sh.pk]),
            data='{"row": 0, "col": 0, "value": "42"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['value'], '42')
        self.assertEqual(body['computed'], '')

    def test_set_cell_arithmetic_formula(self):
        wb = Workbook.objects.create(
            title='formula-test', owner=self.user,
            formula_language=FormulaLanguage.objects.create(slug='arith', name='Arith'),
        )
        sh = Sheet.objects.create(workbook=wb, name='Sheet1', order=0)
        # Seed A1=5, A2=7, then write =A1+A2 in B1.
        Cell.objects.create(sheet=sh, row=0, col=0, value='5')
        Cell.objects.create(sheet=sh, row=1, col=0, value='7')
        resp = self.client.post(
            reverse('ledger:api_set_cell', args=[wb.slug, sh.pk]),
            data='{"row": 0, "col": 1, "value": "=A1+A2"}',
            content_type='application/json',
        )
        body = resp.json()
        self.assertTrue(body['ok'], body)
        self.assertEqual(body['computed'], '12')

    def test_delete_workbook(self):
        wb = Workbook.objects.create(title='gone', owner=self.user)
        resp = self.client.post(reverse('ledger:delete', args=[wb.slug]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Workbook.objects.filter(pk=wb.pk).exists())
