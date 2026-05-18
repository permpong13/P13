# -*- coding: utf-8 -*-
from pyrevit import DB
import System

class WarningKiller(DB.IFailuresPreprocessor):
    """
    Class พิเศษที่ทำหน้าที่เป็น 'นักฆ่า Warning'
    จะแอบทำงานอยู่เบื้องหลังเวลากด Transaction Commit
    """
    def PreprocessFailures(self, failuresAccessor):
        # ดึงรายการ Error หรือ Warning ทั้งหมดที่กำลังจะเด้งขึ้นมา
        failures = failuresAccessor.GetFailureMessages()
        
        if failures.Count == 0:
            return DB.FailureProcessingResult.Continue
            
        for failure in failures:
            severity = failure.GetSeverity()
            
            # ถ้าเป็นแค่ Warning (คำเตือนสีส้มๆ เช่น แก้ Type แล้วกระทบตัวอื่น)
            # ให้สั่ง Delete (คือการกด OK ยอมรับเงียบๆ)
            if severity == DB.FailureSeverity.Warning:
                failuresAccessor.DeleteWarning(failure)
                
            # ถ้าเป็น Error ระดับร้ายแรง (สีแดง) เราต้องปล่อยให้มัน Rollback
            # หรือจะพยายาม Resolve ก็ได้ถ้ามีวิธี
            elif severity == DB.FailureSeverity.Error:
                # ลองดูว่ามีวิธีแก้ปัญหาอัตโนมัติไหม (เช่น ขยับระยะให้เอง)
                if failuresAccessor.HasResolutions():
                    failuresAccessor.ResolveFailure(failure)
                    return DB.FailureProcessingResult.ProceedWithCommit
                return DB.FailureProcessingResult.ProceedWithRollBack
                
        # ถ้ากำจัด Warning หมดแล้ว ให้ลุย Commit ต่อเลย!
        return DB.FailureProcessingResult.Continue