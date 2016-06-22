# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.wizard import Wizard, StateView, StateAction, Button

from trytond.modules.account_payment.payment import _STATES, _DEPENDS

__all__ = ['Journal', 'Payment', 'PayLine', 'CleanReceivedBankDiscountsStart',
    'CleanReceivedBankDiscounts']


class Journal:
    __name__ = 'account.payment.journal'
    __metaclass__ = PoolMeta
    bank_discount_account = fields.Many2One('account.account',
        'Bank Discount Account', states={
            'required': Bool(Eval('bank_discount_journal')),
            }, depends=['bank_discount_journal'])
    bank_discount_journal = fields.Many2One('account.journal',
        'Bank Discount Journal', states={
            'required': Bool(Eval('bank_discount_account')),
            },
        depends=['bank_discount_account'])
    bank_discount_percent = fields.Numeric('Bank Discount Percent',
        digits=(16, 4), domain=[
            ['OR',
                ('bank_discount_percent', '=', None),
                [
                    ('bank_discount_percent', '>', Decimal(0)),
                    ('bank_discount_percent', '<=', Decimal(1.0)),
                    ],
                ],
            ],
        states={
            'required': Bool(Eval('bank_discount_account')),
            }, depends=['bank_discount_account'],
        help='The percentage over the total owed amount that the bank will '
        'advance.')
    bank_discount_clearing_margin = fields.Integer(
        'Margin for Bank Discount Clearing', domain=[
            ['OR',
                ('bank_discount_clearing_margin', '=', None),
                ('bank_discount_clearing_margin', '>=', 0),
                ],
            ],
        states={
            'required': Bool(Eval('bank_discount_account')),
            }, depends=['bank_discount_account'],
        help='The Bank Discount Clearing will select the move lines until '
        'this number of days before the date supplied in the wizard.')

    @fields.depends('bank_discount_account', 'bank_discount_percent')
    def on_change_with_bank_discount_percent(self):
        if self.bank_discount_account and not self.bank_discount_percent:
            return Decimal(1)
        return self.bank_discount_percent


class Payment:
    __name__ = 'account.payment'
    __metaclass__ = PoolMeta
    bank_discount_amount = fields.Numeric('Bank Discount Amount',
        digits=(16, Eval('currency_digits', 2)), domain=[
            ['OR',
                ('bank_discount_amount', '=', None),
                [
                    ('bank_discount_amount', '>=', Decimal(0)),
                    ('bank_discount_amount', '<=', Eval('amount', Decimal(0))),
                    ]
                ],
            ],
        states=_STATES, depends=_DEPENDS + ['currency_digits', 'amount'])
    bank_discount_move = fields.Many2One('account.move', 'Bank Discount Move',
        readonly=True)

    @fields.depends('amount', 'journal')
    def on_change_with_bank_discount_amount(self):
        if (self.amount and self.journal
                and self.journal.bank_discount_account
                and self.journal.bank_discount_percent):
            return self.amount * self.journal.bank_discount_percent


class PayLine:
    __name__ = 'account.move.line.pay'
    __metaclass__ = PoolMeta

    def get_payment(self, line):
        payment = super(PayLine, self).get_payment(line)
        if (payment.journal.bank_discount_account
                and payment.journal.bank_discount_percent):
            payment.bank_discount_amount = (payment.amount
                * payment.journal.bank_discount_percent)
        return payment


class CleanReceivedBankDiscountsStart(ModelView):
    'Clean Lines Due - Start'
    __name__ = 'account.payment.clean_received_bank_discounts.start'
    date = fields.Date('Date', required=True)


