"""Explicit domain exceptions used at adapter and workflow boundaries."""


class WorkflowError(RuntimeError):
    """Base workflow failure."""


class ParameterValidationError(WorkflowError):
    pass


class OptimizerError(WorkflowError):
    pass


class ProcessSupervisorError(WorkflowError):
    """Base error for a supervised external worker."""


class ProcessTimedOut(ProcessSupervisorError):
    """The worker exceeded its deadline and its process tree was verified stopped."""


class ProcessCancelled(ProcessSupervisorError):
    """The worker was cancelled and its process tree was verified stopped."""


class ProcessHeartbeatLost(ProcessSupervisorError):
    """The worker heartbeat became stale and its process tree was verified stopped."""


class ProcessOutcomeUnknown(ProcessSupervisorError):
    """The supervisor could not prove that the worker process tree terminated."""

    def __init__(self, message: str, *, evidence: dict | None = None) -> None:
        super().__init__(message)
        self.evidence = dict(evidence or {})


class SParameterCalculationError(WorkflowError):
    pass


class HFSSExecutionError(WorkflowError):
    pass


class HFSSContractError(HFSSExecutionError):
    pass


class HFSSLicenseLockError(HFSSExecutionError):
    pass


class HFSSStageError(HFSSExecutionError):
    pass


class HFSSProcessOutcomeUnknown(HFSSStageError):
    """HFSS worker/AEDT process-tree termination could not be verified."""

    def __init__(self, message: str, *, evidence: dict | None = None) -> None:
        super().__init__(message)
        self.evidence = dict(evidence or {})


class EvaluationError(WorkflowError):
    pass


class CalibrationError(EvaluationError):
    pass
