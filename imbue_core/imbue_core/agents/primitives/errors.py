class SpecialError(BaseException):
    pass


class ResourceLimitExceeded(SpecialError):
    pass


class DollarLimitExceeded(ResourceLimitExceeded):
    pass


class MaximumSpendExceeded(ResourceLimitExceeded):
    """This happens if you try to make a transation that is larger than your per-hour spend rate"""
