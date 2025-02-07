import logging
import os
import csv
import shutil
from typing import Optional, List, Tuple
import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

SUPPORTED_FORMATS = [".nrrd", ".nii", ".nii.gz", ".dcm"]

class ClassAnnotation(ScriptedLoadableModule):
    """Module for classifying medical images using 3D Slicer."""
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Class Annotation"
        self.parent.categories = ["Examples"]
        self.parent.dependencies = []
        self.parent.contributors = ["Lorena Romeo (UMG)"]
        self.parent.helpText = """
        This module allows loading medical images in .nrrd format, 
        displaying them in 3D Slicer, and classifying them.
        """
        self.parent.acknowledgementText = "Developed with 3D Slicer."

class ClassAnnotationWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Widget per l'interfaccia grafica del modulo."""

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = ClassAnnotationLogic()
        self.loadedPatients = []
        self.currentPatientIndex = 0
        self.classificationData = {}
        self.datasetPath = ""
        self.isHierarchical = False
        self.isFlat = False

    def setup(self) -> None:
        """Configura gli elementi dell'interfaccia grafica."""
        ScriptedLoadableModuleWidget.setup(self)

        uiPath = self.resourcePath("UI/ClassAnnotation.ui")
        if not os.path.exists(uiPath):
            slicer.util.errorDisplay(f"UI file not found: {uiPath}", windowTitle="Error")
            return

        uiWidget = slicer.util.loadUI(uiPath)
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.ui.loadButton.clicked.connect(self.onLoadDatasetClicked)
        self.ui.class0Button.clicked.connect(lambda: self.onClassifyImage(0))
        self.ui.class1Button.clicked.connect(lambda: self.onClassifyImage(1))
        self.ui.class2Button.clicked.connect(lambda: self.onClassifyImage(2))
        self.ui.class3Button.clicked.connect(lambda: self.onClassifyImage(3))
        self.ui.class4Button.clicked.connect(lambda: self.onClassifyImage(4))

        self.ui.classificationTable.setColumnCount(2)
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)

    def onLoadDatasetClicked(self):
        """Carica il dataset, aggiorna la tabella e avvia il caricamento del primo paziente."""
        datasetPath = qt.QFileDialog.getExistingDirectory(None, "Select Dataset Folder")
        if not datasetPath:
            return

        self.datasetPath = datasetPath
        self.loadedPatients.clear()
        self.currentPatientIndex = 0
        self.classificationData.clear()
        self.clearTable()

        self.isFlat = self.logic.isFlatDataset(self.datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("Errore: Il dataset contiene sia cartelle che file nella cartella principale. Usa solo un formato!", windowTitle="Errore Dataset")
            return

        # Aggiorna la tabella con il CSV esistente
        self.loadExistingCSV()

        # Controlla se ci sono ancora pazienti non classificati
        nextPatient = self.logic.getNextPatient(self.datasetPath)

        if nextPatient:
            self.loadNextPatient()
        else:
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati classificati! Dati aggiornati dalla tabella.", windowTitle="Fine del Dataset")

    def loadNextPatient(self):
        """Carica il prossimo paziente disponibile nel dataset."""
        nextPatient = self.logic.getNextPatient(self.datasetPath)

        if nextPatient:
            patientID, fileList = nextPatient
            self.currentPatientIndex += 1  # Passa al paziente successivo
            slicer.mrmlScene.Clear(0)  # Pulisce la scena prima di caricare il nuovo paziente
            self.loadPatientImages((patientID, fileList))
        else:
            slicer.mrmlScene.Clear(0)  # Se tutti i pazienti sono classificati, svuota la scena
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati classificati!", windowTitle="Fine del Dataset")

    def loadPatientImages(self, patientData):
        """Carica tutte le immagini di un paziente."""
        patientID, fileList = patientData
        self.loadedPatients = []

        for filePath in fileList:
            volumeNode = slicer.util.loadVolume(filePath)
            if volumeNode:
                self.loadedPatients.append(volumeNode)

        if self.loadedPatients:
            slicer.util.setSliceViewerLayers(background=self.loadedPatients[0])
        else:
            slicer.util.errorDisplay(f"Errore nel caricamento delle immagini del paziente {patientID}", windowTitle="Errore")

    def onClassifyImage(self, classLabel):
        """Classifica il paziente corrente e passa automaticamente al successivo."""
        if not self.loadedPatients:
            slicer.util.errorDisplay("Nessun paziente caricato!", windowTitle="Errore")
            return

        firstVolume = self.loadedPatients[0]
        filePath = firstVolume.GetStorageNode().GetFileName()
        
        # 🔹 Dataset gerarchico: il paziente è la cartella padre
        if self.isHierarchical:
            patientID = os.path.basename(os.path.dirname(filePath))

        # 🔹 Dataset flat: il paziente è la radice del nome file
        else:
            patientID = os.path.basename(filePath).split("_")[0]

        if patientID is None:
            slicer.util.errorDisplay("Errore: impossibile determinare il paziente!", windowTitle="Errore")
            return  

        self.classificationData[patientID] = classLabel
        self.updateTable()
        self.logic.saveClassificationData(self.datasetPath, self.classificationData)
        slicer.mrmlScene.Clear(0)
        self.loadNextPatient()

    def updateTable(self):
        """Aggiorna la tabella di classificazione con i dati attuali."""
        self.clearTable()
        
        if not self.classificationData:
            return  # Se non ci sono dati, non fare nulla

        for idx, (patientID, classLabel) in enumerate(self.classificationData.items()):
            self.ui.classificationTable.insertRow(idx)
            self.ui.classificationTable.setItem(idx, 0, qt.QTableWidgetItem(patientID))
            self.ui.classificationTable.setItem(idx, 1, qt.QTableWidgetItem(str(classLabel)))

    def clearTable(self):
        """Svuota la tabella."""
        self.ui.classificationTable.setRowCount(0)

    def loadExistingCSV(self):
        """Carica un file CSV esistente, aggiorna `classificationData` e la tabella."""
        csvFilePath = os.path.join(self.datasetPath, "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2:
                        self.classificationData[row[0]] = row[1]  # Aggiorna il dizionario con i dati classificati

            self.updateTable()  # Aggiorna la tabella con i dati dal CSV

        except Exception as e:
            slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

    def lastPatientCSV(self):
        """Restituisce l'ultimo paziente classificato dal CSV."""
        return self.logic.getLastPatientFromCSV(self.datasetPath)

class ClassAnnotationLogic(ScriptedLoadableModuleLogic):
    """Logica del modulo."""

    def isFlatDataset(self, datasetPath: str) -> bool:
        """Determina se il dataset è flat (tutti i file nella cartella principale)."""
        files = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f))]
        return any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in files)

    def isHierarchicalDataset(self, datasetPath: str) -> bool:
        """Determina se il dataset è gerarchico (ogni paziente ha una cartella)."""
        subdirs = [d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d))]
        return any(any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in os.listdir(os.path.join(datasetPath, d))) for d in subdirs)

    def getNextPatient(self, datasetPath: str) -> Optional[Tuple[str, List[str]]]:
        """Restituisce il prossimo paziente da classificare, escludendo i pazienti già classificati."""
        
        self.isHierarchical = self.isHierarchicalDataset(datasetPath)
        self.isFlat = self.isFlatDataset(datasetPath)

        # 🔹 1️⃣ Se è un dataset gerarchico
        if self.isHierarchical:
            patientDirs = sorted([
                d for d in os.listdir(datasetPath) 
                if os.path.isdir(os.path.join(datasetPath, d)) and d.lower() != "output"
            ])

            if not patientDirs:
                return None  # Nessun paziente disponibile

            classifiedPatients = self.loadExistingCSV(datasetPath)

            for patientID in patientDirs:
                if patientID not in classifiedPatients:
                    nextPatientPath = os.path.join(datasetPath, patientID)
                    return patientID, self.getPatientFiles(nextPatientPath)

            return None  # Nessun paziente disponibile

        # 🔹 2️⃣ Se è un dataset flat, raggruppa i file per ID paziente
        elif self.isFlat:
            allFiles = sorted([
                f for f in os.listdir(datasetPath) 
                if os.path.isfile(os.path.join(datasetPath, f)) and f.endswith(tuple(SUPPORTED_FORMATS))
            ])

            if not allFiles:
                return None  # Nessun file disponibile

            csvExists = os.path.exists(os.path.join(datasetPath, "classification_results.csv"))
            classifiedPatients = self.loadExistingCSV(datasetPath) if csvExists else []

            patientGroups = {}  # Raggruppiamo i file per ID paziente
            for fileName in allFiles:
                patientID = fileName.split("_")[0]  # Estraggo la radice (ID paziente)
                if patientID not in patientGroups:
                    patientGroups[patientID] = []
                patientGroups[patientID].append(os.path.join(datasetPath, fileName))

            # Troviamo il primo paziente non ancora classificato
            for patientID, files in patientGroups.items():
                if patientID not in classifiedPatients:
                    return patientID, files

            return None  # Nessun paziente disponibile

        return None  # Nessun paziente trovato

    def loadExistingCSV(self, datasetPath: str) -> List[str]:
        """Carica i pazienti già classificati dal CSV e restituisce una lista dei loro ID."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        classifiedPatients = []

        if not os.path.exists(csvFilePath):
            return classifiedPatients  # Se il CSV non esiste, significa che nessun paziente è stato classificato

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2:
                        classifiedPatients.append(row[0])  # Aggiunge l'ID del paziente classificato
        except Exception as e:
            slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classifiedPatients
    
    def getPatientFiles(self, patientPath: str) -> List[str]:
        """Restituisce la lista di file di un paziente, escludendo la cartella output."""
        return [os.path.join(patientPath, f) for f in os.listdir(patientPath) 
                if f.endswith(tuple(SUPPORTED_FORMATS))]

    def getFormattedName(self, volumeNode, isHierarchical: bool, isFlat: bool) -> Optional[str]:
        """Genera il nome formattato per il paziente."""
        if volumeNode is None or volumeNode.GetStorageNode() is None:
            slicer.util.errorDisplay("Errore: il file non è stato caricato correttamente!", windowTitle="Errore")
            return None  

        filePath = volumeNode.GetStorageNode().GetFileName()
        if filePath is None:
            slicer.util.errorDisplay("Errore: il file non ha un percorso valido!", windowTitle="Errore")
            return None

        fileName = os.path.basename(filePath)
        baseName, _ = os.path.splitext(fileName)

        if baseName.endswith(".nii"):
            baseName, _ = os.path.splitext(baseName)

        if isHierarchical:
            patientID = os.path.basename(os.path.dirname(filePath))
            return f"{patientID}_{baseName}"
        else:
            return baseName.split("_")[0]

    def saveClassificationData(self, datasetPath: str, classificationData: dict):
        """Salva i dati di classificazione nel CSV e organizza i file in output in modo gerarchico."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        outputFolder = os.path.join(datasetPath, "output")

        try:
            # Salvataggio nel CSV
            with open(csvFilePath, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Patient ID", "Class"])
                for patientID, classLabel in classificationData.items():
                    writer.writerow([patientID, classLabel])

            # Creiamo la cartella di output se non esiste
            if not os.path.exists(outputFolder):
                os.makedirs(outputFolder)

            # Processiamo ogni paziente classificato
            for patientID, classLabel in classificationData.items():
                classFolder = os.path.join(outputFolder, f"class{classLabel}")

                # Creiamo la cartella della classe se non esiste
                if not os.path.exists(classFolder):
                    os.makedirs(classFolder)

                # Creiamo la cartella del paziente all'interno della classe
                patientFolder = os.path.join(classFolder, patientID)
                if not os.path.exists(patientFolder):
                    os.makedirs(patientFolder)

                # Troviamo i file originali del paziente
                originalFilePaths = self.findOriginalFile(datasetPath, patientID, self.isHierarchical)

                for originalFilePath in originalFilePaths:
                    if originalFilePath:
                        fileName = os.path.basename(originalFilePath)
                        destPath = os.path.join(patientFolder, fileName)

                        # Copia i file nella struttura gerarchica
                        shutil.copy2(originalFilePath, destPath)

        except Exception as e:
            slicer.util.errorDisplay(f"Errore nel salvataggio del CSV: {str(e)}", windowTitle="Errore")

    def findOriginalFile(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Trova tutti i file originali corrispondenti al paziente."""
        originalFiles = []

        for root, _, files in os.walk(datasetPath):
            if "output" in root:
                continue  # Ignoriamo la cartella di output

            for file in files:
                baseName, _ = os.path.splitext(file)

                # Se il dataset è gerarchico, il paziente è una cartella
                if isHierarchical:
                    if os.path.basename(root) == patientID:
                        originalFiles.append(os.path.join(root, file))
                
                # Se è flat, raggruppiamo i file per radice (ID paziente)
                else:
                    if baseName.startswith(patientID):
                        originalFiles.append(os.path.join(root, file))

        return originalFiles

    def getLastPatientFromCSV(self, datasetPath: str) -> Optional[str]:
        """Recupera l'ultimo paziente classificato dal CSV per sapere da dove riprendere."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return None

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                last_row = None
                for row in reader:
                    if len(row) == 2:
                        last_row = row[0]  # Aggiorna il nome dell'ultimo paziente
                return last_row
        except Exception as e:
            slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")
            return None