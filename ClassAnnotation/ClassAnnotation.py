import logging
import os
import csv
import shutil
import ctk
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
import numpy as np

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
    """Widget for the graphical user interface."""

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
        self.inRandomView = False  
        self.allPatientsClassified = False  
        self.randomPatientsList = []  
        self.currentRandomPatientIndex = 0  
        self.numCasesPerClass = 5 

    def setup(self) -> None:
        """Sets up the UI components."""
        ScriptedLoadableModuleWidget.setup(self)

        uiPath = self.resourcePath("UI/ClassAnnotation.ui")
        if not os.path.exists(uiPath):
            slicer.util.errorDisplay(f"UI file not found: {uiPath}", windowTitle="Error")
            return

        uiWidget = slicer.util.loadUI(uiPath)
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        self.classButtons = {}
        self.classLCDs = {}
        self.classCounters = {}

        self.ui.loadButton.clicked.connect(self.onLoadDatasetClicked)
        self.ui.reviewButton.clicked.connect(self.onReviewPatientClicked)
        self.ui.checkBox.toggled.connect(self.onCheckToggled)
        self.ui.nextPatientButton.clicked.connect(self.onLoadNextRandomPatient)
        self.ui.generateClassesButton.clicked.connect(self.generateClassButtons)  

        self.ui.casesInput.setText("5")  
        self.ui.casesInput.setPlaceholderText("")  
   
        self.ui.classificationTable.setColumnCount(2)
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        self.ui.classificationTable.itemSelectionChanged.connect(self.onPatientSelected)

        self.ui.classCountInput.valueChanged.connect(self.onClassCountChanged)

        self.disableAllButtons(True)
        self.updateButtonStates()

    def generateClassButtons(self):
        """Remove all existing elements and regenerate the classification buttons and counters with updated data."""

        numClasses = self.ui.classCountInput.value  

        classificationLayout = self.ui.classificationGroupBox.layout()

        if classificationLayout is None:
            slicer.util.errorDisplay("❌ Error: Missing layout in classificationGroupBox!", windowTitle="Error")
            return

        # rimozione dei widget presenti
        while classificationLayout.count():
            item = classificationLayout.takeAt(0)
            if item:
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    while item.layout().count():
                        sub_item = item.layout().takeAt(0)
                        if sub_item.widget():
                            sub_item.widget().deleteLater()
                    item.layout().deleteLater()

        self.classButtons.clear()
        self.classLCDs.clear()

        # Recupera il conteggio aggiornato dei casi per classe
        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)

        # Crea un nuovo layout a griglia
        gridLayout = qt.QGridLayout()
        gridLayout.setSpacing(5)
        gridLayout.setContentsMargins(10, 10, 10, 10)

        headerLabel = qt.QLabel("Current Cases per Class")
        headerLabel.setAlignment(qt.Qt.AlignCenter)
        headerLabel.setStyleSheet("font-size: 12px; font-weight: bold; padding-bottom: 5px;")
        gridLayout.addWidget(headerLabel, 0, 1)  

        for classLabel in range(numClasses):
            row = classLabel + 1  

            button = qt.QPushButton(f"Class {classLabel}")
            button.setStyleSheet(f"""
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 {self.getLighterColor(classLabel)}, 
                            stop:0.5 {self.getMainColor(classLabel)}, 
                            stop:1 {self.getDarkerColor(classLabel)});
                color: black;
                font-weight: bold;
                font-size: 14px;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid #555;
                box-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
            """)
            button.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _, lbl=classLabel: self.onClassifyImage(lbl))
            self.classButtons[classLabel] = button

            lcdCounter = qt.QLCDNumber()
            lcdCounter.setDigitCount(2)
            lcdCounter.display(self.classCounters.get(classLabel, 0))  
            lcdCounter.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
            lcdCounter.setMinimumHeight(30)
            self.classLCDs[classLabel] = lcdCounter

            gridLayout.addWidget(button, row, 0)
            gridLayout.addWidget(lcdCounter, row, 1)

        classificationLayout.addLayout(gridLayout)

        self.ui.classificationGroupBox.setLayout(classificationLayout)
        self.ui.classificationGroupBox.update()

    def getMainColor(self, classLabel):
        """Main Color."""
        mainColors = {
            0: "#FF7777",  # Rosso morbido
            1: "#66BB66",  # Verde bilanciato
            2: "#FFBB55",  # Arancione caldo
            3: "#FFDD55",  # Giallo luminoso
            4: "#5599FF",  # Blu leggero
            5: "#B266FF",  # Viola acceso
            6: "#33CCCC",  # Azzurro equilibrato
            7: "#88C766",  # Verde pastello più intenso
            8: "#FF8866",  # Corallo vibrante
            9: "#778899"   # Grigio bluastro
        }
        return mainColors.get(classLabel, "#DDDDDD")

    def getLighterColor(self, classLabel):
        """Lighter Color."""
        lighterColors = {
            0: "#FFAAAA",
            1: "#99DD99",
            2: "#FFD699",
            3: "#FFF2A1",
            4: "#99CCFF",
            5: "#D3A6FF",
            6: "#66E0E0",
            7: "#B0E68C",
            8: "#FFB299",
            9: "#AABBCD"
        }
        return lighterColors.get(classLabel, "#EEEEEE")

    def getDarkerColor(self, classLabel):
        """Darker Color."""
        darkerColors = {
            0: "#E55A5A",
            1: "#4DA64D",
            2: "#E69A33",
            3: "#E6C233",
            4: "#4477CC",
            5: "#8A4FCC",
            6: "#2E9999",
            7: "#77A94D",
            8: "#CC6644",
            9: "#667788"
        }
        return darkerColors.get(classLabel, "#BBBBBB")

    def updateLCDCounters(self):
        """Update the LCD counters with the number of classified cases for each class."""
        
        # Conta i pazienti per ogni classe
        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)

        for classLabel, count in self.classCounters.items():
            if classLabel not in self.classLCDs:
            
                lcdCounter = qt.QLCDNumber()
                lcdCounter.setDigitCount(2)
                lcdCounter.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
                lcdCounter.setMinimumHeight(30)
                self.classLCDs[classLabel] = lcdCounter
                self.ui.classificationGroupBox.layout().addWidget(lcdCounter) 

            self.classLCDs[classLabel].display(count)
        
    def getClassColor(self, classLabel):
        """Returns a predefined color for the classes."""
        colors = ["#FF4C4C", "#4CAF50", "#FF9800", "#FFD700", "#2196F3", "#9C27B0", "#00BCD4", "#8BC34A", "#FF5722", "#607D8B"]
        return colors[classLabel % len(colors)]
    
    def onClassCountChanged(self):
        """Check if the number of classes is lower than the highest existing class and generate a warning."""
        
        maxClass = 4  
        existingClasses = [c for c in self.classificationData.values() if c is not None]
        if existingClasses:
            maxClass = max(existingClasses)

        minRequiredClasses = maxClass + 1  

        currentNumClasses = self.ui.classCountInput.value

        if currentNumClasses < minRequiredClasses:
            slicer.util.warningDisplay(
                f"⚠️ Number of classes cannot be lower than {minRequiredClasses} "
                f"because at least one patient is classified as Class {maxClass}.",
                windowTitle="Invalid Class Count"
            )

            self.ui.classCountInput.blockSignals(True)  
            self.ui.classCountInput.setValue(minRequiredClasses)
            self.ui.classCountInput.blockSignals(False)

    def disableAllButtons(self, disable=True):
        """Enable or disable all UI elements."""
        for button in self.classButtons.values():
            button.setEnabled(not disable)
            
        self.ui.reviewButton.setEnabled(not disable)
        self.ui.checkBox.setEnabled(not disable)
        self.ui.patientDropdown.setEnabled(not disable)
        self.ui.casesInput.setEnabled(not disable)

    def disableClassificationButtons(self, disable: bool):
        """Enable or disable only classification buttons."""
        for button in self.classButtons.values():
            button.setEnabled(not disable)

    def updateButtonStates(self):
        """Update button states based on the current situation."""
        datasetLoaded = bool(self.datasetPath)
        self.allPatientsClassified = datasetLoaded and None not in self.classificationData.values()

        if not datasetLoaded:
            self.disableAllButtons(True)
            self.ui.nextPatientButton.setEnabled(False)
            return  

        self.disableAllButtons(False)
        self.disableClassificationButtons(self.inRandomView)
        self.ui.reviewButton.setEnabled(not self.inRandomView)

        enableNextRandom = self.allPatientsClassified and self.ui.checkBox.isChecked()
        self.ui.nextPatientButton.setEnabled(enableNextRandom)

        if self.manualReviewMode:
            self.ui.checkBox.setChecked(False)


    def onLoadDatasetClicked(self):
        """Load the dataset, update the table, and correctly set the default number of classes."""
        
        confirm = qt.QMessageBox()
        confirm.setIcon(qt.QMessageBox.Question)
        confirm.setWindowTitle("Load Dataset")
        confirm.setText("Loading a new dataset will clear the scene. Do you want to continue?")
        
        yesButton = confirm.addButton(qt.QMessageBox.Yes)
        noButton = confirm.addButton(qt.QMessageBox.No)
        
        confirm.setDefaultButton(yesButton)
        confirm.setEscapeButton(noButton)

        confirm.exec_()

        if confirm.clickedButton() == noButton:
            slicer.util.infoDisplay("Dataset loading cancelled.", windowTitle="Cancelled")
            return  

        slicer.mrmlScene.Clear(0)
        self.updateTable()
        self.currentPatientID = ""  

        datasetPath = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), "Select Dataset Folder")
        if not datasetPath:
            slicer.util.errorDisplay("⚠️ No dataset selected!", windowTitle="Error")
            return

        self.datasetPath = datasetPath
        self.loadedPatients.clear()
        self.currentPatientIndex = 0
        self.classificationData.clear()
        self.clearTable()
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0

        self.isFlat = self.logic.isFlatDataset(self.datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("⚠️ Dataset contains both folders and files. Use a single format!", windowTitle="Error")
            self.disableAllButtons(True)
            return

        self.classificationData = self.logic.loadExistingCSV(self.datasetPath)
        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)

        if len(allPatientIDs) == 0:
            slicer.util.errorDisplay("⚠️ No patients found in the dataset! Please check your data.", windowTitle="Error")
            return
     
        if not self.classificationData:
            slicer.util.infoDisplay("⚠️ The dataset needs to be classified. Starting classification mode.", windowTitle="Dataset Not Classified")
            self.allPatientsClassified = False  
        else:
            allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath) 

            self.allPatientsClassified = all(
                self.classificationData[patientID] is not None for patientID in allPatientIDs
            )

            if self.allPatientsClassified:
                slicer.util.infoDisplay("✔️ The dataset is fully classified. Loading the first patient.", windowTitle="Dataset Fully Classified")

        maxClass = 4 
        if self.classificationData:
            existingClasses = [c for c in self.classificationData.values() if c is not None]
            if existingClasses:
                maxClass = max(existingClasses)


        defaultNumClasses = max(5, maxClass + 1)  
        self.ui.classCountInput.setValue(defaultNumClasses)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)

        self.generateClassButtons()

        for classLabel, count in self.classCounters.items():
            if classLabel in self.classLCDs:
                self.classLCDs[classLabel].display(count)

        self.populatePatientDropdown()

        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)  
        print("All patients:", allPatientIDs)
        print("All patients classified?", self.allPatientsClassified)

        if not allPatientIDs:
            slicer.util.errorDisplay("⚠️ No patients found in the dataset!", windowTitle="Error")
            return  

        if self.allPatientsClassified:
            firstPatientID = allPatientIDs[0]
        else:
            for patientID in allPatientIDs:
                if self.classificationData.get(patientID) is None:  
                    firstPatientID = patientID
                    break
            else:
                firstPatientID = allPatientIDs[0]  

        firstPatientFiles = self.logic.getPatientFilesForReview(self.datasetPath, firstPatientID, self.isHierarchical)

        if firstPatientFiles:
            self.currentPatientID = firstPatientID
            self.loadPatientImages((firstPatientID, firstPatientFiles))
            self.disableAllButtons(False)
        else:
            slicer.util.errorDisplay(f"⚠️ No images found for patient {firstPatientID}!", windowTitle="Error")

        self.ui.labelInputPath.setText('Input Path: ' + self.datasetPath)
        outputFolder = os.path.join(datasetPath, "output")
        self.ui.labelOutputPath.setText('Output Path: '+ outputFolder)

        self.updateButtonStates()
            
            
    def onCheckToggled(self, checked: bool) -> None:
        """Activates or deactivates random review and manages button states."""
        if checked:
            self.manualReviewMode = False
            self.ui.reviewButton.setEnabled(False)
            self.ui.checkBox.setChecked(True)

        
            self.classificationData = self.logic.loadExistingCSV(self.datasetPath)
            self.allPatientsClassified = None not in self.classificationData.values()

            if not self.allPatientsClassified:
                slicer.util.infoDisplay("At the end of the classification, the automatic review will start.", windowTitle="Random Review Mode")
            
            if self.allPatientsClassified:
                self.ui.nextPatientButton.setEnabled(True)
                slicer.util.infoDisplay("✔️ Dataset already classified. Starting automatic review.", windowTitle="Random Review")
                self.startRandomCheck()
            else:
                self.ui.nextPatientButton.setEnabled(False)

        else:
            self.inRandomView = False
            self.randomPatientsList = []
            self.currentRandomPatientIndex = 0
            slicer.mrmlScene.Clear(0)

            self.currentPatientID = ""  
            
            self.updateTable()
            self.ui.nextPatientButton.setEnabled(False)

        self.updateButtonStates()

    def startRandomCheck(self):
        """Select random patients for review and activate random review mode."""
        
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0
        self.inRandomView = True  

        classifiedPatients = self.logic.loadExistingCSV(self.datasetPath)

        if not classifiedPatients:
            slicer.util.errorDisplay("⚠️ No classified patients found!", windowTitle="Error")
            self.ui.checkBox.setChecked(False)
            self.inRandomView = False  
            self.updateButtonStates()  
            return

        try:
            numCasesText = self.ui.casesInput.text  
            if callable(numCasesText):  
                numCasesText = numCasesText()  

            if numCasesText.strip() == "":  # Se è vuoto, imposta 5
                self.numCasesPerClass = 5
            else:
                self.numCasesPerClass = int(numCasesText)  
        except (ValueError, TypeError):
            slicer.util.errorDisplay("⚠️ Invalid number of cases per class! Using default (5)", windowTitle="Error")
            self.numCasesPerClass = 5  
            self.ui.casesInput.setText(str(self.numCasesPerClass))  # Forza il valore effettivo

        patientsByClass = {}  

        for patientID, classLabel in classifiedPatients.items():
            if classLabel is not None:  
                if classLabel not in patientsByClass:
                    patientsByClass[classLabel] = []
                patientsByClass[classLabel].append(patientID)

        self.randomPatientsList = []

       
        for classLabel, patients in patientsByClass.items():
            if patients:  
                numToSelect = min(len(patients), self.numCasesPerClass) 
                selectedPatients = random.sample(patients, numToSelect)  
                self.randomPatientsList.extend(selectedPatients)

        random.shuffle(self.randomPatientsList)

        if not self.randomPatientsList:
            slicer.util.errorDisplay("⚠️ No patients available for review!", windowTitle="Error")
            self.ui.checkBox.setChecked(False)
            self.inRandomView = False  
            self.updateButtonStates()  
            return

        self.updateButtonStates()  
        self.onLoadNextRandomPatient() 

    def onReviewPatientClicked(self):
        """Loads the selected patient for manual review and disables random review."""
        patientID = self.ui.patientDropdown.currentText

        if patientID == "-":
            slicer.util.errorDisplay("⚠️ No patient selected for review!", windowTitle="Error")
            return

        if self.ui.checkBox.isChecked():
            self.ui.checkBox.setChecked(False)

        patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

        if patientFiles:
            slicer.mrmlScene.Clear(0)
            self.updateTable()
            self.loadPatientImages((patientID, patientFiles))
            self.manualReviewMode = True  
            self.disableAllButtons(False)
        else:
            slicer.util.errorDisplay(f"⚠️ No images found for patient {patientID}!", windowTitle="Error")

        self.updateButtonStates()  

    def onLoadNextRandomPatient(self):
        """Load the next random patient for review and update the LCD counters."""
        
        if not self.randomPatientsList:
            slicer.util.errorDisplay("⚠️ No patients selected for review!", windowTitle="Error")
            self.inRandomView = False
            return

        if self.currentRandomPatientIndex < len(self.randomPatientsList):
            patientID = self.randomPatientsList[self.currentRandomPatientIndex]
            patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

            if patientFiles:
                slicer.mrmlScene.Clear(0)
                self.loadPatientImages((patientID, patientFiles))
            else:
                slicer.util.errorDisplay(f"⚠️ No images found for patient {patientID}!", windowTitle="Error")

            self.currentRandomPatientIndex += 1

            if self.currentRandomPatientIndex >= len(self.randomPatientsList):
                slicer.util.infoDisplay("✔️ All selected patients have been reviewed!", windowTitle="Review Complete")
                self.ui.checkBox.setChecked(False)
                self.inRandomView = False
                self.randomPatientsList = []
                self.currentRandomPatientIndex = 0

                self.currentPatientID = ""  
                self.updateTable()

            self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath)
            for classLabel, count in self.classCounters.items():
                if classLabel in self.classLCDs:
                    self.classLCDs[classLabel].display(count)

        self.updateButtonStates()

    def loadNextPatient(self):
        """Loads the next available patient for classification."""
        self.manualReviewMode = False

        nextPatient = self.logic.getNextPatient(self.datasetPath)

        if nextPatient:
            patientID, fileList = nextPatient
            self.currentPatientIndex += 1
            slicer.mrmlScene.Clear(0)
            self.loadPatientImages((patientID, fileList))
            self.disableAllButtons(False)
        else:
            slicer.mrmlScene.Clear(0)
            slicer.util.infoDisplay("✔️ All patients classified!", windowTitle="Classification Complete")

            self.currentPatientID = ""  
            self.updateTable()

    def loadPatientImages(self, patientData):
        """Loads all images of a patient, handling DICOM and other formats."""
        patientID, fileList = patientData
        self.loadedPatients = []
        self.currentPatientID = patientID  

        dicomExtensions = (".dcm", ".DCM")
        otherExtensions = tuple(ext for ext in SUPPORTED_FORMATS if ext.lower() not in dicomExtensions)

        dicomFiles = [f for f in fileList if f.lower().endswith(dicomExtensions)]
        otherFiles = [f for f in fileList if f.lower().endswith(otherExtensions)]

        hasVolume = False
        volumeNode = None  
        segmentationFiles = []
        volumeFiles = []

        try:
            if dicomFiles:
                dicomDir = os.path.dirname(dicomFiles[0])  
                reader = sitk.ImageSeriesReader()
                dicomSeries = reader.GetGDCMSeriesFileNames(dicomDir)  
                reader.SetFileNames(dicomSeries)
                sitkImage = reader.Execute()  

                volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                volumeNode.SetName(f"{patientID}_DICOM") 
                sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                if volumeNode:
                    self.loadedPatients.append(volumeNode)
                    hasVolume = True

            for filePath in otherFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath) 
                    numpyImage = sitk.GetArrayFromImage(sitkImage).astype(np.float32)  

                    numpyImage_uint8 = numpyImage.astype(np.uint8)
                    numpyImage_uint8[numpyImage_uint8 >= 120] = 120  
                    numpyImage_float32 = numpyImage_uint8.astype(np.float32)

                    if np.sum(numpyImage == numpyImage_float32) == np.prod(numpyImage.shape):
                        segmentationFiles.append(filePath)
                    else:
                        volumeFiles.append(filePath)

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Error reading {filePath}: {str(e)}", windowTitle="Error")

            for filePath in volumeFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath)  
                    
                    volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
                    if self.isFlat:
                        volumeNode.SetName(f"{os.path.basename(filePath)}") 
                    elif self.isHierarchical:
                        volumeNode.SetName(f"{patientID}_{os.path.basename(filePath)}") 

                    sitkUtils.PushVolumeToSlicer(sitkImage, volumeNode)

                    if volumeNode:
                        self.loadedPatients.append(volumeNode)
                        hasVolume = True  

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Error loading volume {filePath}: {str(e)}", windowTitle="Error")

            existingSegmentationNode = slicer.mrmlScene.GetFirstNodeByName(f"{patientID}_Segmentation")

            if hasVolume:
                if not existingSegmentationNode:
                    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
                    segmentationNode.SetName(f"{patientID}_Segmentation")
                else:
                    segmentationNode = existingSegmentationNode

            for filePath in segmentationFiles:
                try:
                    sitkImage = sitk.ReadImage(filePath)  
                    sitkLabelMap = sitk.Cast(sitkImage, sitk.sitkUInt8)

                    if hasVolume:
                        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        sitkUtils.PushVolumeToSlicer(sitkLabelMap, labelmapVolumeNode)  

                        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmapVolumeNode, segmentationNode)
                        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)  
                        self.loadedPatients.append(segmentationNode)
                    else:
                        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
                        labelmapVolumeNode.SetName(f"{patientID}_LabelMap")
                        sitkUtils.PushVolumeToSlicer(sitkLabelMap, labelmapVolumeNode)
                        self.loadedPatients.append(labelmapVolumeNode)

                except Exception as e:
                    slicer.util.errorDisplay(f"❌ Error loading segmentation {filePath}: {str(e)}", windowTitle="Error")

        except Exception as e:
            slicer.util.errorDisplay(f"❌ General error loading patient {patientID}: {str(e)}", windowTitle="Error")

        if self.loadedPatients:
            slicer.util.setSliceViewerLayers(background=self.loadedPatients[0])
            slicer.app.processEvents()
            slicer.util.resetSliceViews()
        else:
            slicer.util.errorDisplay(f"❌ Error: No images loaded for {patientID}", windowTitle="Error")
        
        self.updateTable()

    def onClassifyImage(self, classLabel):
        """Classify the current patient, update the CSV, the table, and the LCD counters."""

        if not self.loadedPatients:
            slicer.util.errorDisplay("❌ No patient loaded!", windowTitle="Error")
            return

        if not self.currentPatientID:
            slicer.util.errorDisplay("❌ Error: Unable to determine the patient!", windowTitle="Error")
            return  

        classifiedPatients = self.logic.loadExistingCSV(self.datasetPath)
        oldClass = classifiedPatients.get(self.currentPatientID) 

        if oldClass is not None and oldClass == classLabel and not self.manualReviewMode:
            slicer.util.errorDisplay("⚠️ This patient is already classified as this class!", windowTitle="Error")
            return  

        self.classificationData[self.currentPatientID] = classLabel
        self.logic.saveClassificationData(self.datasetPath, self.classificationData)

        if oldClass is not None and oldClass in self.classLCDs:
            if isinstance(self.classLCDs[oldClass], qt.QLCDNumber):  
                oldCount = self.classLCDs[oldClass].value
                self.classLCDs[oldClass].display(max(0, oldCount - 1))  
            else:  
                self.classLCDs[oldClass] = max(0, self.classLCDs[oldClass] - 1)

        if classLabel in self.classLCDs:
            if isinstance(self.classLCDs[classLabel], qt.QLCDNumber):  
                newCount = self.classLCDs[classLabel].value
                self.classLCDs[classLabel].display(newCount + 1)  
            else:  
                self.classLCDs[classLabel] += 1  

        self.updateTable()
        self.populatePatientDropdown()

        self.allPatientsClassified = None not in self.classificationData.values()

        if self.allPatientsClassified:
            slicer.util.infoDisplay("✔️ All patients classified!", windowTitle="Classification Complete")
            slicer.app.processEvents()

            if self.ui.checkBox.isChecked():
                slicer.util.infoDisplay("✔️ Starting automatic review. Click 'Next' to continue.", windowTitle="Review Mode")
                slicer.app.processEvents() 
                self.startRandomCheck()
            return  
     
        self.updateButtonStates()
        slicer.mrmlScene.Clear(0)
        self.loadNextPatient()
        
    def updateTable(self):
        """Highlight the loaded patient in the scene with an arrow (→) and bold text. If the scene is empty, no patient is highlighted."""
        self.clearTable()

        if not self.classificationData:
            return

        classColors = {
            0: "#FF4C4C",  # Rosso
            1: "#4CAF50",  # Verde
            2: "#FF9800",  # Arancione
            3: "#FFD700",  # Giallo
            4: "#2196F3",  # Blu
            5: "#9C27B0",  # Viola
            6: "#00BCD4",  # Azzurro
            7: "#8BC34A",  # Verde chiaro
            8: "#FF5722",  # Rosso aranciato
            9: "#607D8B"   # Grigio bluastro
        }

        sceneIsEmpty = len(self.loadedPatients) == 0 

        for idx, (patientID, classLabel) in enumerate(self.classificationData.items()):
            self.ui.classificationTable.insertRow(idx)

            # Se la scena è vuota, non mostriamo la freccia e non evidenziamo nulla
            isCurrentPatient = not sceneIsEmpty and hasattr(self, 'currentPatientID') and self.currentPatientID == patientID
            displayID = f"→ {patientID}" if isCurrentPatient else patientID

            patientItem = qt.QTableWidgetItem(displayID)
            classItem = qt.QTableWidgetItem(str(classLabel) if classLabel is not None else "")

            # Sfondo bianco se non classificato, altrimenti colore della classe
            rowColor = classColors.get(classLabel, "white") if classLabel is not None else "white"
            patientItem.setBackground(qt.QColor(rowColor))
            classItem.setBackground(qt.QColor(rowColor))

            # Se la scena è vuota, NON mettiamo grassetto a nessun paziente
            font = qt.QFont()
            font.setBold(isCurrentPatient and not sceneIsEmpty)  
            font.setWeight(qt.QFont.ExtraBold if isCurrentPatient and not sceneIsEmpty else qt.QFont.Normal)

            patientItem.setFont(font)
            classItem.setFont(font)

            self.ui.classificationTable.setItem(idx, 0, patientItem)
            self.ui.classificationTable.setItem(idx, 1, classItem)

        # Se la scena è vuota, rimuoviamo qualsiasi evidenziazione e resettiamo l'ID paziente attuale
        if sceneIsEmpty:
            self.ui.classificationTable.clearSelection()
            self.currentPatientID = ""  

    def clearTable(self):
        """Clears the classification table."""
        self.ui.classificationTable.setRowCount(0)

    def populatePatientDropdown(self):
        """Updates the dropdown menu with classified patients."""
        self.ui.patientDropdown.clear()  
        self.ui.patientDropdown.addItem("-")

        patients = self.logic.loadExistingCSV(self.datasetPath) 
        classifiedPatients = {patientID: classLabel for patientID, classLabel in patients.items() if classLabel is not None}

        if not classifiedPatients:
            return  

        for patientID in sorted(classifiedPatients):
            self.ui.patientDropdown.addItem(patientID)

    def onPatientSelected(self):
        """Load the selected patient from the table for classification."""
        selectedItems = self.ui.classificationTable.selectedItems()
        
        if not selectedItems:
            return
        
        selectedRow = selectedItems[0].row()
        patientID = self.ui.classificationTable.item(selectedRow, 0).text().replace("→ ", "").strip()

        if not patientID or patientID == "-":
            slicer.util.errorDisplay("⚠️ Invalid patient selected!", windowTitle="Error")
            return

        patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)

        if patientFiles:
            slicer.mrmlScene.Clear(0)
            self.loadPatientImages((patientID, patientFiles))
            self.currentPatientID = patientID  
            self.disableAllButtons(False)  
        else:
            slicer.util.errorDisplay(f"⚠️ No images found for patient {patientID}!", windowTitle="Error")


