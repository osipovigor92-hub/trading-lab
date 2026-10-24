import copy
import unittest
from test_manual_paper import Market, plan
from manual_paper import prepare
from trader_risk import check_entry


class TraderRiskTests(unittest.TestCase):
    def test_caps_cash_and_full_notional_for_both_directions(self):
        for side in (1, -1):
            proposal = plan(side)
            proposal['settings'].update(cash_buffer_pct=90, max_position_pct=5, min_order_usd=5)
            position = prepare(proposal, Market(), 600, 100001)
            check = position['risk_check']
            self.assertEqual(check['verdict'], 'PASS')
            self.assertLessEqual(check['notional'], 30)
            self.assertGreaterEqual(check['cash_after_reservation'], 540)
            self.assertEqual(check['limits']['reserve'], 540)

    def test_actual_balance_limits_budget_not_form_capital(self):
        proposal = plan()
        proposal['settings'].update(cash_buffer_pct=10, max_position_pct=25, min_order_usd=5)
        position = prepare(proposal, Market(), 40, 100001)
        self.assertEqual(position['risk_check']['limits']['capital'], 40)
        self.assertLessEqual(position['risk_check']['notional'], 10)

    def test_minimum_reserve_invalid_values_block(self):
        for settings in ({'min_order_usd': 101}, {'cash_buffer_pct': 100},
                         {'cash_buffer_pct': float('nan')}, {'max_position_pct': True},
                         {'max_position_pct': 101}, {'min_order_usd': -1}):
            proposal = plan();proposal['settings'].update(settings)
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                prepare(proposal, Market(), 600, 100001)

    def test_rechecks_fill_and_fingerprint_covers_plan_and_execution(self):
        proposal = plan()
        position = prepare(proposal, Market(), 600, 100001)
        first = position['risk_check']['fingerprint']
        changed = copy.deepcopy(proposal);changed['target'] += 1
        self.assertNotEqual(first, check_entry(changed, position, 600, 100001)['fingerprint'])
        changed_fill = dict(position, quantity=position['quantity']*.9)
        self.assertNotEqual(first, check_entry(proposal, changed_fill, 600, 100001)['fingerprint'])
        with self.assertRaises(ValueError):
            check_entry(proposal, dict(position, quantity=100), 600, 100001)

    def test_old_plan_keeps_original_optional_limits(self):
        position = prepare(plan(), Market(), 600, 100001)
        self.assertEqual(position['risk_check']['limits']['cash_buffer_pct'], 0)
        self.assertEqual(position['risk_check']['limits']['max_position_pct'], 100)
