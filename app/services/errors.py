"""Errors our business logic can raise. Handlers turn them into friendly messages."""


class ServiceError(Exception):
    """Base class for expected, user-facing problems."""


class ProductUnavailable(ServiceError):
    pass


class InsufficientBalance(ServiceError):
    def __init__(self, price_cents: int, balance_cents: int):
        super().__init__("insufficient balance")
        self.price_cents = price_cents
        self.balance_cents = balance_cents


class DuplicateOrder(ServiceError):
    pass


class DuplicateDeposit(ServiceError):
    def __init__(self, deposit: dict):
        super().__init__("pending deposit exists")
        self.deposit = deposit


class NotFoundOrAlreadyHandled(ServiceError):
    pass
