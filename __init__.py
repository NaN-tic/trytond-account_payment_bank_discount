# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from .payment import *
from .bank_statement import *


def register():
    Pool.register(
        Journal,
        Payment,
        StatementMoveLine,
        CleanReceivedBankDiscountsStart,
        module='account_payment_bank_discount', type_='model')
    Pool.register(
        PayLine,
        CleanReceivedBankDiscounts,
        module='account_payment_bank_discount', type_='wizard')
