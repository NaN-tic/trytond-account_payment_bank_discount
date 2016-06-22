# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If, Bool
from trytond.transaction import Transaction

__all__ = ['StatementMoveLine']


class StatementMoveLine:
    __name__ = 'account.bank.statement.move.line'
    __metaclass__ = PoolMeta
    payment = fields.Many2One('account.payment', 'Payment',
        domain=[
            If(Bool(Eval('party')), [('party', '=', Eval('party'))], []),
            ('state', 'in', ['processing', 'succeeded']),
            ],
        depends=['party'])

    @fields.depends('party', 'payment', methods=['account'])
    def on_change_party(self):
        changes = super(StatementMoveLine, self).on_change_party()
        if self.payment:
            if self.payment.party != self.party:
                changes['payment'] = None
                self.payment = None
            elif changes.get('account'):
                changes.update(self.on_change_account())
        return changes

    @fields.depends('account', 'payment')
    def on_change_account(self):
        changes = super(StatementMoveLine, self).on_change_account()
        if self.payment:
            bank_discount_account = self.payment.journal.bank_discount_account
            clearing_account = getattr(self.payment.journal,
                'clearing_account')
            if bank_discount_account:
                if self.account != bank_discount_account:
                    changes['payment'] = None
                    self.payment = None
            elif clearing_account:
                # compatibility with account_payment_clearing
                if self.account != clearing_account:
                    changes['payment'] = None
                    self.payment = None
            elif self.account:
                changes['payment'] = None
                self.payment = None
        return changes

    @fields.depends('payment', 'party', 'account', '_parent_statement.journal')
    def on_change_payment(self):
        pool = Pool()
        Currency = pool.get('currency.currency')
        changes = {}
        if self.payment:
            if not self.party:
                changes['party'] = self.payment.party.id
                changes['party.rec_name'] = self.payment.party.rec_name
                self.party = self.payment.party
            bank_discount_account = self.payment.journal.bank_discount_account
            bank_discount = False
            clearing_account = getattr(self.payment.journal,
                'clearing_account')
            if (not self.account
                    and bank_discount_account
                    and self.payment.bank_discount_amount
                    and not self.payment.bank_discount_move):
                changes['account'] = bank_discount_account.id
                changes['account.rec_name'] = bank_discount_account.rec_name
                self.account = bank_discount_account
                bank_discount = True
            elif (not self.account
                    and clearing_account
                    and self.payment.clearing_move):
                # compatibility with account_payment_clearing
                changes['account'] = clearing_account.id
                changes['account.rec_name'] = clearing_account.rec_name
            if self.statement and self.statement.journal:
                with Transaction().set_context(date=self.payment.date):
                    if bank_discount:
                        amount = Currency.compute(
                            self.payment.currency,
                            self.payment.bank_discount_amount,
                            self.statement.journal.currency)
                    elif self.payment and self.payment.bank_discount_move:
                        amount = Currency.compute(
                            self.payment.currency,
                            self.payment.amount
                            - self.payment.bank_discount_amount,
                            self.statement.journal.currency)
                    else:
                        amount = Currency.compute(
                            self.payment.currency,
                            self.payment.amount,
                            self.statement.journal.currency)
                changes['amount'] = amount
                self.amount = amount
                if self.payment.kind == 'payable':
                    changes['amount'] *= -1
                    self.amount *= -1
        return changes

    def create_move(self):
        pool = Pool()
        MoveLine = pool.get('account.move.line')
        move = super(StatementMoveLine, self).create_move()
        if self.payment:
            print "AKI"
            if (self.payment.journal.bank_discount_account
                    and self.payment.bank_discount_amount
                    and not self.payment.bank_discount_move):
                print "aki 1"
                self.payment.bank_discount_move = move
                self.payment.save()
                print "payment %s. bank_discount_move: %s" %(self.payment, self.payment.bank_discount_move)
            elif (not self.payment.bank_discount_move
                    and getattr(self.payment, 'clearing_move')):
                print "aki 2"
                # Compatibility with account_payment_clearing
                clearing_account = self.payment.journal.clearing_account
                if clearing_account.reconcile:
                    to_reconcile = []
                    for line in move.lines + self.payment.clearing_move.lines:
                        if (line.account == clearing_account
                                and not line.reconciliation):
                            to_reconcile.append(line)
                    if not sum((l.debit - l.credit) for l in to_reconcile):
                        MoveLine.reconcile(to_reconcile)
        return move

    @classmethod
    def post_move(cls, lines):
        pool = Pool()
        Move = pool.get('account.move')
        super(StatementMoveLine, cls).post_move(lines)
        Move.post([l.payment.clearing_move for l in lines
                if (l.payment and getattr(l.payment, 'clearing_move')
                    and l.payment.clearing_move.state != 'posted')])

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        else:
            default = default.copy()
        default.setdefault('payment', None)
        return super(StatementMoveLine, cls).copy(lines, default=default)
