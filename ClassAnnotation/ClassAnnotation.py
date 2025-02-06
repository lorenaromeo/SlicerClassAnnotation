import logging
import os
import csv
import re
from typing import Optional

import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

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
    """Widget for the graphical user interface (GUI) of the module."""

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = ClassAnnotationLogic()
        self.loadedImages = []
        self.currentImageIndex = 0
        self.classificationData = {}
        self.datasetPath = ""
        self.isHierarchical = False
        self.isFlat = False

    def setup(self) -> None:
        """Setup the GUI elements."""
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
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID / File Name", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)

    def onLoadDatasetClicked(self):
        """Carica il dataset e avvia il caricamento della prima immagine."""
        datasetPath = qt.QFileDialog.getExistingDirectory(None, "Select Dataset Folder")
        if not datasetPath:
            return

        self.datasetPath = datasetPath
        self.loadedImages.clear()
        self.currentImageIndex = 0
        self.classificationData.clear()
        self.clearTable()

        self.isFlat = self.logic.isFlatDataset(datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("Errore: Il dataset contiene sia cartelle che file .nrrd nella cartella principale. Usa solo un formato!", windowTitle="Errore Dataset")
            return

        self.loadExistingCSV()
        self.loadNextImage()

    def loadNextImage(self):
        """Carica la prossima immagine nel dataset, sia gerarchico che piatto."""
        nextImage = self.logic.getNextImage(self.datasetPath, self.lastPatientCSV())

        if nextImage:
            self.loadSingleImage(nextImage)
        else:
            slicer.util.infoDisplay("Tutte le immagini sono già state classificate!", windowTitle="Fine del Dataset")

    def loadSingleImage(self, imageData):
        """Carica una singola immagine solo se non è già presente nel CSV."""
        patientID, fileName, filePath = imageData
        csvFilePath = os.path.join(self.datasetPath, "classification_results.csv")

        # Se il CSV esiste, controlla se l'immagine è già classificata
        if os.path.exists(csvFilePath):
            try:
                with open(csvFilePath, mode='r') as file:
                    reader = csv.reader(file)
                    next(reader, None)  # Salta l'intestazione
                    
                    for row in reader:
                        if len(row) == 2 and str(row[0]) == f"{patientID}_{fileName.rsplit('.')[0]}":  
                            slicer.util.warningDisplay(
                                "Questa immagine è già stata classificata. Nessuna immagine caricata.",
                                windowTitle="Avviso"
                            )
                            return None  # Non carica nulla se l'immagine è già stata classificata
            
            except Exception as e:
                slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")
                return None  # Esce se c'è un errore nella lettura del CSV

        # Se l'immagine non è già stata classificata, la carica
        volumeNode = slicer.util.loadVolume(filePath)
        if volumeNode:
            self.loadedImages = [volumeNode]
            self.currentImageIndex = 0
            slicer.util.setSliceViewerLayers(background=volumeNode)
            slicer.util.infoDisplay(f"Caricata immagine: {fileName}" + 
                                    (f" (Paziente: {patientID})" if patientID else ""), 
                                    windowTitle="Immagine Caricata")
        else:
            slicer.util.errorDisplay(f"Errore nel caricamento dell'immagine {filePath}", windowTitle="Errore")

    def lastPatientCSV(self):
        """Restituisce l'ultimo paziente classificato dal CSV."""
        return self.logic.getLastPatientFromCSV(self.datasetPath)
    
    def loadExistingCSV(self):
        """Se esiste un file CSV nel dataset, lo carica e aggiorna la tabella."""
        csvFilePath = os.path.join(self.datasetPath, "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return  # Se il CSV non esiste, esce dalla funzione

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2:
                        self.classificationData[row[0]] = row[1]  # Aggiorna il dizionario

            self.updateTable()  # Aggiorna la tabella con i dati letti
        except Exception as e:
            slicer.util.errorDisplay(f"Error reading CSV: {str(e)}", windowTitle="Error")

    def onClassifyImage(self, classLabel):
        """Classifica l'immagine corrente e carica la successiva."""
        if not self.loadedImages:
            slicer.util.errorDisplay("Nessuna immagine caricata!", windowTitle="Errore")
            return

        currentVolume = self.loadedImages[self.currentImageIndex]
        formattedName = self.logic.getFormattedName(currentVolume, self.isHierarchical, self.isFlat)

        self.classificationData[formattedName] = classLabel
        self.updateTable()
        self.logic.saveClassificationData(self.datasetPath, self.classificationData)
        slicer.mrmlScene.Clear(0)
        self.loadNextImage()

    def updateTable(self):
        """Aggiorna la tabella di classificazione."""
        self.clearTable()
        for idx, (fileName, classLabel) in enumerate(self.classificationData.items()):
            self.ui.classificationTable.insertRow(idx)
            self.ui.classificationTable.setItem(idx, 0, qt.QTableWidgetItem(fileName))
            self.ui.classificationTable.setItem(idx, 1, qt.QTableWidgetItem(str(classLabel)))

    def clearTable(self):
        """Svuota la tabella."""
        self.ui.classificationTable.setRowCount(0)

class ClassAnnotationLogic(ScriptedLoadableModuleLogic):
    """Logica del modulo, separata dall'interfaccia grafica."""

    def isHierarchicalDataset(self, datasetPath):
        """Determina se il dataset è gerarchico (se contiene cartelle con file .nrrd all'interno)."""
        if self.isFlatDataset(datasetPath):  
            return False

        subdirs = [d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d))]

        for subdir in subdirs:
            subdirPath = os.path.join(datasetPath, subdir)
            if any(f.endswith(".nrrd") for f in os.listdir(subdirPath)): 
                return True

        return False 
    
    def isFlatDataset(self, datasetPath):
        """Determina se il dataset è piatto (ha file .nrrd nella cartella principale, indipendentemente da cartelle di output)."""
        files = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f))]  
        hasNRRD = any(f.endswith(".nrrd") for f in files) 

        return hasNRRD 

    def getNextImage(self, datasetPath, lastPatient):
        """Restituisce la prossima immagine da classificare, gestendo sia dataset gerarchici che piatti."""
        allImages = []
        isHierarchical = self.isHierarchicalDataset(datasetPath)

        for root, _, files in os.walk(datasetPath):
            for file in sorted(files):
                if file.endswith(".nrrd"):
                    parentFolder = os.path.basename(root) if isHierarchical else None  
                    allImages.append((parentFolder, file, os.path.join(root, file)))

        if not allImages:
            return None

        if lastPatient:
            lastIndex = next((i for i, (p, f, path) in enumerate(allImages) 
                            if (f"{p}_{os.path.splitext(f)[0]}" == lastPatient if p else os.path.splitext(f)[0] == lastPatient)), None)
            if lastIndex is not None and lastIndex < len(allImages) - 1:
                return allImages[lastIndex + 1]

        return allImages[0]  

    def getLastPatientFromCSV(self, datasetPath):
        """Restituisce l'ultimo paziente classificato dal CSV."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return None

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader, None)
                last_row = None
                for row in reader:
                    if len(row) == 2:
                        last_row = row[0]
                return last_row
        except:
            return None
        
    def loadExistingCSV(self, datasetPath):
        """Se esiste un file CSV nel dataset, lo carica e restituisce i dati."""
        classificationData = {}
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return classificationData  

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                for row in reader:
                    if len(row) == 2:
                        classificationData[row[0]] = row[1]  

        except Exception as e:
            slicer.util.errorDisplay(f"Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classificationData

    def getFormattedName(self, volumeNode, isHierarchical, isFlat):
        """Genera il nome formattato per la classificazione."""
        filePath = volumeNode.GetStorageNode().GetFileName()
        fileName = os.path.splitext(os.path.basename(filePath))[0]

        if isHierarchical:
            return f"{os.path.basename(os.path.dirname(filePath))}_{fileName}"  
        elif isFlat:
            return fileName  
        else:
            return fileName  
    
    def saveClassificationData(self, datasetPath, classificationData):
        """Salva i dati di classificazione in un file CSV."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")

        try:
            with open(csvFilePath, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Patient ID / File Name", "Class"])
                for fileName, classLabel in classificationData.items():
                    writer.writerow([fileName, classLabel])
        except Exception as e:
            slicer.util.errorDisplay(f"Errore nel salvataggio del CSV: {str(e)}", windowTitle="Errore")