class ClassAnnotationLogic(ScriptedLoadableModuleLogic):
    """Module logic for image classification."""

    def isFlatDataset(self, datasetPath: str) -> bool:
        """Checks if the dataset is flat (all files are in the main folder)."""
        files = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f)) and not f.startswith('.') and f != 'classification_results.csv']
        return any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in files)

    def isHierarchicalDataset(self, datasetPath: str) -> bool:
        """Checks if the dataset is hierarchical (each patient has a folder)."""
        subdirs = [d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d))]
        return any(any(f.endswith(tuple(SUPPORTED_FORMATS)) for f in os.listdir(os.path.join(datasetPath, d))) for d in subdirs)

    def getNextPatient(self, datasetPath: str) -> Optional[Tuple[str, List[str]]]:
        """Returns the next unclassified patient."""

        self.isHierarchical = self.isHierarchicalDataset(datasetPath)
        self.isFlat = self.isFlatDataset(datasetPath)

        classifiedPatients = self.loadExistingCSV(datasetPath)

        unclassifiedPatients = {patientID: classLabel for patientID, classLabel in classifiedPatients.items() if classLabel is None}

        if not unclassifiedPatients:
            return None  

        sortedPatientIDs = sorted(unclassifiedPatients.keys())

        for patientID in sortedPatientIDs:
            if self.isHierarchical:
                patientPath = os.path.join(datasetPath, patientID)
                patientFiles = self.getPatientFiles(patientPath)
            else:
                allFiles = os.listdir(datasetPath)
                patientFiles = [os.path.join(datasetPath, f) for f in allFiles if f.startswith(patientID) and f.endswith(tuple(SUPPORTED_FORMATS))]

            if patientFiles:
                return patientID, patientFiles

        return None  

    def loadExistingPatientsFromCSV(self, csvFilePath: str) -> dict:
        """Loads existing patients from CSV, including unclassified ones."""
        
        existingPatients = {}

        if not os.path.exists(csvFilePath):
            return existingPatients 

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)
                for row in reader:
                    if len(row) == 2:
                        patientID = row[0]
                        classLabel = row[1] if row[1].isdigit() else None  
                        existingPatients[patientID] = int(classLabel) if classLabel is not None else None

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error reading CSV: {str(e)}", windowTitle="Error")

        return existingPatients
        
    def getPatientFiles(self, patientPath: str) -> List[str]:
        """Returns a list of a patient's files, excluding the output folder."""
        if not os.path.exists(patientPath):
            return []

        files = [
            os.path.join(patientPath, f)
            for f in os.listdir(patientPath)
            if f.endswith(tuple(SUPPORTED_FORMATS))
        ]

        return files

    def saveClassificationData(self, datasetPath: str, classificationData: dict):
        """Saves classification data to CSV and organizes files into output folders."""

        outputFolder = os.path.join(datasetPath, "output")
        if not os.path.exists(outputFolder):
            os.makedirs(outputFolder)

        csvFilePath = os.path.join(outputFolder, "classification_results.csv")

        try:
            existingPatients = self.loadExistingPatientsFromCSV(csvFilePath)

            for patientID, classLabel in classificationData.items():
                existingPatients[patientID] = classLabel

            with open(csvFilePath, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Patient ID", "Class"])
                for patientID, classLabel in sorted(existingPatients.items()):  
                    writer.writerow([patientID, classLabel if classLabel is not None else ""])

            isHierarchical = self.isHierarchicalDataset(datasetPath)

            for patientID, classLabel in existingPatients.items():
                if classLabel is not None:
                    classFolder = os.path.join(outputFolder, f"class{classLabel}")
                    if not os.path.exists(classFolder):
                        os.makedirs(classFolder)

                    self.movePatientIfReclassified(outputFolder, patientID, classLabel)

                    patientFolder = os.path.join(classFolder, patientID)
                    if not os.path.exists(patientFolder):
                        os.makedirs(patientFolder)

                    originalFilePaths = self.findOriginalFile(datasetPath, patientID, isHierarchical)
                    for originalFilePath in originalFilePaths:
                        if originalFilePath:
                            fileName = os.path.basename(originalFilePath)
                            destPath = os.path.join(patientFolder, fileName)
                            shutil.copy2(originalFilePath, destPath)

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error saving CSV: {str(e)}", windowTitle="Error")

    def findOriginalFile(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
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
    
    def getLastPatientFromCSV(self, datasetPath: str) -> Optional[str]:
        """Retrieves the last classified patient from the CSV to resume classification."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        if not os.path.exists(csvFilePath):
            return None

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                last_row = None
                for row in reader:
                    if len(row) == 2:
                        last_row = row[0] 
                return last_row
        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error reading CSV: {str(e)}", windowTitle="Error")
            return None
        
    def getPatientFilesForReview(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Finds images for a previously classified patient."""
        patientFiles = []

        if isHierarchical:
            patientPath = os.path.join(datasetPath, patientID)
            if os.path.exists(patientPath):
                patientFiles = [os.path.join(patientPath, f) for f in os.listdir(patientPath) if f.endswith(tuple(SUPPORTED_FORMATS))]
        else:
            for file in os.listdir(datasetPath):
                if file.startswith(patientID) and file.endswith(tuple(SUPPORTED_FORMATS)):
                    patientFiles.append(os.path.join(datasetPath, file))

        return patientFiles

    def loadExistingCSV(self, datasetPath: str) -> dict:
        """Loads already classified patients from CSV and ensures all patients are included."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        classifiedPatients = {}

        if os.path.exists(csvFilePath):
            try:
                with open(csvFilePath, mode='r') as file:
                    reader = csv.reader(file)
                    next(reader)  
                    
                    for row in reader:
                        if len(row) == 2:
                            patientID = row[0]
                            classLabel = row[1] if row[1].isdigit() else None
                            classifiedPatients[patientID] = int(classLabel) if classLabel is not None else None

            except Exception as e:
                slicer.util.errorDisplay(f"❌ Error reading CSV: {str(e)}", windowTitle="Error")

        allPatientIDs = self.getAllPatientIDs(datasetPath)

        for patientID in allPatientIDs:
            if patientID not in classifiedPatients:
                classifiedPatients[patientID] = None  

        return classifiedPatients

    def movePatientIfReclassified(self, outputFolder: str, patientID: str, newClass: str):
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

    def countPatientsPerClassFromCSV(self, datasetPath: str):
        """Count the number of patients for each class from the CSV."""
        csvFilePath = os.path.join(datasetPath, "output", "classification_results.csv")
        classCounts = {}

        if not os.path.exists(csvFilePath):
            return classCounts

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                
                for row in reader:
                    if len(row) == 2 and row[1].isdigit():
                        classLabel = int(row[1])
                        if classLabel not in classCounts:
                            classCounts[classLabel] = 0
                        classCounts[classLabel] += 1

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Errore nella lettura del CSV: {str(e)}", windowTitle="Errore")

        return classCounts
    
    def getAllPatientIDs(self, datasetPath: str) -> List[str]:
        """Retrieves all patient IDs in the dataset, including unclassified ones."""
        patientIDs = set()

        if self.isHierarchicalDataset(datasetPath):
            patientIDs = {d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d)) 
                        and d.lower() != "output" and not d.startswith('.')}

        elif self.isFlatDataset(datasetPath):
            allFiles = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f)) 
                        and f.lower() != "output" and not f.startswith('.') and f != 'classification_results.csv']
            for fileName in allFiles:
                patientID = fileName.split("_")[0]  
                patientIDs.add(patientID)
        
        return sorted(patientIDs)