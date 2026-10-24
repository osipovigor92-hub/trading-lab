"""Trading Lab adaptation of trader-budget/trader-risk, MIT Jake Schincariol.

Source: Jakeschincariol/trader-skill @ 5189e79b9a480755a3733ac9713f5353981dbe18.
See docs/licenses/trader-skill-MIT.txt. Pure PAPER sizing/checks, no I/O or broker.
The single-position simulator reserves full notional for LONG and SHORT alike.
"""
import hashlib
import json
import math

OPTIONAL_LIMITS = {'cash_buffer_pct': (0, 100), 'max_position_pct': (.01, 100), 'min_order_usd': (0, 1e6)}
LEGACY_RULES = {'cash_buffer_pct': 0., 'max_position_pct': 100., 'min_order_usd': 0.}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def budget_limits(settings, balance):
    rules = {key: settings.get(key, default) for key, default in LEGACY_RULES.items()}
    if any(not finite(v) or not OPTIONAL_LIMITS[k][0] <= v <= OPTIONAL_LIMITS[k][1] for k, v in rules.items()):
        raise ValueError('Некорректные лимиты бюджета')
    if not finite(balance) or balance <= 0:
        raise ValueError('Нет доступного PAPER-баланса')
    capital, maximum = settings['capital'], settings['max_notional']
    if not finite(capital) or capital <= 0 or not finite(maximum) or maximum <= 0:
        raise ValueError('Некорректный капитал или лимит входа')
    available = min(balance, capital)
    reserve = available * rules['cash_buffer_pct'] / 100
    return dict(rules, capital=available, reserve=reserve, spendable=available-reserve,
                max_notional=min(maximum, available*rules['max_position_pct']/100))


def check_entry(plan, position, balance, now):
    """Check the exact server-sized fill. PASS is recorded, never an order approval."""
    limits = budget_limits(plan['settings'], balance)
    notional = position['entry'] * position['quantity']
    fee, risk, budget = position['entry_fee'], position['risk'], position['budget']
    if not all(finite(v) for v in (notional, fee, risk, budget, now)) or notional <= 0 or fee < 0 or risk <= 0:
        raise ValueError('Размер входа не прошёл проверку бюджета')
    reasons = []
    if notional < limits['min_order_usd']-1e-8:
        reasons.append('объём ниже минимального входа')
    if notional > limits['max_notional']+1e-8:
        reasons.append('превышен лимит позиции')
    if notional + fee > limits['spendable']+1e-8:
        reasons.append('нарушен резерв бюджета')
    if risk > budget+1e-8:
        reasons.append('превышен риск до стопа')
    if reasons:
        raise ValueError('PAPER-вход заблокирован: ' + '; '.join(reasons))
    core = dict(plan=plan, balance=balance, entry=position['entry'], quantity=position['quantity'],
                entry_fee=fee, risk=risk, budget=budget, checked_at=now)
    fingerprint = hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    return dict(verdict='PASS', mode='paper', version=1, checked_at=now, fingerprint=fingerprint,
                notional=notional, fee=fee, cash_after_reservation=balance-notional-fee, limits=limits)


# Upstream license retained with the deployed adaptation.
# MIT License
# 
# Copyright (c) 2026 Jake Schincariol
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
