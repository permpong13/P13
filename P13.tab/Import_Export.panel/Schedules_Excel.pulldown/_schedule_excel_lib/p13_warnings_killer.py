# -*- coding: utf-8 -*-
from pyrevit import DB


class WarningKiller(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, failures_accessor):
        for failure in failures_accessor.GetFailureMessages():
            severity = failure.GetSeverity()
            if severity == DB.FailureSeverity.Warning:
                failures_accessor.DeleteWarning(failure)
            elif severity == DB.FailureSeverity.Error:
                if failures_accessor.HasResolutions():
                    failures_accessor.ResolveFailure(failure)
                    return DB.FailureProcessingResult.ProceedWithCommit
                return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue
