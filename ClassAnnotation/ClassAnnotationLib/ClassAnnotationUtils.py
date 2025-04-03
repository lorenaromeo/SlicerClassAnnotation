import os
import shutil
from typing import List

def movePatientIfReclassified(outputFolder: str, patientID: str, newClass: str):    
        """Moves the patient folder to the new class if reclassified."""

        for classFolder in os.listdir(outputFolder):
            currentClassPath = os.path.join(outputFolder, classFolder)

            if os.path.isdir(currentClassPath):
                patientFolderPath = os.path.join(currentClassPath, patientID)

                if os.path.exists(patientFolderPath) and classFolder != f"class{newClass}":
                    newClassFolder = os.path.join(outputFolder, f"class{newClass}")
                    if not os.path.exists(newClassFolder):
                        os.makedirs(newClassFolder)

                    newPatientPath = os.path.join(newClassFolder, patientID)
                    shutil.move(patientFolderPath, newPatientPath)

                    if not os.listdir(currentClassPath):
                        shutil.rmtree(currentClassPath)
                        

def findOriginalFile(datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Finds all original files corresponding to a patient, handling both hierarchical and flat datasets."""
        originalFiles = []

        for root, _, files in os.walk(datasetPath):
            if "output" in root:
                continue  

            for file in files:
                baseName, _ = os.path.splitext(file)

                if isHierarchical:
                    if os.path.basename(root) == patientID:
                        originalFiles.append(os.path.join(root, file))
    
                else:
                    if baseName.startswith(patientID):
                        originalFiles.append(os.path.join(root, file))

        return originalFiles