class CleanReceivedBankDiscounts(Wizard):
    'Clean Lines Due'
    __name__ = 'account.payment.clean_received_bank_discounts'
    start = StateView('account.payment.clean_received_bank_discounts.start',
        'account_payment_bank_discount'
        '.clean_received_bank_discounts_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Clean', 'clean', 'tryton-ok', default=True),
            ])
    clean = StateAction('account.act_move_form')

    def get_clean_move(self, payment):
        pool = Pool()
        Currency = pool.get('currency.currency')
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')
        Period = pool.get('account.period')

        period = Period.find(payment.company.id,
            date=self.start.date)

        amount = Currency.compute(
            payment.currency,
            payment.bank_discount_amount,
            payment.company.currency)

        move = Move(
            journal=payment.journal.bank_discount_journal,
            origin=payment,
            date=self.start.date,
            period=period)

        bank_discount = Line()
        if payment.kind == 'payable':
            bank_discount.debit, bank_discount.credit = 0, amount
        else:
            bank_discount.debit, bank_discount.credit = amount, 0
        bank_discount.account = payment.journal.bank_discount_account
        bank_discount.second_currency = (payment.currency
            if payment.currency != payment.company.currency else None)
        bank_discount.amount_second_currency = (payment.bank_discount_amount
            if bank_discount.second_currency else None)
        bank_discount.party = (payment.party
            if bank_discount.account.party_required else None)

        counterpart = Line()
        if payment.kind == 'payable':
            counterpart.debit, counterpart.credit = amount, 0
        else:
            counterpart.debit, counterpart.credit = 0, amount
        if getattr(payment, 'clearing_move'):
            # Compatibility with account_payment_clearing
            counterpart.account = payment.journal.clearing_account
        else:
            counterpart.account = payment.line.account
        counterpart.second_currency = (payment.currency
            if payment.currency != payment.company.currency else None)
        counterpart.amount_second_currency = (payment.bank_discount_amount
            if counterpart.second_currency else None)
        counterpart.party = (payment.party
            if counterpart.account.party_required else None)

        move.lines = (bank_discount, counterpart)
        return move

    def do_clean(self, action):
        pool = Pool()
        Journal = pool.get('account.payment.journal')
        Line = pool.get('account.move.line')
        Move = pool.get('account.move')
        Payment = pool.get('account.payment')

        account_clearing = hasattr(Payment, 'clearing_move')

        journals = Journal.search([
                ('bank_discount_account', '!=', None),
                ])
        new_move_ids = []
        for journal in journals:
            limit_date = (self.start.date
                - relativedelta(days=journal.bank_discount_clearing_margin))
            print "limit_date:", limit_date
            domain = [
                    ('journal', '=', journal),
                    ('state', '=', 'succeeded'),
                    ('bank_discount_move', '!=', None),
                    ('bank_discount_move.date', '<=', limit_date),
                    ]
            if account_clearing:
                domain += [
                    ['OR',
                        [
                            ('clearing_move', '!=', None),
                            ('clearing_move.date', '<=', limit_date),
                            ],
                        [
                            ('clearing_move', '=', None),
                            ('line.date', '<=', limit_date),
                            ],
                        ],
                    ]
            else:
                domain.append(('line.date', '<=', limit_date))
            for payment in Payment.search(domain):
                move = self.get_clean_move(payment)
                move.save()
                Move.post([move])
                new_move_ids.append(move.id)

                bank_discount_account = payment.journal.bank_discount_account
                if bank_discount_account.reconcile:
                    account2to_reconcile = {l.account.id: [l]
                        for l in move.lines if not l.reconciliation}
                    print "account2to_reconcile 1:", account2to_reconcile
                    # counterpart
                    if account_clearing and payment.clearing_move:
                        for line in payment.clearing_move.lines:
                            if (line.account.id in account2to_reconcile
                                    and not line.reconciliation):
                                account2to_reconcile[line.account.id].append(
                                    line)
                    elif not payment.line.reconciliation:
                        account2to_reconcile[payment.line.account.id].append(
                            payment.line)
                    # bank discount
                    for line in payment.bank_discount_move.lines:
                        if (line.account == bank_discount_account
                                and not line.reconciliation):
                            account2to_reconcile[line.account.id].append(line)
                    print "account2to_reconcile 2:", account2to_reconcile
                    for to_reconcile in account2to_reconcile.values():
                        if not sum((l.debit - l.credit) for l in to_reconcile):
                            print "reconciliing"
                            Line.reconcile(to_reconcile)

        return action, {
            'res_id': new_move_ids,
            }
