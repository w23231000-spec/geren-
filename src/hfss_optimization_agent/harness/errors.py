"""Explicit domain exceptions used at adapter and workflow boundaries."""


class WorkflowError(RuntimeError):
    """Base workflow failure."""


class ParameterValidationError(WorkflowError):
    pass


class OptimizerError(WorkflowError):
    pass


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


class EvaluationError(WorkflowError):
    pass


class CalibrationError(EvaluationError):
    pass
