import logging
import os
import csv
import shutil
from typing import Optional, List, Tuple
from DICOMLib import DICOMUtils
import SimpleITK as sitk
import sitkUtils
import vtk
import qt
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
import random

SUPPORTED_FORMATS = [".nrrd", ".nii", ".nii.gz", ".dcm", ".DCM"]

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
        self.manualReviewMode = False  

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

        # Inizializza i contatori delle classi
        self.classCounters = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  

        # Associa i QLCDNumber alle rispettive classi
        self.classLCDs = {
            0: self.ui.lcdClass0,
            1: self.ui.lcdClass1,
            2: self.ui.lcdClass2,
            3: self.ui.lcdClass3,
            4: self.ui.lcdClass4
        }

        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)

        self.ui.reviewButton.clicked.connect(self.onReviewPatientClicked)
        self.ui.checkBox.toggled.connect(self.onCheckToggled)
        self.ui.nextPatientButton.clicked.connect(self.onLoadNextRandomPatient)


        self.ui.classificationTable.setColumnCount(2)
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)


    def disableClassificationButtons(self, disable=True):
        """Disabilita o abilita i pulsanti di classificazione, eccetto se siamo in modalità di revisione manuale."""
        if self.manualReviewMode:
            disable = False  # Se siamo in revisione manuale, i pulsanti devono restare attivi
        self.ui.class0Button.setEnabled(not disable)
        self.ui.class1Button.setEnabled(not disable)
        self.ui.class2Button.setEnabled(not disable)
        self.ui.class3Button.setEnabled(not disable)
        self.ui.class4Button.setEnabled(not disable)

    def onLoadDatasetClicked(self):
        """Carica il dataset, aggiorna la tabella e avvia il caricamento del primo paziente."""
        datasetPath = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), "Select Dataset Folder")
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

        self.classificationData = self.logic.loadExistingCSV(self.datasetPath)
        self.updateTable()  # Aggiorna la tabella con i dati caricati

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)
        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)  

        self.populatePatientDropdown()

        nextPatient = self.logic.getNextPatient(self.datasetPath)
        if nextPatient:
            self.loadNextPatient()
        else:
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati classificati! Dati aggiornati dalla tabella.", windowTitle="Fine del Dataset")


    def onCheckToggled(self, checked: bool) -> None:
        """Seleziona N casi random per ogni classe e li prepara per la visualizzazione."""
        
        if checked:
            try:
                num_cases = int(self.ui.casesInput.text)  
                if num_cases <= 0:
                    slicer.util.errorDisplay("⚠️ Inserisci un numero valido di pazienti per classe!", windowTitle="Errore")
                    self.ui.checkBox.setChecked(False)
                    return
            except ValueError:
                slicer.util.errorDisplay("⚠️ Inserisci un numero numerico valido!", windowTitle="Errore")
                self.ui.checkBox.setChecked(False)
                return

            # Reset della lista di pazienti selezionati
            self.randomPatientsList = []
            self.currentRandomPatientIndex = 0

            # Carica il dataset classificato
            classifiedPatients = self.logic.loadExistingCSV(self.datasetPath)

            if not classifiedPatients:
                slicer.util.errorDisplay("⚠️ Nessun paziente classificato disponibile!", windowTitle="Errore")
                self.ui.checkBox.setChecked(False)
                return

            # Raggruppa i pazienti per classe
            patientsByClass = {}
            for patientID, classLabel in classifiedPatients.items():
                if classLabel not in patientsByClass:
                    patientsByClass[classLabel] = []
                patientsByClass[classLabel].append(patientID)

            # Seleziona casualmente `num_cases` pazienti per ogni classe
            for classLabel, patients in patientsByClass.items():
                if len(patients) > num_cases:
                    selectedPatients = random.sample(patients, num_cases)
                else:
                    selectedPatients = patients  # Se ci sono meno pazienti, li prende tutti
                self.randomPatientsList.extend(selectedPatients)

            random.shuffle(self.randomPatientsList)  # Mischia i pazienti per renderli casuali
            
            # Se ci sono pazienti da caricare, avvia il primo
            if self.randomPatientsList:
                self.onLoadNextRandomPatient()
            else:
                slicer.util.errorDisplay("⚠️ Nessun paziente disponibile per la revisione!", windowTitle="Errore")
                self.ui.checkBox.setChecked(False)
        else:
            slicer.mrmlScene.Clear(0)  # Pulisce la scena se la spunta viene disattivata

    def onReviewPatientClicked(self):
        """Carica il paziente selezionato dal menu a tendina per la revisione manuale."""
        patientID = self.ui.patientDropdown.currentText

        if patientID == "Select a patient to review":
            slicer.util.errorDisplay("⚠️ Nessun paziente selezionato per la revisione!", windowTitle="Errore")
            return

        patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

        if patientFiles:
            slicer.mrmlScene.Clear(0)  # Pulisce la scena
            self.loadPatientImages((patientID, patientFiles))  # Carica le immagini
            self.manualReviewMode = True  # Attiva la modalità revisione manuale
            self.disableClassificationButtons(False)  # Abilita i pulsanti di classificazione
        else:
            slicer.util.errorDisplay(f"⚠️ Nessuna immagine trovata per il paziente {patientID}!", windowTitle="Errore")

    def onLoadNextRandomPatient(self):
        """Carica il prossimo paziente casuale dalla lista selezionata."""
        
        if not self.randomPatientsList:
            slicer.util.errorDisplay("⚠️ Nessun paziente selezionato per Random Check!", windowTitle="Errore")
            return

        # Controlla se ci sono ancora pazienti da caricare
        if self.currentRandomPatientIndex < len(self.randomPatientsList):
            patientID = self.randomPatientsList[self.currentRandomPatientIndex]
            patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

            if patientFiles:
                slicer.mrmlScene.Clear(0)  # Pulisce la scena
                self.loadPatientImages((patientID, patientFiles))
            else:
                slicer.util.errorDisplay(f"⚠️ Nessuna immagine trovata per il paziente {patientID}!", windowTitle="Errore")

            self.currentRandomPatientIndex += 1  # Passa al paziente successivo

        else:
            slicer.util.infoDisplay("✔️ Tutti i pazienti selezionati sono stati rivisti!", windowTitle="Fine Random Check")
            self.ui.checkBox.setChecked(False)  # Disattiva la modalità Random Check

    def loadNextPatient(self):
        """Carica il prossimo paziente disponibile nel dataset."""
        self.manualReviewMode = False  # Disattiva la revisione manuale

        nextPatient = self.logic.getNextPatient(self.datasetPath)

        if nextPatient:
            patientID, fileList = nextPatient
            self.currentPatientIndex += 1  
            slicer.mrmlScene.Clear(0)  # Pulisce la scena prima di caricare il nuovo paziente
            self.loadPatientImages((patientID, fileList))
            self.disableClassificationButtons(False)  # Abilita i pulsanti di classificazione
        else:
            slicer.mrmlScene.Clear(0)  
            slicer.util.infoDisplay("✔️ Tutti i pazienti sono stati classificati!", windowTitle="Fine del Dataset")
            self.disableClassificationButtons(True)  # Disabilita i pulsanti di classificazione

    def loadPatientImages(self, patientData):
        """Carica tutte le immagini di un paziente rispettando la gestione DICOM e altri formati."""
        
        patientID, fileList = patientData
        self.loadedPatients = []
        self.currentPatientID = patientID  

        # **Usiamo la lista SUPPORTATI per separare i file**
        dicomExtensions = (".dcm", ".DCM")
        otherExtensions = tuple(ext for ext in SUPPORTED_FORMATS if ext.lower() not in dicomExtensions)

        dicomFiles = [f for f in fileList if f.lower().endswith(dicomExtensions)]
        otherFiles = [f for f in fileList if f.lower().endswith(otherExtensions)]

        try:
            if dicomFiles:
                dicomDir = os.path.dirname(dicomFiles[0])  
                reader = sitk.ImageSeriesReader()
                dicomSeries = reader.GetGDCMSeriesFileNames(dicomDir)  
                reader.SetFileNames(dicomSeries)
                sitkImage = reader.Execute()  # Carica l'intera serie DICOM

                # Creiamo un nodo volume per il DICOM con il nome del paziente
                volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                volumeNode.SetName(f"{patientID}_DICOM")  # Nome leggibile in Slicer
                sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                if volumeNode:
                    self.loadedPatients.append(volumeNode)

            for filePath in otherFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath)  
                    volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                    volumeNode.SetName(f"{patientID}_{os.path.basename(filePath)}") 
                    sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                    if volumeNode:
                        self.loadedPatients.append(volumeNode)

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Errore nel caricamento di {filePath}: {str(e)}", windowTitle="Errore")

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore generale nel caricamento del paziente {patientID}: {str(e)}", windowTitle="Errore")

        if self.loadedPatients:
            slicer.util.setSliceViewerLayers(background=self.loadedPatients[0])
            slicer.app.processEvents()
            slicer.util.resetSliceViews()
        else:
            slicer.util.errorDisplay(f"❌ Errore: nessuna immagine caricata per {patientID}", windowTitle="Errore")

    def onClassifyImage(self, classLabel):
        """Classifica il paziente corrente e aggiorna il CSV e i contatori delle classi."""
        
        if not self.loadedPatients:
            slicer.util.errorDisplay("❌ Nessun paziente caricato!", windowTitle="Errore")
            return

        if not self.currentPatientID:
            slicer.util.errorDisplay("❌ Errore: impossibile determinare il paziente!", windowTitle="Errore")
            return  

        if self.currentPatientID in self.classificationData and not self.manualReviewMode:
            slicer.util.errorDisplay("⚠️ Questo paziente è già stato classificato!", windowTitle="Errore")
            return  

        self.classificationData[self.currentPatientID] = classLabel

        self.logic.saveClassificationData(self.datasetPath, self.classificationData)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)
        for classLabel, count in self.classCounters.items():
            self.classLCDs[classLabel].display(count)  

        self.updateTable()
        self.populatePatientDropdown()

        if not self.manualReviewMode:  # Solo se NON siamo in revisione manuale
            slicer.mrmlScene.Clear(0)
            self.loadNextPatient()
            
    def updateTable(self):
        """Aggiorna la tabella di classificazione con i dati attuali e colora le righe."""
        self.clearTable()

        if not self.classificationData:
            return 

        classColors = {
            0: "#FF4C4C",  # Rosso
            1: "#4CAF50",  # Verde
            2: "#FF9800",  # Arancione
            3: "#FFD700",  # Giallo
            4: "#2196F3"   # Azzurro 
        }

        for idx, (patientID, classLabel) in enumerate(self.classificationData.items()):
            self.ui.classificationTable.insertRow(idx)

            patientItem = qt.QTableWidgetItem(patientID)
            classItem = qt.QTableWidgetItem(str(classLabel))

            if classLabel in classColors:
                color = qt.QColor(classColors[classLabel])  # Converte in un oggetto QColor
                patientItem.setBackground(color)
                classItem.setBackground(color)

            # Blocca la modifica delle celle
            patientItem.setFlags(qt.Qt.ItemIsSelectable | qt.Qt.ItemIsEnabled)
            classItem.setFlags(qt.Qt.ItemIsSelectable | qt.Qt.ItemIsEnabled)

            # Inserisci gli elementi nella tabella
            self.ui.classificationTable.setItem(idx, 0, patientItem)
            self.ui.classificationTable.setItem(idx, 1, classItem)

    def clearTable(self):
        """Svuota la tabella."""
        self.ui.classificationTable.setRowCount(0)


    def populatePatientDropdown(self):
        """Aggiorna il menu a tendina con i pazienti classificati."""
        self.ui.patientDropdown.clear()  

        self.ui.patientDropdown.addItem("Select a patient to review")

        classifiedPatients = self.logic.loadExistingCSV(self.datasetPath) 
        if not classifiedPatients:
            return  

        for patientID in sorted(classifiedPatients):
            self.ui.patientDropdown.addItem(patientID)

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
        """Restituisce il prossimo paziente da classificare, escludendo quelli già classificati."""

        self.isHierarchical = self.isHierarchicalDataset(datasetPath)
        self.isFlat = self.isFlatDataset(datasetPath)

        classifiedPatients = self.loadExistingCSV(datasetPath)  

        if self.isHierarchical:
            patientDirs = sorted([
                d for d in os.listdir(datasetPath) 
                if os.path.isdir(os.path.join(datasetPath, d)) and d.lower() != "output"
            ])

            for patientID in patientDirs:
                if patientID not in classifiedPatients:
                    nextPatientPath = os.path.join(datasetPath, patientID)
                    return patientID, self.getPatientFiles(nextPatientPath)

        elif self.isFlat:
            allFiles = sorted([
                f for f in os.listdir(datasetPath) 
                if os.path.isfile(os.path.join(datasetPath, f)) and f.endswith(tuple(SUPPORTED_FORMATS))
            ])

            patientGroups = {}
            for fileName in allFiles:
                patientID = fileName.split("_")[0]  
                if patientID not in patientGroups:
                    patientGroups[patientID] = []
                patientGroups[patientID].append(os.path.join(datasetPath, fileName))

            for patientID, files in patientGroups.items():
                if patientID not in classifiedPatients:
                    return patientID, files

        return None  

    def loadExistingPatientsFromCSV(self, csvFilePath: str) -> dict:
        """Carica i pazienti esistenti dal CSV, mantenendo anche quelli non classificati."""
        
        existingPatients = {}

        if not os.path.exists(csvFilePath):
            return existingPatients  # Se il file non esiste, ritorna un dizionario vuoto

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2:
                        patientID = row[0]
                        classLabel = row[1] if row[1].isdigit() else None  # Mantiene None se non è classificato
                        existingPatients[patientID] = int(classLabel) if classLabel is not None else None

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return existingPatients
        
    def getPatientFiles(self, patientPath: str) -> List[str]:
        """Restituisce la lista di file di un paziente, escludendo la cartella output."""

        if not os.path.exists(patientPath):
            return []

        files = [
            os.path.join(patientPath, f)
            for f in os.listdir(patientPath)
            if f.endswith(tuple(SUPPORTED_FORMATS))
        ]

        return files

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
        """Salva i dati di classificazione nel CSV e organizza i file in cartelle di output."""

        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        outputFolder = os.path.join(datasetPath, "output")

        try:
            # Recupera i pazienti già esistenti nel CSV
            existingPatients = self.loadExistingPatientsFromCSV(csvFilePath)

            # Aggiorna i dati con le nuove classificazioni
            for patientID, classLabel in classificationData.items():
                existingPatients[patientID] = classLabel

            # Scrive il file CSV aggiornato
            with open(csvFilePath, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Patient ID", "Class"])
                for patientID, classLabel in sorted(existingPatients.items()):  # Ordina per ID paziente
                    writer.writerow([patientID, classLabel if classLabel is not None else ""])

            # Crea la cartella output se non esiste
            if not os.path.exists(outputFolder):
                os.makedirs(outputFolder)

            # Organizza i pazienti nelle cartelle delle classi
            for patientID, classLabel in existingPatients.items():
                if classLabel is not None:
                    classFolder = os.path.join(outputFolder, f"class{classLabel}")
                    if not os.path.exists(classFolder):
                        os.makedirs(classFolder)

                    self.movePatientIfReclassified(outputFolder, patientID, classLabel)

                    patientFolder = os.path.join(classFolder, patientID)
                    if not os.path.exists(patientFolder):
                        os.makedirs(patientFolder)

                    originalFilePaths = self.findOriginalFile(datasetPath, patientID, self.isHierarchical)
                    for originalFilePath in originalFilePaths:
                        if originalFilePath:
                            fileName = os.path.basename(originalFilePath)
                            destPath = os.path.join(patientFolder, fileName)
                            shutil.copy2(originalFilePath, destPath)

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nel salvataggio del CSV: {str(e)}", windowTitle="Errore")


    def findOriginalFile(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Trova tutti i file originali corrispondenti al paziente, gestendo sia dataset gerarchici che flat."""
        originalFiles = []

        for root, _, files in os.walk(datasetPath):
            if "output" in root:
                continue  

            for file in files:
                baseName, _ = os.path.splitext(file)

                # Dataset gerarchico: il paziente è una cartella
                if isHierarchical:
                    if os.path.basename(root) == patientID:
                        originalFiles.append(os.path.join(root, file))
                
                # Dataset flat: trova tutti i file che iniziano con l'ID paziente
                else:
                    if baseName.startswith(patientID):
                        originalFiles.append(os.path.join(root, file))

        return originalFiles


    def movePatientIfReclassified(self, outputFolder: str, patientID: str, newClass: str):
        """Sposta la cartella del paziente nella nuova classe se il paziente è stato riclassificato."""

        # Scansioniamo le classi già esistenti dentro output
        for classFolder in os.listdir(outputFolder):
            currentClassPath = os.path.join(outputFolder, classFolder)

            if os.path.isdir(currentClassPath):  # Assicuriamoci che sia una cartella
                patientFolderPath = os.path.join(currentClassPath, patientID)

                # Se il paziente è già in un'altra cartella di classe, lo spostiamo
                if os.path.exists(patientFolderPath) and classFolder != f"class{newClass}":
                    newClassFolder = os.path.join(outputFolder, f"class{newClass}")
                    if not os.path.exists(newClassFolder):
                        os.makedirs(newClassFolder)

                    newPatientPath = os.path.join(newClassFolder, patientID)
                    shutil.move(patientFolderPath, newPatientPath)

                    # Se la vecchia cartella di classe è vuota, la eliminiamo
                    if not os.listdir(currentClassPath):
                        shutil.rmtree(currentClassPath)

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
        
    def getPatientFilesForReview(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
            """Trova le immagini di un paziente già classificato."""
            patientFiles = []

            if isHierarchical:
                patientPath = os.path.join(datasetPath, patientID)
                if os.path.exists(patientPath):
                    patientFiles = [os.path.join(patientPath, f) for f in os.listdir(patientPath) if f.endswith(tuple(SUPPORTED_FORMATS))]
            else:
                # Dataset flat: trova tutti i file che iniziano con il patientID
                for file in os.listdir(datasetPath):
                    if file.startswith(patientID) and file.endswith(tuple(SUPPORTED_FORMATS)):
                        patientFiles.append(os.path.join(datasetPath, file))

            return patientFiles
    
    def loadExistingCSV(self, datasetPath: str) -> dict:
        """Carica i pazienti già classificati dal CSV e restituisce un dizionario con i loro ID e classi."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        classifiedPatients = {}

        if not os.path.exists(csvFilePath):
            return classifiedPatients  # Se il CSV non esiste, restituisce un dizionario vuoto

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2:
                        patientID = row[0]
                        classLabel = row[1] if row[1].isdigit() else None  # Mantiene None se non classificato
                        classifiedPatients[patientID] = int(classLabel) if classLabel is not None else None

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classifiedPatients
    

    def countPatientsPerClassFromCSV(self, datasetPath: str):  
        """Conta il numero di pazienti per ciascuna classe leggendo dal CSV."""
        csvFilePath = os.path.join(datasetPath, "classification_results.csv")
        classCounts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}  # Inizializza i contatori a 0

        if not os.path.exists(csvFilePath):
            return classCounts  # Se il CSV non esiste, restituisce i contatori a 0

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  # Salta l'intestazione
                for row in reader:
                    if len(row) == 2 and row[1].isdigit():  # Assicura che la riga contenga una classe valida
                        classLabel = int(row[1])
                        if classLabel in classCounts:
                            classCounts[classLabel] += 1

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classCounts