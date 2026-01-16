import os
import re
import shutil
from typing import List, Set

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

def compute_file_hash(path: str) -> str:
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compute_patient_hashes(fileList):
    import hashlib
    import SimpleITK as sitk
    import os

    def hash_volume(image):
        array = sitk.GetArrayFromImage(image)
        return hashlib.sha256(array.tobytes()).hexdigest()

    hashList = []

    fileList = [
        f for f in fileList
        if os.path.isfile(f) and not os.path.basename(f).startswith('.') 
    ]

    dicomFiles = [f for f in fileList if f.lower().endswith(".dcm")]
    otherFiles = [f for f in fileList if not f.lower().endswith(".dcm")]

    if dicomFiles:
        try:
            reader = sitk.ImageSeriesReader()
            dicomDir = os.path.dirname(dicomFiles[0])
            dicomSeries = reader.GetGDCMSeriesFileNames(dicomDir)
            reader.SetFileNames(dicomSeries)
            image = reader.Execute()
            hashList.append(hash_volume(image))
        except Exception:
            pass  

    for filePath in otherFiles:
        try:
            image = sitk.ReadImage(filePath)
            hashList.append(hash_volume(image))
        except Exception:
            pass  

    if not hashList:
        return [""] 

    combinedHash = hashlib.sha256("".join(hashList).encode()).hexdigest()
    return [combinedHash]


def remove_supported_extension(fname: str) -> str:
    """
    Rimuove l'estensione dal nome file, gestendo anche .nii.gz.
    Restituisce il nome senza estensione.
    """
    lower = fname.lower()
    if lower.endswith(".nii.gz"):
        return fname[:-7]  # len(".nii.gz") = 7
    root, _ = os.path.splitext(fname)
    return root


def extract_patient_id_from_name(fname: str) -> str:
    """
    Extracts the patient ID from filenames of the form:
    <patientID>-<modality>.ext  or  <patientID>_<modality>.ext

    - The separator is either '-' or '_'.
    - Both patientID and modality may contain alphanumeric characters.
    - The patient ID is always the substring preceding the first separator.
    """
    base = os.path.basename(fname)
    stem = remove_supported_extension(base)

    # Split on the first '-' or '_' only
    parts = re.split(r"[-_]", stem, maxsplit=1)

    # The first token is always the patient ID
    return parts[0] if parts else stem