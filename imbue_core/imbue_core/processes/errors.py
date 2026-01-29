from imbue_core.errors import ExpectedError


class RemoteCommandConnectionError(ExpectedError):
    pass


class ShutdownError(ExpectedError):
    pass


class EnvironmentStoppedError(ExpectedError):
    pass
