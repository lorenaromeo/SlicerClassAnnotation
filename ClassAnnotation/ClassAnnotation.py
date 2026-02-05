import os
import csv
import shutil
import SimpleITK as sitk
import sitkUtils
import qt
import json
import slicer
from typing import Tuple
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from typing import List, Dict


SUPPORTED_FORMATS = (
    ".nrrd", ".nii", ".nii.gz", ".dcm", ".DCM", ".mha",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
)
STANDARD_MODE = "standard"
ADVANCED_MODE = "advanced"
SINGLE_LABEL = "single"
MULTI_LABEL = "multi"
OUTPUT_FOLDER = "output"

class ClassAnnotation(ScriptedLoadableModule):
    """Module for classifying medical images using 3D Slicer."""
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Class Annotation"
        self.parent.categories = ["Utilities"]
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
        self.singleClassification = {}   
        self.multiClassification  = {} 
        self.multiClassNames = {}   
        self.featureMeta = {}
        self.datasetPath = ""
        self.outputPath = None
        self.isHierarchical = False
        self.isFlat = False
        self.manualReviewMode = False  
        self.inRandomView = False  
        self.allPatientsClassified = False  
        self.randomPatientsList = []  
        self.currentRandomPatientIndex = 0  
        self.numCasesPerClass = 5 
        self.standardMode = False
        self.advancedMode = False
        self.mode = STANDARD_MODE
        self.blinkTimer = qt.QTimer() 
        self.blinkTimer.timeout.connect(self.toggleBlink)  
        self.blinkState = True  
        self.blinkItem = None 
        self.blinkPatientID = None  
        self.patientImageHashes = []  
        self.fromOverviewSelection = False

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

        if hasattr(self.ui, "singleButton") and hasattr(self.ui, "multiButton") and hasattr(self.ui, "SingleTab"):
            self.classButtons = {} 
            self.ui.singleButton.setCheckable(True)
            self.ui.multiButton.setCheckable(True)

            self.ui.singleButton.clicked.connect(
                lambda: self.setLabelModeFromButtons(SINGLE_LABEL)
            )
            self.ui.multiButton.clicked.connect(
                lambda: self.setLabelModeFromButtons(MULTI_LABEL)
            )

            self.ui.SingleTab.currentChanged.connect(self.onSingleTabChanged)

            self.logic.label_mode = SINGLE_LABEL  
            self.updateSingleMultiButtonsStyle()
            self.syncModeUI()

        self.classButtons = {}
        self.classLCDs = {}
        self.classCounters = {}

        self.ui.loadButton.clicked.connect(lambda: self.setModeAndLoad("standard"))
        self.ui.loadButton_advanced.clicked.connect(lambda: self.setModeAndLoad(ADVANCED_MODE))
        self.ui.loadButton_output.clicked.connect(self.onSelectOutputFolderClicked)
        self.ui.reviewButton.clicked.connect(self.onReviewPatientClicked)
        self.ui.checkBox.toggled.connect(self.onCheckToggled)
        self.ui.nextPatientButton.clicked.connect(self.onLoadNextRandomPatient)
        self.ui.generateClassesButton.clicked.connect(self.generateClassButtons)  
        self.ui.renameButton.clicked.connect(self.renameClassButtons)

        self.ui.casesInput.setText("5")  
        self.ui.casesInput.setPlaceholderText("")  
   
        self.ui.classificationTable.setColumnCount(2)
        self.ui.classificationTable.setHorizontalHeaderLabels(["Patient ID", "Class"])
        self.ui.classificationTable.horizontalHeader().setStretchLastSection(True)
        self.ui.classificationTable.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
        self.ui.classificationTable.itemSelectionChanged.connect(self.onPatientSelected)

        self.ui.addRowButton.clicked.connect(self.addRow)

        self.ui.generateMultiButton.clicked.connect(self.generateMultiLabelClassButtons)

        self.ui.classCountInput.valueChanged.connect(self.onClassCountChanged)

        self.ui.DeleteRow.clicked.connect(self.onDeleteFeatureClicked)

        self.disableAllButtons(True)
        self.updateButtonStates()

    def getActiveClassificationDict(self):
        return self.singleClassification if self.logic.label_mode == SINGLE_LABEL else self.multiClassification
    
    def generateNewFeatureID(self) -> str:
        if not self.featureMeta:
            return "F001"
        nums = [int(fid[1:]) for fid in self.featureMeta.keys()]
        return f"F{max(nums)+1:03d}"

    def addRow(self):
            """Adds a row to the MultiLabel table with a default name and a spinbox for class count."""
            table = self.ui.MultiLabeltable
            row = table.rowCount
            table.insertRow(row)

            default_name = f"Feature {row + 1}"
            name_item = qt.QTableWidgetItem(default_name)
            table.setItem(row, 0, name_item)

            spin_box = qt.QSpinBox()
            spin_box.setMinimum(2)  
            spin_box.setMaximum(10) 
            spin_box.setValue(2)    

            spin_box.setAlignment(qt.Qt.AlignCenter)
            spin_box.setStyleSheet("background-color: white; color: black;")

            table.setCellWidget(row, 1, spin_box)
            spin_box.valueChanged.connect(lambda _=None, r=row: self.onFeatureCountChanged(r))
            self.populateDeleteFeatureDropdown()


    def onFeatureCountChanged(self, row: int):
        table = self.ui.MultiLabeltable
        item = table.item(row, 0)
        if not item:
            return

        feature_name = item.text().strip()
        if not feature_name:
            return

        spin = table.cellWidget(row, 1)
        if not spin:
            return

        min_required = self.getMinClassesForFeature(feature_name)

        current = spin.value if not callable(spin.value) else spin.value()
        if current < min_required:
            slicer.util.warningDisplay(
                f"⚠️ '{feature_name}': Number of classes cannot be lower than {min_required} "
                f"because at least one patient has value {min_required-1}.",
                windowTitle="Invalid Feature Class Count"
            )
            spin.blockSignals(True)
            spin.setValue(min_required)
            spin.blockSignals(False)

        self.populateDeleteFeatureDropdown()


    def configureClassificationTableForMultiLabel(self):
        feature_names = self.getGeneratedFeatureNames()

        headers = ["Patient ID"] + feature_names

        t = self.ui.classificationTable
        t.clear()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)

        t.setEditTriggers(qt.QAbstractItemView.NoEditTriggers)


    def configureClassificationTableForSingleLabel(self):
        t = self.ui.classificationTable
        t.clear()
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(["Patient ID", "Class"])
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)

        t.setEditTriggers(qt.QAbstractItemView.AllEditTriggers)
        t.setSelectionMode(qt.QAbstractItemView.SingleSelection)

    def generateMultiLabelClassButtons(self):
            """Generates the classification UI based on the MultiLabel table configuration."""
            from ClassAnnotationLib.ClassAnnotationUIUtils import getMainColor, getDarkerColor, getLighterColor
            
            table = self.ui.MultiLabeltable
            
            if table.rowCount == 0:
                slicer.util.warningDisplay("Please add at least one feature row before generating.", windowTitle="Empty Table")
                return

            classificationLayout = self.ui.classificationGroupBox.layout()
            if classificationLayout is None:
                classificationLayout = qt.QVBoxLayout()
                self.ui.classificationGroupBox.setLayout(classificationLayout)

            def clearLayout(layout):
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    childLayout = item.layout()
                    if widget:
                        widget.setParent(None)
                        widget.deleteLater()
                    elif childLayout:
                        clearLayout(childLayout)
                        childLayout.setParent(None)
            
            clearLayout(classificationLayout)
            
            self.classButtons.clear()
            self.populateDeleteFeatureDropdown()
            self.multiLabelButtons = {} 

            for row in range(table.rowCount):
                item_name = table.item(row, 0)
                if not item_name or not item_name.text().strip():
                    continue 
                
                feature_name = item_name.text().strip()

                spin_widget = table.cellWidget(row, 1)
                num_classes = spin_widget.value if spin_widget else 2


                row_frame = qt.QFrame()
                row_layout = qt.QHBoxLayout(row_frame)
                row_layout.setContentsMargins(5, 5, 5, 5)
                row_layout.setSpacing(10)

                label = qt.QLabel(f"{feature_name}:")
                label.setStyleSheet("font-weight: bold; font-size: 13px;")
                label.setFixedWidth(150) 
                row_layout.addWidget(label)

                self.multiLabelButtons[feature_name] = {}

                for i in range(num_classes):
                    btn = qt.QPushButton(str(i))
                    btn.setFixedSize(40, 30) 
                    btn.setCheckable(True)
                    labelMap = self.multiClassNames.get(feature_name, {})
                    txt = labelMap.get(str(i), str(i))  
                    btn = qt.QPushButton(txt)   
                    
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: #f0f0f0;
                            border: 1px solid #999;
                            border-radius: 4px;
                            font-weight: bold;
                        }}
                        QPushButton:checked {{
                            background-color: {getMainColor(i)}; 
                            color: white;
                            border: 1px solid #333;
                        }}
                        QPushButton:hover {{
                            background-color: #e0e0e0;
                        }}
                    """)
   
                    btn.clicked.connect(lambda checked, f=feature_name, val=i: self.onMultiLabelClick(f, val))
                    
                    self.multiLabelButtons[feature_name][i] = btn
                    row_layout.addWidget(btn)
                    
                iconPath = self.resourcePath("Icons/pencil.png")

                pencil = qt.QToolButton()
                pencil.setIcon(qt.QIcon(iconPath))
                pencil.setIconSize(qt.QSize(18, 18))

                pencil.setFixedSize(24, 24)
                pencil.setAutoRaise(True)                 # 🔑 niente bordo
                pencil.setToolButtonStyle(qt.Qt.ToolButtonIconOnly)
                pencil.setFocusPolicy(qt.Qt.NoFocus)

                pencil.setStyleSheet("""
                    QToolButton {
                        border: none;
                        padding: 0px;
                    }
                    QToolButton:hover {
                        background-color: rgba(0,0,0,20);
                        border-radius: 4px;
                    }
                """)

                pencil.setToolTip("Rename labels")
                pencil.clicked.connect(
                    lambda _=None, f=feature_name: self.renameMultiFeatureLabels(f)
                )

                row_layout.addWidget(pencil)
                row_layout.setAlignment(pencil, qt.Qt.AlignVCenter)

                row_layout.addStretch()
                
                classificationLayout.addWidget(row_frame)
                
                # Aggiungi una linea separatrice 
                line = qt.QFrame()
                line.setFrameShape(qt.QFrame.HLine)
                line.setFrameShadow(qt.QFrame.Sunken)
                classificationLayout.addWidget(line)
            
            # --- NEXT PATIENT button sotto le feature ---
            # self.nextPatientMultiBtn = qt.QPushButton("Next Patient")
            # self.nextPatientMultiBtn.setFixedHeight(36)
            # self.nextPatientMultiBtn.setStyleSheet("""
            #     QPushButton {
            #         background-color: #2d89ef;
            #         color: white;
            #         font-weight: bold;
            #         border-radius: 6px;
            #         padding: 8px;
            #     }
            #     QPushButton:hover { background-color: #1b5fbd; }
            #     QPushButton:pressed { background-color: #144a93; }
            # """)
            # self.nextPatientMultiBtn.clicked.connect(self.onNextPatientMultiLabelClicked)
            # classificationLayout.addWidget(self.nextPatientMultiBtn)

            self.logic.label_mode = MULTI_LABEL


            self.configureClassificationTableForMultiLabel()

            self.updateTable()
            self.populatePatientDropdown()
            classificationLayout.addStretch(1)

    def onDeleteFeatureClicked(self):
        if self.logic.label_mode != MULTI_LABEL:
            slicer.util.warningDisplay(
                "Delete Feature is available only in Multi-label mode.",
                windowTitle="Wrong mode"
            )
            return

        feature = self.ui.DeleteFeatureDropdown.currentText
        if not feature or feature == "-":
            slicer.util.warningDisplay(
                "Select a feature to delete.",
                windowTitle="No selection"
            )
            return

        if self.logic.isMultiFeatureUsed(self.datasetPath, self.outputPath, feature):
            slicer.util.warningDisplay(
                f"⚠️ Cannot delete '{feature}': at least one patient already has a value.",
                windowTitle="Feature in use"
            )
            return

        table = self.ui.MultiLabeltable
        for r in range(table.rowCount):
            item = table.item(r, 0)
            if item and item.text().strip() == feature:
                table.removeRow(r)
                break

        self.generateMultiLabelClassButtons()

        slicer.util.infoDisplay(
            f"Feature '{feature}' deleted.",
            windowTitle="Deleted"
        )

    def renameMultiFeatureLabels(self, feature_name: str):
        if not hasattr(self, "multiLabelButtons") or feature_name not in self.multiLabelButtons:
            return

        btns = self.multiLabelButtons[feature_name] 

        for val, btn in btns.items():
            current = btn.text if callable(btn.text) else btn.text()
            newName, ok = qt.QInputDialog.getText(
                slicer.util.mainWindow(),
                f"Rename labels – {feature_name}",
                f"New name for class {val}:",
                qt.QLineEdit.Normal,
                current
            )
            if ok and newName.strip():
                btn.setText(newName.strip())
                self.multiClassNames.setdefault(feature_name, {})[str(val)] = newName.strip()

        self.logic.saveMultiLabels(self.datasetPath, self.outputPath, self.multiClassNames)

    def setLabelModeFromButtons(self, label_mode: str):
        if not hasattr(self.ui, "SingleTab"):
            return

        self.logic.label_mode = label_mode

        self.syncTabsWithTopMode()

        self.updateSingleMultiButtonsStyle()
        self.applyLabelModeUI()

        if self.datasetPath:
            self.reloadStateFromCSVs()
            self.configureTableByMode()
            self.updateTable()
            self.populatePatientDropdown()
            self.loadNextPatient()
            self.updateButtonStates()

    # def setLabelModeFromButtons(self, label_mode: str):
    #     if not hasattr(self.ui, "SingleTab"):
    #         return

    #     # set mode
    #     self.logic.label_mode = label_mode

    #     # cambia tab senza triggerare eventi a catena
    #     self.ui.SingleTab.blockSignals(True)
    #     self.ui.SingleTab.setCurrentIndex(0 if label_mode == SINGLE_LABEL else 1)
    #     self.ui.SingleTab.blockSignals(False)

    #     # UI enable/disable
    #     self.updateSingleMultiButtonsStyle()
    #     self.applyLabelModeUI()

    #     # se dataset già caricato: ricarica i dict dal CSV corretto e riparti dal primo non annotato
    #     if self.datasetPath:
    #         self.reloadStateFromCSVs()     
    #         self.configureTableByMode()    
    #         self.updateTable()
    #         self.populatePatientDropdown()
    #         self.loadNextPatient()
    #         self.updateButtonStates()

    def syncModeUI(self):
        """Rende coerenti: label_mode, tab attiva, tab disabilitata."""
        if not hasattr(self.ui, "SingleTab"):
            return

        isSingle = (self.logic.label_mode == SINGLE_LABEL)

        self.ui.SingleTab.blockSignals(True)
        self.ui.SingleTab.setCurrentIndex(0 if isSingle else 1)
        self.ui.SingleTab.setTabEnabled(0, isSingle)
        self.ui.SingleTab.setTabEnabled(1, not isSingle)
        self.ui.SingleTab.blockSignals(False)

        self.updateSingleMultiButtonsStyle()

    def reloadStateFromCSVs(self):
        self.singleClassification, self.classNames = self.logic.loadSingleCSV(self.datasetPath, self.outputPath)
        self.multiClassification, self.multiFeatureNames = self.logic.loadMultiCSV(self.datasetPath, self.outputPath)
    
    def configureTableByMode(self):
        if self.logic.label_mode == SINGLE_LABEL:
            self.configureClassificationTableForSingleLabel()
        else:
            self.configureClassificationTableForMultiLabel()

    def applyLabelModeUI(self):
        isSingle = (self.logic.label_mode == SINGLE_LABEL)

        self.ui.generateClassesButton.setEnabled(isSingle)
        self.ui.classCountInput.setEnabled(isSingle)
        self.ui.renameButton.setEnabled(isSingle)

        self.ui.addRowButton.setEnabled(not isSingle)
        self.ui.generateMultiButton.setEnabled(not isSingle)
        if hasattr(self.ui, "MultiLabeltable"):
            self.ui.MultiLabeltable.setEnabled(not isSingle)

        if isSingle:
            self.generateClassButtons()
            pass
        else:
            self.generateMultiLabelClassButtons()
            pass


    def onSingleTabChanged(self, index: int):
        newMode = SINGLE_LABEL if index == 0 else MULTI_LABEL
        self.setLabelModeFromButtons(newMode)

    def updateSingleMultiButtonsStyle(self):
        isSingle = (self.logic.label_mode == SINGLE_LABEL)

        self.ui.singleButton.blockSignals(True)
        self.ui.multiButton.blockSignals(True)
        self.ui.singleButton.setChecked(isSingle)
        self.ui.multiButton.setChecked(not isSingle)
        self.ui.singleButton.blockSignals(False)
        self.ui.multiButton.blockSignals(False)

        self.ui.singleButton.setStyleSheet("font-weight: bold;" if isSingle else "font-weight: normal;")
        self.ui.multiButton.setStyleSheet("font-weight: normal;" if isSingle else "font-weight: bold;")

    def getGeneratedFeatureNames(self) -> List[str]:
        if hasattr(self, "multiLabelButtons") and isinstance(self.multiLabelButtons, dict) and self.multiLabelButtons:
            return list(self.multiLabelButtons.keys())

        if hasattr(self, "multiFeatureNames") and isinstance(self.multiFeatureNames, list) and self.multiFeatureNames:
            return list(self.multiFeatureNames)

        return []

    def isSingleComplete(self, pid: str) -> bool:
        v = self.singleClassification.get(pid, None)
        return (v is not None) and (v != "") and (v != "DUPLICATE")

    def isMultiComplete(self, pid: str) -> bool:
        required = self.getGeneratedFeatureNames()
        feats = self.multiClassification.get(pid, {})
        if not required:
            return False
        if not isinstance(feats, dict):
            return False
        for f in required:
            if feats.get(f, None) in (None, "", " "):
                return False
        return True
    

    
    def isPatientCompleteCurrentMode(self, pid: str) -> bool:
        if self.logic.label_mode == SINGLE_LABEL:
            return self.isSingleComplete(pid)
        else:
            return self.isMultiComplete(pid)
    
    def isCurrentPatientMultiLabelComplete(self) -> bool:
        pid = getattr(self, "currentPatientID", "")
        if not pid:
            return False

        required_features = self.getGeneratedFeatureNames()
        if not required_features:
            return False  

        feats = self.classificationData.get(pid, {})
        if not isinstance(feats, dict):
            return False

        for f in required_features:
            if f not in feats:
                return False
            v = feats.get(f, None)
            if v is None or str(v).strip() == "":
                return False

        return True

    def onNextPatientMultiLabelClicked(self):
        """Passa al paziente successivo (modalità multi-label)."""
        if getattr(self, "inRandomView", False):
            self.onLoadNextRandomPatient()
            return

        if getattr(self, "manualReviewMode", False):
            self.manualReviewMode = False

        slicer.mrmlScene.Clear(0)
        slicer.app.processEvents()

        self.loadNextPatient()
        self.updateButtonStates()

    def onMultiLabelClick(self, feature_name: str, value: int):
        self.syncLoadedPatientFromViewer()

        if not self.loadedPatients or not getattr(self, "currentPatientID", ""):
            slicer.util.errorDisplay(
                f"❌ Unable to classify: no patient ID/volume detected.\n"
                f"loadedPatients={len(self.loadedPatients)}  currentPatientID='{getattr(self, 'currentPatientID', '')}'",
                windowTitle="Classification Error"
            )
            return

        self.logic.label_mode = MULTI_LABEL
        pid = self.currentPatientID

        if pid not in self.multiClassification or not isinstance(self.multiClassification.get(pid), dict):
            self.multiClassification[pid] = {}

        self.multiClassification[pid][feature_name] = value

        if hasattr(self, "multiLabelButtons") and feature_name in self.multiLabelButtons:
            for v, b in self.multiLabelButtons[feature_name].items():
                b.blockSignals(True)
                b.setChecked(v == value)
                b.blockSignals(False)

        self.updateTable()
        self.populatePatientDropdown()

        feature_names = self.getGeneratedFeatureNames()
        self.logic.saveMultiCSV(self.datasetPath, self.outputPath, self.multiClassification, feature_names)

        if self.isMultiComplete(pid):
            slicer.mrmlScene.Clear(0)
            slicer.app.processEvents()
            self.loadNextPatient()
            self.updateButtonStates()

    def generateClassButtons(self):
            """Remove all existing elements and regenerate the classification buttons for Single-Label."""
            from ClassAnnotationLib.ClassAnnotationUIUtils import getMainColor, getDarkerColor, getLighterColor
            
            # --- RESET TABLE TO SINGLE-LABEL STRUCTURE ---
            t = self.ui.classificationTable
            t.clear()
            t.setColumnCount(2)
            t.setHorizontalHeaderLabels(["Patient ID", "Class"])
            t.horizontalHeader().setSectionResizeMode(qt.QHeaderView.Stretch)
            
            # Set logic mode to single
            self.logic.label_mode = SINGLE_LABEL
            self.updateTable()

            # --- GRAPHICAL BUTTON GENERATION ---
            numClasses = self.ui.classCountInput.value  
            classificationLayout = self.ui.classificationGroupBox.layout()

            if classificationLayout is None:
                classificationLayout = qt.QVBoxLayout()
                self.ui.classificationGroupBox.setLayout(classificationLayout)

            # Clear existing layout
            def clearLayout(layout):
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                    elif item.layout():
                        clearLayout(item.layout())
            clearLayout(classificationLayout)

            self.classButtons.clear()
            self.classLCDs.clear()
            self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)

            gridLayout = qt.QGridLayout()
            gridLayout.setSpacing(5)
            
            headerLabel = qt.QLabel("Current Cases per Class")
            headerLabel.setAlignment(qt.Qt.AlignCenter)
            headerLabel.setStyleSheet("font-size: 12px; font-weight: bold;")
            gridLayout.addWidget(headerLabel, 0, 1)

            _, classNamesFromCSV = self.logic.loadExistingCSV(self.datasetPath, self.outputPath)

            for classLabel in range(numClasses):
                row = classLabel + 1  
                defaultName = f"Class {classLabel}"
                customName = classNamesFromCSV.get(classLabel, defaultName)
                button = qt.QPushButton(customName)

                # button = qt.QPushButton(f"Class {classLabel}")
                button.setStyleSheet(f"""
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                                stop:0 {getLighterColor(classLabel)}, 
                                stop:0.5 {getMainColor(classLabel)}, 
                                stop:1 {getDarkerColor(classLabel)});
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

    def clearMultiButtonsSelection(self):
        """Deseleziona TUTTI i bottoni della UI multi-label."""
        if not hasattr(self, "multiLabelButtons") or not isinstance(self.multiLabelButtons, dict):
            return
        for feature, btns in self.multiLabelButtons.items():
            for v, b in btns.items():
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)

    def applyMultiButtonsFromPatient(self, pid: str):
        """Se il paziente ha già valori in multiClassification, riseleziona i bottoni corretti."""
        if not pid:
            return
        if not hasattr(self, "multiLabelButtons") or not isinstance(self.multiLabelButtons, dict):
            return

        feats = self.multiClassification.get(pid, {})
        if not isinstance(feats, dict):
            feats = {}

        for feature, btns in self.multiLabelButtons.items():
            raw = feats.get(feature, None)
            if raw is None or str(raw).strip() == "":
                continue

            try:
                val = int(raw)
            except Exception:
                continue

            if val in btns:
                for v, b in btns.items():
                    b.blockSignals(True)
                    b.setChecked(v == val)
                    b.blockSignals(False)
                

    def renameClassButtons(self):
        """Open a dialog to rename class buttons with scroll layout and styled input fields."""
        dialog = qt.QDialog()
        dialog.setWindowTitle("Rename Class Buttons")
        dialog.setModal(True)
        dialog.setFixedSize(300, 250)

        mainLayout = qt.QVBoxLayout()
        mainLayout.setContentsMargins(10, 10, 10, 10)
        dialog.setLayout(mainLayout)

        scrollArea = qt.QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollWidget = qt.QWidget()
        scrollLayout = qt.QVBoxLayout(scrollWidget)
        scrollArea.setWidget(scrollWidget)
        mainLayout.addWidget(scrollArea)

        renameInputs = {}

        for classLabel, button in self.classButtons.items():
            if not isinstance(button, qt.QPushButton):
                continue

            classRow = qt.QHBoxLayout()

            label = qt.QLabel(f"Class {classLabel}:")
            label.setFixedWidth(100)
            label.setStyleSheet("font-size: 12px; font-weight: bold;")

            inputField = qt.QLineEdit()
            
            try:
                placeholder = button.text()  
            except TypeError:
                placeholder = button.text  

            inputField.setPlaceholderText(placeholder)
            renameInputs[classLabel] = inputField

            classRow.addWidget(label)
            classRow.addWidget(inputField)
            scrollLayout.addLayout(classRow)

        scrollLayout.addStretch(1)

        # Apply & Cancel buttons
        buttonLayout = qt.QHBoxLayout()

        applyButton = qt.QPushButton("Apply")
        applyButton.setStyleSheet(
            "background-color: #4CAF50; color: black; font-weight: bold; padding: 8px; border-radius: 6px;"
        )
        applyButton.clicked.connect(lambda: self.applyRenaming(renameInputs, dialog))

        cancelButton = qt.QPushButton("Cancel")
        cancelButton.setStyleSheet(
            "background-color: #D32F2F; color: black; font-weight: bold; padding: 8px; border-radius: 6px;"
        )
        cancelButton.clicked.connect(dialog.reject)

        buttonLayout.addWidget(cancelButton)
        buttonLayout.addWidget(applyButton)
        mainLayout.addLayout(buttonLayout)

        dialog.exec()


    def applyRenaming(self, renameInputs, dialog):
        """Apply the new labels to the buttons only if the fields are not empty."""
        renamed = False

        for classLabel, inputField in renameInputs.items():
            try:
                newName = inputField.text().strip()
            except TypeError:
                newName = inputField.text.strip()  

            if newName:
                button = self.classButtons[classLabel]
                try:
                    currentName = button.text().strip()
                except TypeError:
                    currentName = button.text.strip()

                if newName != currentName:
                    button.setText(newName)
                    renamed = True

        dialog.accept()

        if renamed:
            self.updateTable()
            self.logic.saveClassificationData(self.datasetPath, self.classificationData, self.outputPath)
            slicer.util.infoDisplay("Class names updated and saved!", windowTitle="Update Successful")
        else:
            slicer.util.infoDisplay("No changes applied.", windowTitle="No Update")
    

    def updateLCDCounters(self):
        """Update the LCD counters with the number of classified cases for each class."""
        
        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)

        for classLabel, count in self.classCounters.items():
            if classLabel not in self.classLCDs:
            
                lcdCounter = qt.QLCDNumber()
                lcdCounter.setDigitCount(2)
                lcdCounter.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Fixed)
                lcdCounter.setMinimumHeight(30)
                self.classLCDs[classLabel] = lcdCounter
                self.ui.classificationGroupBox.layout().addWidget(lcdCounter) 

            self.classLCDs[classLabel].display(count)
    
    def onClassCountChanged(self):
        """Check if the number of classes is lower than the highest existing class and generate a warning."""
        
        minRequiredClasses = 2  

        existingClasses = [c for c in self.classificationData.values() if c is not None]

        if existingClasses: 
            maxClass = max(existingClasses)
            minRequiredClasses = max(maxClass + 1, 2)  

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
        self.ui.generateClassesButton.setEnabled(not disable)
        self.ui.classCountInput.setEnabled(not disable)
        self.ui.renameButton.setEnabled(not disable)
        self.ui.addRowButton.setEnabled(not disable)
        self.ui.renameButton.setEnabled(not disable)
        self.ui.generateMultiButton.setEnabled(not disable)
        self.ui.DeleteFeatureDropdown.setEnabled(not disable)
        self.ui.DeleteRow.setEnabled(not disable)


    def disableClassificationButtons(self, disable: bool):
        """Enable or disable only classification buttons."""
        for button in self.classButtons.values():
            button.setEnabled(not disable)

    def disableSingleLabelMode(self, disable: bool):
        """Disable only SingleLabel buttons."""
        self.ui.generateClassesButton.setEnabled(not disable)
        self.ui.classCountInput.setEnabled(not disable)
        self.ui.renameButton.setEnabled(not disable)


    def resetModuleState(self):
        self.classificationData.clear()
        self.classButtons.clear()
        self.classLCDs.clear()
        self.classCounters.clear()
        self.loadedPatients.clear()
        self.currentPatientIndex = 0
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0
        self.allPatientsClassified = False
        self.manualReviewMode = False
        self.inRandomView = False
        self.currentPatientID = ""
        self.patientHashesFromCSV = {}

        self.ui.classificationTable.setRowCount(0)
        self.ui.patientDropdown.clear()
        self.ui.patientDropdown.addItem("-")

        self.ui.labelInputPath.setText("Input Path: ")
        self.ui.labelOutputPath.setText("Output Path: ")
        self.ui.labelInputPath_advanced.setText("Input Path: ")
        self.ui.labelOutputPath_advanced.setText("Output Path: ")


    def updateButtonStates(self):
        datasetLoaded = bool(self.datasetPath)

        if not datasetLoaded:
            self.allPatientsClassified = False
            self.disableAllButtons(True)
            if hasattr(self.ui, "nextPatientButton"):
                self.ui.nextPatientButton.setEnabled(False)
            return
        
        allIDs = self.logic.getAllPatientIDs(self.datasetPath)
        self.allPatientsClassified = (len(allIDs) > 0) and all(self.isPatientCompleteCurrentMode(pid) for pid in allIDs)

        self.disableAllButtons(False)
        self.disableClassificationButtons(self.inRandomView)
        self.ui.reviewButton.setEnabled(not self.inRandomView)

        enableNextRandom = self.allPatientsClassified and self.ui.checkBox.isChecked()
        self.ui.nextPatientButton.setEnabled(enableNextRandom)

        if self.manualReviewMode:
            self.ui.checkBox.setChecked(False)


    def onSelectOutputFolderClicked(self):
        """Allows the user to select an output folder and update the UI."""
        outputPath = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), "Select Output Folder")

        if not outputPath:
            slicer.util.errorDisplay("⚠️ You must select an output folder to proceed!", windowTitle="Error")
            return

        self.outputPath = outputPath
        # if self.mode == ADVANCED_MODE:
        #     self.ui.labelOutputPath_advanced.setText(f"Output Path: {self.outputPath}")

        # else:
        #     self.ui.labelOutputPath.setText(f"Output Path: {self.outputPath}")

        # if self.datasetPath:
        #     self.loadDataset()
        
        # self.updateButtonStates()

        self.ui.labelOutputPath_advanced.setText(f"Output Path: {self.outputPath}")

      
        if self.datasetPath and self.mode == ADVANCED_MODE:
            self.loadDataset()

        self.updateButtonStates()
        
    def setModeAndLoad(self, mode: str):
        self.mode = mode  
        self.logic.mode = mode  
        self.onLoadDatasetClicked(mode)  

    def setModeSingleOrMulti(self, mode: str):
        self.mode = mode  
        self.logic.mode = mode  
        self.onLoadDatasetClicked(mode)  


    def syncTabsWithTopMode(self):
        """Se Single è attivo: mostra tab 0 e disabilita tab 1. Viceversa per Multi."""
        if not hasattr(self.ui, "SingleTab"):
            return

        isSingle = (self.logic.label_mode == SINGLE_LABEL)

        self.ui.SingleTab.blockSignals(True)

        self.ui.SingleTab.setCurrentIndex(0 if isSingle else 1)

        self.ui.SingleTab.setTabEnabled(0, isSingle)
        self.ui.SingleTab.setTabEnabled(1, not isSingle)

        self.ui.SingleTab.blockSignals(False)


    def syncLoadedPatientFromViewer(self):
        """
        Prova a recuperare un nodo visualizzabile dalla scena (volume o labelmap),
        e ricava currentPatientID dal nome.
        """
        self.loadedPatients = []
        node = None

        lm = slicer.app.layoutManager()
        if lm:
            for sliceName in ("Red", "Yellow", "Green"):
                try:
                    sw = lm.sliceWidget(sliceName)
                    if not sw:
                        continue
                    bg = sw.sliceLogic().GetBackgroundLayer().GetVolumeNode()
                    if bg:
                        node = bg
                        break
                except Exception:
                    pass

        if node is None:
            vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
            if vols:
                node = vols[0]

        if node is None:
            labs = slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")
            if labs:
                node = labs[0]

        if node:
            self.loadedPatients = [node]

            if not getattr(self, "currentPatientID", ""):
                try:
                    from ClassAnnotationLib.ClassAnnotationUtils import extract_patient_id_from_name
                    self.currentPatientID = extract_patient_id_from_name(node.GetName())
                except Exception:
                    name = node.GetName() if hasattr(node, "GetName") else ""
                    self.currentPatientID = name.split("_")[0] if name else ""


    def loadDataset(self):
        if not self.datasetPath:
            slicer.util.errorDisplay("⚠️ No dataset selected!", windowTitle="Error")
            return

        self.isFlat = self.logic.isFlatDataset(self.datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("⚠️ Dataset contains both files and folders. Use a single format!", windowTitle="Error")
            return

        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)
        if not allPatientIDs:
            slicer.util.errorDisplay("⚠️ No patients found in the dataset!", windowTitle="Error")
            return

        self.reloadStateFromCSVs()
        self.multiClassNames = self.logic.loadMultiLabels(self.datasetPath, self.outputPath)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)

        if self.logic.label_mode == SINGLE_LABEL:
            self.generateClassButtons()

        self.syncModeUI()
        self.configureTableByMode()
        self.loadNextPatient()
        self.syncLoadedPatientFromViewer()

        self.updateTable()
        self.populatePatientDropdown()

        self.updateButtonStates()


    def onLoadDatasetClicked(self, mode: str):  
        """Load the dataset, update the table, and correctly set the default number of classes."""
        from ClassAnnotationLib.ClassAnnotationUIUtils import showDatasetStructureWarning
        
        showDatasetStructureWarning()

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
        
        self.resetModuleState()


        slicer.mrmlScene.Clear(0)
        slicer.app.processEvents()
        self.updateTable()
        self.currentPatientID = ""  

        datasetPath = qt.QFileDialog.getExistingDirectory(slicer.util.mainWindow(), "Select Dataset Folder")
        if not datasetPath:
            slicer.util.errorDisplay("⚠️ No dataset selected!", windowTitle="Error")
            return

        self.datasetPath = datasetPath
        self.ui.labelInputPath_advanced.setText(f"Input Path: {self.datasetPath}")
        # self.ui.labelInputPath.setText(f"Input Path: {self.datasetPath}")

        # shouldLoad = True
        # if self.mode == ADVANCED_MODE:
        #     if not self.outputPath:
        #         slicer.util.infoDisplay("Please select the output folder.", windowTitle="Select Output")
        #         shouldLoad = False

        # if shouldLoad:
        #     self.loadDataset()

        if self.mode == ADVANCED_MODE:
            if not self.outputPath:
                slicer.util.infoDisplay("Please select the output folder.", windowTitle="Select Output")
                return  
            
        self.loadDataset() 
        #     else:
        #         self.loadDataset()  
        # else:
        #     self.loadDataset()

        # if self.datasetPath and self.outputPath:
        #     self.loadDataset()

        # self.loadedPatients.clear()
        # self.currentPatientIndex = 0
        # self.classificationData.clear()
        # self.clearTable()
        self.loadedPatients.clear()
        self.currentPatientIndex = 0
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0

        self.isFlat = self.logic.isFlatDataset(self.datasetPath)
        self.isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)

        if self.isFlat and self.isHierarchical:
            slicer.util.errorDisplay("⚠️ Dataset contains both folders and files. Use a single format!", windowTitle="Error")
            self.disableAllButtons(True)
            return

        self.reloadStateFromCSVs()

        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)
        self.allPatientsClassified = (len(allPatientIDs) > 0) and all(
            self.isPatientCompleteCurrentMode(pid) for pid in allPatientIDs
        )

        if self.allPatientsClassified:
            slicer.util.infoDisplay("✔️ The dataset is fully classified.", windowTitle="Dataset Fully Classified")

        self.updateTable()

        maxClass = 4 
        if self.classificationData:
            existingClasses = [int(c) for c in self.classificationData.values() if c is not None and str(c).isdigit()]
            # existingClasses = [c for c in self.classificationData.values() if c is not None]
            if existingClasses:
                maxClass = max(existingClasses)


        defaultNumClasses = max(5, maxClass + 1)  
        self.ui.classCountInput.setValue(defaultNumClasses)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)

        self.generateClassButtons()

        csvFilePath = os.path.join(
            self.outputPath if self.mode == ADVANCED_MODE else self.datasetPath,
            OUTPUT_FOLDER,
            "classification_results.csv"
        )

        customClassNames = {}

        if os.path.exists(csvFilePath):
            with open(csvFilePath, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    classStr = row.get("Class", "").strip()
                    nameStr = row.get("Class Name", "").strip()
                    if classStr and nameStr and classStr.isdigit():
                        classID = int(classStr)
                        if nameStr.lower() != f"class{classID}".lower():
                            customClassNames[classID] = nameStr

        for classID, newName in customClassNames.items():
            if classID in self.classButtons:
                self.classButtons[classID].setText(newName)

        for classLabel, count in self.classCounters.items():
            if classLabel in self.classLCDs:
                self.classLCDs[classLabel].display(count)

        self.populatePatientDropdown()

        # allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)  

        # if not allPatientIDs:
        #     slicer.util.errorDisplay("⚠️ No patients found in the dataset!", windowTitle="Error")
        #     return  

        # if self.allPatientsClassified:
        #     firstPatientID = allPatientIDs[0]
        # else:
        #     for patientID in allPatientIDs:
        #         if self.classificationData.get(patientID) is None:  
        #             firstPatientID = patientID
        #             break
        #     else:
        #         firstPatientID = allPatientIDs[0]  

        # firstPatientFiles = self.logic.getPatientFilesForReview(self.datasetPath, firstPatientID, self.isHierarchical)

        # if firstPatientFiles:
        #     print(firstPatientFiles)
        #     self.currentPatientID = firstPatientID

        #     self.patientHashesFromCSV = self.logic.loadHashesFromCSV(self.datasetPath, self.outputPath)

        #     self.loadNextPatient()
        #     self.disableAllButtons(False)
        # else:
        #     slicer.util.errorDisplay(f"⚠️ No images found for patient {firstPatientID}!", windowTitle="Error")

        if self.mode == ADVANCED_MODE:
            self.ui.labelInputPath_advanced.setText(f"Input Path: {self.datasetPath}")
            finalOutputFolder = os.path.join(self.outputPath, OUTPUT_FOLDER)  
            self.ui.labelOutputPath_advanced.setText(f"Output Path: {finalOutputFolder}")

            self.ui.labelInputPath.setText("Input Path: ")
            self.ui.labelOutputPath.setText("Output Path: ")

        else:
            self.ui.labelInputPath.setText(f"Input Path: {self.datasetPath}")
            outputFolder = os.path.join(self.datasetPath, OUTPUT_FOLDER)  
            self.ui.labelOutputPath.setText(f"Output Path: {outputFolder}")

            self.ui.labelInputPath_advanced.setText("Input Path: ")
            self.ui.labelOutputPath_advanced.setText("Output Path: ")

        self.updateButtonStates()
            
            
            
    def onCheckToggled(self, checked: bool) -> None:
        """Activates or deactivates random review and manages button states."""

        if checked:
            self.manualReviewMode = False
            self.ui.reviewButton.setEnabled(False)
            self.ui.checkBox.setChecked(True)
            self.ui.classificationTable.setEditTriggers(qt.QAbstractItemView.NoEditTriggers) 
            self.ui.classificationTable.setSelectionMode(qt.QAbstractItemView.NoSelection) 

            for row in range(self.ui.classificationTable.rowCount):
                for col in range(self.ui.classificationTable.columnCount):
                    item = self.ui.classificationTable.item(row, col)
                    if item:
                        item.setForeground(qt.QBrush(qt.QColor("black")))  

            self.reloadStateFromCSVs()

            allIDs = self.logic.getAllPatientIDs(self.datasetPath)
            self.allPatientsClassified = (len(allIDs) > 0) and all(
                self.isPatientCompleteCurrentMode(pid) for pid in allIDs
            )

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
            self.ui.classificationTable.setEditTriggers(qt.QAbstractItemView.AllEditTriggers)
            self.ui.classificationTable.setSelectionMode(qt.QAbstractItemView.SingleSelection)
            self.updateTable()
            self.ui.nextPatientButton.setEnabled(False)

        self.updateButtonStates()



    def startRandomCheck(self):
        import random

        """Select random patients for review and activate random review mode."""
        
        self.randomPatientsList = []
        self.currentRandomPatientIndex = 0
        self.inRandomView = True  

        classifiedPatients, self.classNames = self.logic.loadExistingCSV(self.datasetPath, self.outputPath)

        if not classifiedPatients:
            slicer.util.errorDisplay("⚠️ No classified patients found!", windowTitle="Error")
            self.ui.checkBox.setChecked(False)
            self.inRandomView = False 
            self.ui.classificationTable.setEnabled(True) 
            self.updateButtonStates()  
            return

        try:
            numCasesText = self.ui.casesInput.text  
            if callable(numCasesText):  
                numCasesText = numCasesText()  

            if numCasesText.strip() == "":  
                self.numCasesPerClass = 5
            else:
                self.numCasesPerClass = int(numCasesText)  
        except (ValueError, TypeError):
            slicer.util.errorDisplay("⚠️ Invalid number of cases per class! Using default (5)", windowTitle="Error")
            self.numCasesPerClass = 5  
            self.ui.casesInput.setText(str(self.numCasesPerClass))  

        patientsByClass = {}  

        for patientID, classLabel in classifiedPatients.items():
            if classLabel is not None and classLabel != "DUPLICATE":
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
            self.manualReviewMode = True  
            slicer.mrmlScene.Clear(0)
            self.updateTable()
            self.loadPatientImages((patientID, patientFiles))
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

            self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)
            for classLabel, count in self.classCounters.items():
                if classLabel in self.classLCDs:
                    self.classLCDs[classLabel].display(count)

        self.updateButtonStates()


    def loadNextPatient(self):
        if not self.datasetPath:
            return

        allIDs = self.logic.getAllPatientIDs(self.datasetPath)

        if self.logic.label_mode == MULTI_LABEL:
            unclassified = [pid for pid in allIDs if not self.isMultiComplete(pid)]
        else:
            unclassified = [pid for pid in allIDs if not self.isSingleComplete(pid)]

        for patientID in unclassified:
            patientFiles = self.logic.getPatientFilesForReview(
                self.datasetPath, patientID, self.isHierarchical
            )
            if not patientFiles:
                continue

            if self.logic.label_mode == SINGLE_LABEL:
                try:
                    from ClassAnnotationLib.ClassAnnotationUtils import compute_patient_hashes, findOriginalFile

                    originalPaths = findOriginalFile(self.datasetPath, patientID, self.isHierarchical)
                    hashSet = set(compute_patient_hashes(originalPaths))
                    currentHashString = "|".join(sorted(hashSet))

                    self.patientHashesFromCSV = self.logic.loadHashesFromCSV(self.datasetPath, self.outputPath)

                    isDup, originalID = self.isPatientDuplicate(patientID, currentHashString)
                    if isDup:
                        self.markAsDuplicate(patientID, originalID)
                        continue
                except Exception as e:
                    print(f"[WARNING] Duplicate/hash check failed for {patientID}: {e}")

            if self.loadPatientImages((patientID, patientFiles)):
                self.currentPatientID = patientID

                self.disableAllButtons(False)
                self.disableClassificationButtons(False)

                return

            self.currentPatientID = ""

        slicer.mrmlScene.Clear(0)
        slicer.app.processEvents()

        slicer.util.infoDisplay("✔️ All patients classified!", windowTitle="Classification Complete")
        self.currentPatientID = ""
        self.updateTable()

        self.disableClassificationButtons(True)

        self.updateButtonStates()


    def isPatientDuplicate(self, patientID, currentHashString):
        for existingID, existingHashStr in self.patientHashesFromCSV.items():
            if not existingHashStr.strip():
                continue
            if currentHashString == existingHashStr.strip():
                return True, existingID
        return False, None
    
    def markAsDuplicate(self, patientID, duplicateOfID):
        slicer.util.warningDisplay(
            f"⚠️ Patient {patientID} is a duplicate of {duplicateOfID}. It will be skipped.",
            windowTitle="Duplicate Detected"
        )
        self.classificationData[patientID] = "DUPLICATE"
        self.logic.saveClassificationData(self.datasetPath, self.classificationData, self.outputPath)
        self.updateTable()
        self.currentPatientID = ""

    def tryLoadPatient(self, patientID, fileList):
        from ClassAnnotationLib.ClassAnnotationUtils import compute_patient_hashes, findOriginalFile

        self.patientHashesFromCSV = self.logic.loadHashesFromCSV(self.datasetPath, self.outputPath)
        try:
            slicer.mrmlScene.Clear(0)
            self.clearPreviousPatientNodes()

            success = self.loadPatientImages((patientID, fileList))
            if not success:
                self.currentPatientID = ""
                slicer.util.errorDisplay(f"❌ Error loading patient {patientID}: No images found", windowTitle="Load Error")
                return

            self.currentPatientID = patientID

            # hash
            isHierarchical = self.logic.isHierarchicalDataset(self.datasetPath)
            originalFilePaths = findOriginalFile(self.datasetPath, patientID, isHierarchical)
            hashSet = set(compute_patient_hashes(originalFilePaths))
            currentHashStr = "|".join(sorted(hashSet))

            self.patientHashesFromCSV = self.logic.loadHashesFromCSV(self.datasetPath, self.outputPath)

            for existingID, existingHashStr in self.patientHashesFromCSV.items():
                if existingID == patientID or not existingHashStr.strip():
                    continue

                existingHashSet = set(existingHashStr.strip().lower().split('|'))
                if set(h.lower() for h in hashSet) == existingHashSet:
        
                    slicer.util.warningDisplay(
                        f"⚠️ Patient {patientID} is a duplicate of {existingID}. It will be skipped.",
                        windowTitle="Duplicate Detected"
                    )

                    self.classificationData[patientID] = "DUPLICATE"
                    self.logic.saveClassificationData(self.datasetPath, self.classificationData, self.outputPath)
                    self.updateTable()

                    slicer.app.processEvents()
                    slicer.mrmlScene.Clear(0)
                    self.clearPreviousPatientNodes()
                    self.currentPatientID = ""

                    if not (self.manualReviewMode or self.inRandomView or self.fromOverviewSelection):
                        self.loadNextPatient()
                    return

            self.updateTable()
            slicer.app.processEvents()

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Failed to load patient {patientID}: {str(e)}", windowTitle="Error")

    def clearPreviousPatientNodes(self):
        for node in getattr(self, "loadedPatients", []):
            slicer.mrmlScene.RemoveNode(node)
        self.loadedPatients = []

    def loadPatientImages(self, patientData):
        import numpy as np
        import SimpleITK as sitk
        import sitkUtils

        patientID, fileList = patientData
        self.loadedPatients = []
        # self.currentPatientID = patientID

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
            self.currentPatientID = patientID

            if self.logic.label_mode == MULTI_LABEL:
                self.clearMultiButtonsSelection()
                self.applyMultiButtonsFromPatient(patientID)
        else:
            self.currentPatientID=''
            slicer.util.errorDisplay(f"❌ Error: No images loaded for {patientID}", windowTitle="Error")

        self.updateTable()

        loadedNodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        if self.loadedPatients:
            return True
        else:
            return False

    def onClassifyImage(self, classLabel):
        self.syncLoadedPatientFromViewer()

        if not self.loadedPatients or not getattr(self, "currentPatientID", ""):
            slicer.util.errorDisplay(
                f"❌ Unable to classify: no patient ID/volume detected.\n"
                f"loadedPatients={len(self.loadedPatients)}  currentPatientID='{getattr(self, 'currentPatientID', '')}'",
                windowTitle="Classification Error"
            )
            return

        self.logic.label_mode = SINGLE_LABEL
        pid = self.currentPatientID

        oldClass = self.singleClassification.get(pid, None)
        if oldClass is not None and oldClass == classLabel and not self.manualReviewMode:
            slicer.util.errorDisplay("⚠️ This patient is already classified as this class!", windowTitle="Error")
            return

        self.singleClassification[pid] = classLabel
        self.disableClassificationButtons(True)

        self.logic.saveSingleCSV(self.datasetPath, self.outputPath, self.singleClassification)

        self.classCounters = self.logic.countPatientsPerClassFromCSV(self.datasetPath, self.outputPath)
        for lbl, lcd in self.classLCDs.items():
            lcd.display(self.classCounters.get(lbl, 0))

        self.updateTable()
        self.populatePatientDropdown()

        self.updateButtonStates()

        slicer.mrmlScene.Clear(0)
        slicer.app.processEvents()

        self.loadNextPatient()

        self.disableClassificationButtons(False)

            
    def updateTable(self):
        from ClassAnnotationLib.ClassAnnotationUIUtils import classColors

        self.clearTable()
        if not self.datasetPath:
            return

        t = self.ui.classificationTable
        allPatientIDs = self.logic.getAllPatientIDs(self.datasetPath)

        sceneIsEmpty = (
            len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")) == 0
            and len(slicer.util.getNodesByClass("vtkMRMLLabelMapVolumeNode")) == 0
            and len(slicer.util.getNodesByClass("vtkMRMLSegmentationNode")) == 0
        )
        self.blinkItem = None
        self.blinkPatientID = None

        # -------- MULTI-LABEL TABLE --------
        if self.logic.label_mode == MULTI_LABEL:
            feature_names = self.getGeneratedFeatureNames()

            expected_cols = 1 + len(feature_names)
            if t.columnCount != expected_cols:
                self.configureClassificationTableForMultiLabel()

            for row, pid in enumerate(allPatientIDs):
                t.insertRow(row)

                isCurrent = (not sceneIsEmpty and getattr(self, "currentPatientID", "") == pid)
                displayID = f"→ {pid}" if isCurrent else pid

                pidItem = qt.QTableWidgetItem(displayID)
                pidItem.setForeground(qt.QBrush(qt.QColor("black")))
                t.setItem(row, 0, pidItem)
                
                font = qt.QFont()
                font.setBold(isCurrent and not sceneIsEmpty)
                pidItem.setFont(font)

                feats = self.multiClassification.get(pid, {})
                if not isinstance(feats, dict):
                    feats = {}

                for j, f in enumerate(feature_names):
                    val = feats.get(f, "")
                    item = qt.QTableWidgetItem("" if val is None else str(val))
                    item.setForeground(qt.QBrush(qt.QColor("black")))
                    t.setItem(row, 1 + j, item)

                if isCurrent:
                    self.blinkItem = pidItem
                    self.blinkPatientID = pid

            if self.blinkItem:
                self.blinkTimer.start(300)
            else:
                self.blinkTimer.stop()
            return

        # -------- SINGLE-LABEL TABLE --------
        if t.columnCount != 2:
            self.configureClassificationTableForSingleLabel()

        row = 0
        for pid in allPatientIDs:
            t.insertRow(row)

            classLabel = self.singleClassification.get(pid, None)
            if isinstance(classLabel, dict):
                classLabel = None

            isCurrent = (not sceneIsEmpty and getattr(self, "currentPatientID", "") == pid)
            displayID = f"→ {pid}" if isCurrent else pid

            patientItem = qt.QTableWidgetItem(displayID)

            className = ""
            if classLabel is not None and classLabel != "DUPLICATE":
                btn = self.classButtons.get(classLabel)
                defaultName = f"Class {classLabel}"
                if btn:
                    actualName = btn.text.strip()
                    className = actualName if actualName != defaultName else str(classLabel)
                else:
                    className = str(classLabel)
            elif classLabel == "DUPLICATE":
                className = "DUPLICATE"

            classItem = qt.QTableWidgetItem(className)

            rowColor = classColors.get(classLabel, "white") if classLabel not in (None, "DUPLICATE") else "white"
            patientItem.setBackground(qt.QColor(rowColor))
            classItem.setBackground(qt.QColor(rowColor))
            patientItem.setForeground(qt.QBrush(qt.QColor("black")))
            classItem.setForeground(qt.QBrush(qt.QColor("black")))

            font = qt.QFont()
            font.setBold(isCurrent and not sceneIsEmpty)
            patientItem.setFont(font)
            classItem.setFont(font)

            t.setItem(row, 0, patientItem)
            t.setItem(row, 1, classItem)

            if isCurrent:
                self.blinkItem = patientItem
                self.blinkPatientID = pid

            row += 1

        if self.blinkItem:
            self.blinkState = True
            self.blinkTimer.start(300)
        else:
            self.blinkTimer.stop()

    def clearTable(self):
        """Clears the classification table."""
        self.ui.classificationTable.setRowCount(0)

    def toggleBlink(self):
        """Alternates between visible and invisible text to simulate the flashing of both the arrow and the ID."""
        if self.blinkItem and self.blinkPatientID:
            if self.blinkState:
                self.blinkItem.setText("")  
            else:
                self.blinkItem.setText(f"→ {self.blinkPatientID}")  

            self.blinkState = not self.blinkState  

    def populatePatientDropdown(self):
        dd = self.ui.patientDropdown
        dd.clear()
        dd.addItem("-")

        if not self.datasetPath:
            return

        allIDs = self.logic.getAllPatientIDs(self.datasetPath)

        if self.logic.label_mode == SINGLE_LABEL:
            ids_for_review = [
                pid for pid in allIDs
                if self.singleClassification.get(pid, None) not in (None, "", "DUPLICATE")
            ]
        else:
            ids_for_review = [pid for pid in allIDs if self.isMultiComplete(pid)]

        for pid in sorted(ids_for_review):
            dd.addItem(pid)

    def populateDeleteFeatureDropdown(self):
        """Populate dropdown with the features currently present in the MultiLabel table."""
        if not hasattr(self.ui, "DeleteFeatureDropdown"):
            return

        dd = self.ui.DeleteFeatureDropdown
        dd.blockSignals(True)
        dd.clear()
        dd.addItem("-")

        features = []

        if hasattr(self.ui, "MultiLabeltable"):
            table = self.ui.MultiLabeltable
            for r in range(table.rowCount):
                item = table.item(r, 0)
                if item:
                    name = item.text().strip()
                    if name:
                        features.append(name)

        if not features:
            features = self.getGeneratedFeatureNames()

        for f in features:
            dd.addItem(f)

        dd.blockSignals(False)

    def getMinClassesForFeature(self, feature_name: str) -> int:
        min_required = 2


        for pid, feats in self.multiClassification.items():
            if not isinstance(feats, dict):
                continue
            v = feats.get(feature_name, None)
            if v is None or str(v).strip() == "":
                continue
            try:
                v_int = int(v)
            except Exception:
                continue
            min_required = max(min_required, v_int + 1) 

        return min_required

            
    def onPatientSelected(self):
        """Load the selected patient from the table for classification."""
        from ClassAnnotationLib.ClassAnnotationUtils import compute_patient_hashes

        selectedItems = self.ui.classificationTable.selectedItems()
        if not selectedItems:
            return

        selectedRow = selectedItems[0].row()
        patientID = self.ui.classificationTable.item(selectedRow, 0).text().replace("→ ", "").strip()

        if not patientID or patientID == "-":
            slicer.util.errorDisplay("⚠️ Invalid patient selected!", windowTitle="Error")
            return

        patientFiles = self.logic.getPatientFilesForReview(self.datasetPath, patientID, self.isHierarchical)
        if not patientFiles:
            slicer.util.errorDisplay(f"⚠️ No images found for patient {patientID}!", windowTitle="Error")
            return

        confirmation = qt.QMessageBox.question(
            slicer.util.mainWindow(),
            "Confirm Patient Load",
            f"Are you sure you want to load patient {patientID}?",
            qt.QMessageBox.Yes | qt.QMessageBox.No,
            qt.QMessageBox.No
        )

        if confirmation != qt.QMessageBox.Yes:
            return

        slicer.mrmlScene.Clear(0)
        self.tryLoadPatient(patientID, patientFiles)
        self.disableAllButtons(False)

class ClassAnnotationLogic(ScriptedLoadableModuleLogic):
    """Module logic for image classification."""

    def isFlatDataset(self, datasetPath: str) -> bool:
        """Checks if the dataset is flat (all files are in the main folder)."""
        files = [f for f in os.listdir(datasetPath) if os.path.isfile(os.path.join(datasetPath, f)) and not f.startswith('.') and f != 'classification_results.csv']
        return any(f.lower().endswith(tuple(SUPPORTED_FORMATS)) for f in files)

    def isHierarchicalDataset(self, datasetPath: str) -> bool:
        """Checks if the dataset is hierarchical (each patient has a folder)."""
        subdirs = [d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d))]
        return any(any(f.lower().endswith(tuple(SUPPORTED_FORMATS)) for f in os.listdir(os.path.join(datasetPath, d))) for d in subdirs)

    def loadExistingPatientsFromCSV(self, csvFilePath: str) -> dict:
        existingPatients = {}

        if not os.path.exists(csvFilePath):
            return existingPatients 

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    patientID = row.get("Patient ID")
                    classLabel = row.get("Class")
                    existingPatients[patientID] = int(classLabel) if classLabel and classLabel.isdigit() else classLabel
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
            if f.lower().endswith(tuple(SUPPORTED_FORMATS))
        ]

        return files
    
    def _baseOutputDir(self, datasetPath: str, outputPath: str) -> str:
        mode = getattr(self, "mode", STANDARD_MODE)
        base = datasetPath if mode == STANDARD_MODE else outputPath
        return os.path.join(base, OUTPUT_FOLDER)

    def _singleCsvPath(self, datasetPath: str, outputPath: str) -> str:
        return os.path.join(self._baseOutputDir(datasetPath, outputPath), "classification_results.csv")

    def _multiCsvPath(self, datasetPath: str, outputPath: str) -> str:
        return os.path.join(self._baseOutputDir(datasetPath, outputPath), "result_classification_multiLabel.csv")
    
    def loadSingleCSV(self, datasetPath: str, outputPath: str) -> Tuple[dict, dict]:
        csvFilePath = self._singleCsvPath(datasetPath, outputPath)
        classifiedPatients = {}
        classNames = {}

        if os.path.exists(csvFilePath):
            try:
                with open(csvFilePath, mode='r') as file:
                    reader = csv.reader(file)
                    header = next(reader, None)

                    for row in reader:
                        if len(row) < 2:
                            continue
                        pid = row[0].strip()
                        rawLabel = row[1].strip()

                        if rawLabel.isdigit():
                            lbl = int(rawLabel)
                            classifiedPatients[pid] = lbl
                            if len(row) >= 3 and row[2].strip():
                                classNames[lbl] = row[2].strip()
                        elif rawLabel == "DUPLICATE":
                            classifiedPatients[pid] = "DUPLICATE"
                        else:
                            classifiedPatients[pid] = None
            except Exception as e:
                slicer.util.errorDisplay(f"❌ Error while reading single CSV: {str(e)}", windowTitle="Error")

        allIDs = self.getAllPatientIDs(datasetPath)
        for pid in allIDs:
            if pid not in classifiedPatients:
                classifiedPatients[pid] = None

        return classifiedPatients, classNames
    
    def loadMultiCSV(self, datasetPath: str, outputPath: str) -> Tuple[dict, List[str]]:
        csvFilePath = self._multiCsvPath(datasetPath, outputPath)
        multiDict = {}
        feature_names = []

        allIDs = self.getAllPatientIDs(datasetPath)
        for pid in allIDs:
            multiDict[pid] = {}

        if not os.path.exists(csvFilePath):
            return multiDict, feature_names

        try:
            with open(csvFilePath, mode="r", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return multiDict, feature_names

                # Patient ID + (features...) + Hash
                fields = reader.fieldnames
                feature_names = [c for c in fields if c not in ("Patient ID", "Hash")]

                for row in reader:
                    pid = (row.get("Patient ID") or "").strip()
                    if not pid:
                        continue
                    feats = {}
                    for fn in feature_names:
                        v = row.get(fn, "")
                        v = "" if v is None else str(v).strip()
                        if v != "":
                            feats[fn] = v  
                    multiDict[pid] = feats
        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error while reading multi CSV: {str(e)}", windowTitle="Error")

        return multiDict, feature_names
    
    def saveMultiCSV(self, datasetPath: str, outputPath: str, multiDict: dict, feature_names: List[str]):
        from ClassAnnotationLib.ClassAnnotationUtils import findOriginalFile, compute_patient_hashes

        outDir = self._baseOutputDir(datasetPath, outputPath)
        os.makedirs(outDir, exist_ok=True)
        csvFilePath = self._multiCsvPath(datasetPath, outputPath)

        isHierarchical = self.isHierarchicalDataset(datasetPath)
        allIDs = self.getAllPatientIDs(datasetPath)

        header = ["Patient ID"] + list(feature_names) + ["Hash"]

        try:
            with open(csvFilePath, mode="w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                writer.writeheader()

                for pid in allIDs:
                    feats = multiDict.get(pid, {})
                    if not isinstance(feats, dict):
                        feats = {}

                    row = {"Patient ID": pid, "Hash": ""}

                    for fn in feature_names:
                        row[fn] = feats.get(fn, "")

                    if any(str(v).strip() != "" for v in feats.values()):
                        originalPaths = findOriginalFile(datasetPath, pid, isHierarchical)
                        row["Hash"] = "|".join(sorted(compute_patient_hashes(originalPaths)))

                    writer.writerow(row)
                    self._organizeMultiFolders(outDir, datasetPath, isHierarchical, multiDict, feature_names)

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error saving multi CSV: {str(e)}", windowTitle="Error")
        
    def saveSingleCSV(self, datasetPath: str, outputPath: str, singleDict: dict):
        from ClassAnnotationLib.ClassAnnotationUtils import findOriginalFile, compute_patient_hashes

        outDir = self._baseOutputDir(datasetPath, outputPath)
        os.makedirs(outDir, exist_ok=True)
        csvFilePath = self._singleCsvPath(datasetPath, outputPath)

        widget = slicer.modules.classannotation.widgetRepresentation().self()
        isHierarchical = self.isHierarchicalDataset(datasetPath)

        previousClassMap = {}
        if os.path.exists(csvFilePath):
            try:
                with open(csvFilePath, newline='') as oldFile:
                    reader = csv.DictReader(oldFile)
                    for row in reader:
                        pid = (row.get("Patient ID") or "").strip()
                        if pid:
                            previousClassMap[pid] = (row.get("Class", ""), row.get("Class Name", ""))
            except Exception:
                pass

        patientToClassName = {}

        try:
            with open(csvFilePath, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Patient ID", "Class", "Class Name", "Hash"])

                for pid in self.getAllPatientIDs(datasetPath):
                    lbl = singleDict.get(pid, None)

                    className = ""
                    hashString = ""

                    if lbl is not None and lbl != "" and lbl != "DUPLICATE":
                        btn = widget.classButtons.get(lbl)
                        if btn:
                            actual = btn.text.strip()
                            className = actual if actual != f"Class {lbl}" else ""
                        patientToClassName[pid] = className

                        originalPaths = findOriginalFile(datasetPath, pid, isHierarchical)
                        hashString = "|".join(sorted(compute_patient_hashes(originalPaths)))

                    writer.writerow([pid, lbl if lbl is not None else "", className, hashString])

            # organizzazione folder (solo single)
            self._organizeFolders(outDir, singleDict, previousClassMap, patientToClassName, datasetPath, isHierarchical)

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error saving single CSV: {str(e)}", windowTitle="Error")
        
    # def saveClassificationData(self, datasetPath: str, classificationData: dict, outputFolder: str):
    #     from ClassAnnotationLib.ClassAnnotationUtils import (
    #         movePatientIfReclassified,
    #         findOriginalFile,
    #         compute_patient_hashes
    #     )

    #     mode = getattr(self, "mode", STANDARD_MODE)
    #     finalOutputFolder = os.path.join(datasetPath if mode == "standard" else outputFolder, OUTPUT_FOLDER)
    #     os.makedirs(finalOutputFolder, exist_ok=True)
    #     csvFilePath = os.path.join(finalOutputFolder, "classification_results.csv")

    #     widget = slicer.modules.classannotation.widgetRepresentation().self()

    #     existingClassNames = {button.text.strip().replace(" ", "_").replace("/", "_") for button in widget.classButtons.values()}
    #     for folder in os.listdir(finalOutputFolder):
    #         folderPath = os.path.join(finalOutputFolder, folder)
    #         if os.path.isdir(folderPath) and folder.startswith("class") and folder not in existingClassNames:
    #             shutil.rmtree(folderPath)
                    
    #     try:
    #         isHierarchical = self.isHierarchicalDataset(datasetPath)
    #         patientToClassName = {}

    #         previousClassMap = {}
    #         if os.path.exists(csvFilePath):
    #             with open(csvFilePath, newline='') as oldFile:
    #                 reader = csv.DictReader(oldFile)
    #                 for row in reader:
    #                     pid = row.get("Patient ID", "").strip()
    #                     classLabel = row.get("Class", "").strip()
    #                     className = row.get("Class Name", "").strip()
    #                     if pid:
    #                         previousClassMap[pid] = (classLabel, className)

    #         with open(csvFilePath, mode='w', newline='') as file:
    #             writer = csv.writer(file)
    #             writer.writerow(["Patient ID", "Class", "Class Name", "Hash"])

    #             for patientID, classLabel in sorted(classificationData.items()):
    #                 hashString = ""
    #                 className = ""

    #                 if classLabel is not None and classLabel != "DUPLICATE":
    #                     classButton = widget.classButtons.get(classLabel)
    #                     defaultName = f"Class {classLabel}"
    #                     if classButton:
    #                         actualName = classButton.text.strip()
    #                         className = actualName if actualName != defaultName else ""
    #                     patientToClassName[patientID] = className

    #                     originalFilePaths = findOriginalFile(datasetPath, patientID, isHierarchical)
    #                     hashList = sorted(compute_patient_hashes(originalFilePaths))
    #                     hashString = "|".join(hashList)

    #                 else:
    #                     patientToClassName[patientID] = None

    #                 writer.writerow([
    #                     patientID,
    #                     classLabel if classLabel is not None else "",
    #                     className,
    #                     hashString
    #                 ])

    #         for patientID, classLabel in classificationData.items():
    #             if classLabel is None or classLabel == "DUPLICATE":
    #                 continue

    #             className = patientToClassName.get(patientID, "").strip()
    #             classFolderName = className if className else f"class{classLabel}"
    #             classFolderName = classFolderName.replace(" ", "_").replace("/", "_")
    #             newClassFolder = os.path.join(finalOutputFolder, classFolderName)
    #             os.makedirs(newClassFolder, exist_ok=True)

    #             oldClassLabel, oldClassName = previousClassMap.get(patientID, (None, None))
    #             if oldClassLabel is not None and oldClassLabel != str(classLabel):
    #                 oldFolderName = oldClassName if oldClassName else f"class{oldClassLabel}"
    #                 oldFolderName = oldFolderName.replace(" ", "_").replace("/", "_")
    #                 oldPatientFolder = os.path.join(finalOutputFolder, oldFolderName, patientID)
    #                 if os.path.exists(oldPatientFolder):
    #                     shutil.rmtree(oldPatientFolder)

    #             for folderName in os.listdir(finalOutputFolder):
    #                 potentialPath = os.path.join(finalOutputFolder, folderName, patientID)
    #                 if os.path.exists(potentialPath) and os.path.isdir(potentialPath):
    #                     shutil.rmtree(potentialPath)

    #             newPatientFolder = os.path.join(newClassFolder, patientID)
    #             os.makedirs(newPatientFolder, exist_ok=True)
    #             try:
    #                 originalFilePaths = findOriginalFile(datasetPath, patientID, isHierarchical)
    #                 for originalFilePath in originalFilePaths:
    #                     if originalFilePath:
    #                         fileName = os.path.basename(originalFilePath)
    #                         destPath = os.path.join(newPatientFolder, fileName)
    #                         if not os.path.exists(destPath):
    #                             shutil.copy2(originalFilePath, destPath)
    #             except Exception as copy_error:
    #                 print(f"[WARNING] Failed to copy files for {patientID}: {copy_error}")

                
    #         if hasattr(widget, 'patientHashesFromCSV'):
    #             widget.patientHashesFromCSV = self.loadHashesFromCSV(datasetPath, outputFolder)

    #         for classFolder in os.listdir(finalOutputFolder):
    #             fullClassPath = os.path.join(finalOutputFolder, classFolder)
    #             if os.path.isdir(fullClassPath):
    #                 subitems = [item for item in os.listdir(fullClassPath) if not item.startswith('.')]
    #                 if len(subitems) == 0:
    #                     shutil.rmtree(fullClassPath)
                       
    #     except Exception as e:
    #         slicer.util.errorDisplay(f"❌ Error saving CSV: {str(e)}", windowTitle="Error")

    

    # # # def saveClassificationData(self, datasetPath: str, classificationData: dict, outputFolder: str):
    # # #     import os
    # # #     import csv
    # # #     import shutil
    # # #     from ClassAnnotationLib.ClassAnnotationUtils import findOriginalFile, compute_patient_hashes

    # # #     mode = getattr(self, "mode", "standard")
    # # #     # Identify if we are in Single or Multi label mode
    # # #     label_mode = getattr(self, "label_mode", "single") 
        
    # # #     finalOutputFolder = os.path.join(datasetPath if mode == "standard" else outputFolder, "output")
    # # #     os.makedirs(finalOutputFolder, exist_ok=True)
    # # #     csvFilePath = os.path.join(finalOutputFolder, "classification_results.csv")

    # # #     widget = slicer.modules.classannotation.widgetRepresentation().self()
    # # #     isHierarchical = self.isHierarchicalDataset(datasetPath)

    # # #     try:
    # # #         # --- CASE 1: MULTI-LABEL MODE ---
    # # #         if label_mode == "multi":
    # # #             csvFilePath = os.path.join(finalOutputFolder, "result_classification_multiLabel.csv")

    # # #             # lista COMPLETA pazienti
    # # #             allPatientIDs = self.getAllPatientIDs(datasetPath)

    # # #             # feature names: unione delle feature presenti nei pazienti multi-label
    # # #             feature_set = set()
    # # #             for v in classificationData.values():
    # # #                 if isinstance(v, dict):
    # # #                     feature_set.update(v.keys())
    # # #             feature_names = sorted(feature_set)

    # # #             header = ["Patient ID"] + feature_names + ["Hash"]

    # # #             with open(csvFilePath, mode="w", newline="") as file:
    # # #                 writer = csv.DictWriter(file, fieldnames=header)
    # # #                 writer.writeheader()

    # # #                 for patientID in allPatientIDs:
    # # #                     features = classificationData.get(patientID, None)

    # # #                     row = {"Patient ID": patientID}

    # # #                     # default: tutto vuoto (così per i non classificati resta solo ID)
    # # #                     for f in feature_names:
    # # #                         row[f] = ""
    # # #                     row["Hash"] = ""

    # # #                     # se il paziente è multi-label e ha almeno una feature valorizzata
    # # #                     if isinstance(features, dict) and any(
    # # #                         v is not None and str(v).strip() != "" for v in features.values()
    # # #                     ):
    # # #                         # riempi feature
    # # #                         for f in feature_names:
    # # #                             row[f] = features.get(f, "")

    # # #                         # HASH con la STESSA logica del single-label
    # # #                         originalPaths = findOriginalFile(datasetPath, patientID, isHierarchical)
    # # #                         row["Hash"] = "|".join(sorted(compute_patient_hashes(originalPaths)))

    # # #                     writer.writerow(row)

    # # #             return

    # # #         # --- CASE 2: SINGLE-LABEL MODE ---
    # # #         # Clean up old class folders that no longer exist in the UI
    # # #         existingClassNames = {btn.text.strip().replace(" ", "_").replace("/", "_") for btn in widget.classButtons.values()}
    # # #         for folder in os.listdir(finalOutputFolder):
    # # #             fPath = os.path.join(finalOutputFolder, folder)
    # # #             if os.path.isdir(fPath) and folder.startswith("class") and folder not in existingClassNames:
    # # #                 shutil.rmtree(fPath)

    # # #         previousClassMap = {}
    # # #         if os.path.exists(csvFilePath):
    # # #             with open(csvFilePath, newline='') as oldFile:
    # # #                 reader = csv.DictReader(oldFile)
    # # #                 for row in reader:
    # # #                     pid = row.get("Patient ID", "").strip()
    # # #                     if pid:
    # # #                         previousClassMap[pid] = (row.get("Class", ""), row.get("Class Name", ""))

    # # #         # Save CSV for Single-Label
    # # #         patientToClassName = {}
    # # #         with open(csvFilePath, mode='w', newline='') as file:
    # # #             writer = csv.writer(file)
    # # #             writer.writerow(["Patient ID", "Class", "Class Name", "Hash"])

    # # #             for patientID, classLabel in sorted(classificationData.items()):
    # # #                 if isinstance(classLabel, dict): continue # Skip multi-label data if in single mode
                    
    # # #                 className = ""
    # # #                 hashString = ""
    # # #                 if classLabel is not None and classLabel != "DUPLICATE":
    # # #                     btn = widget.classButtons.get(classLabel)
    # # #                     if btn:
    # # #                         actualName = btn.text.strip()
    # # #                         className = actualName if actualName != f"Class {classLabel}" else ""
                        
    # # #                     patientToClassName[patientID] = className
    # # #                     originalPaths = findOriginalFile(datasetPath, patientID, isHierarchical)
    # # #                     hashString = "|".join(sorted(compute_patient_hashes(originalPaths)))

    # # #                 writer.writerow([patientID, classLabel if classLabel is not None else "", className, hashString])

    # # #         # Physically organize files into class folders
    # # #         self._organizeFolders(finalOutputFolder, classificationData, previousClassMap, patientToClassName, datasetPath, isHierarchical)

    # # #     except Exception as e:
    # # #         slicer.util.errorDisplay(f"❌ Error during save: {str(e)}")

    def loadExistingCSV(self, datasetPath: str, outputPath: str) -> Tuple[dict, dict]:
        return self.loadSingleCSV(datasetPath, outputPath)
    
    def saveClassificationData(self, datasetPath: str, classificationData: dict, outputFolder: str):
        label_mode = getattr(self, "label_mode", SINGLE_LABEL)
        widget = slicer.modules.classannotation.widgetRepresentation().self()

        if label_mode == MULTI_LABEL:
            feature_names = widget.getGeneratedFeatureNames() if hasattr(widget, "getGeneratedFeatureNames") else []
            return self.saveMultiCSV(datasetPath, outputFolder, classificationData, feature_names)

        return self.saveSingleCSV(datasetPath, outputFolder, classificationData)


    def _organizeFolders(self, finalOutputFolder, classificationData, previousClassMap, patientToClassName, datasetPath, isHierarchical):
        import os
        import shutil
        from ClassAnnotationLib.ClassAnnotationUtils import findOriginalFile

        for patientID, classLabel in classificationData.items():
            if classLabel is None or classLabel == "DUPLICATE" or isinstance(classLabel, dict):
                continue

            className = patientToClassName.get(patientID, "").strip()
            classFolderName = (className if className else f"class{classLabel}").replace(" ", "_").replace("/", "_")
            newClassFolder = os.path.join(finalOutputFolder, classFolderName)
            os.makedirs(newClassFolder, exist_ok=True)

            # Remove patient from old class folder if reclassified
            oldLabel, oldName = previousClassMap.get(patientID, (None, None))
            if oldLabel is not None and str(oldLabel) != str(classLabel):
                oldFolderName = (oldName if oldName else f"class{oldLabel}").replace(" ", "_").replace("/", "_")
                oldPatientPath = os.path.join(finalOutputFolder, oldFolderName, patientID)
                if os.path.exists(oldPatientPath):
                    shutil.rmtree(oldPatientPath)

            # Ensure patient folder exists in the new class directory
            newPatientFolder = os.path.join(newClassFolder, patientID)
            os.makedirs(newPatientFolder, exist_ok=True)

            # Copy original files to the new location
            try:
                originalFilePaths = findOriginalFile(datasetPath, patientID, isHierarchical)
                for origPath in originalFilePaths:
                    if origPath:
                        destPath = os.path.join(newPatientFolder, os.path.basename(origPath))
                        if not os.path.exists(destPath):
                            shutil.copy2(origPath, destPath)
            except Exception as err:
                print(f"[WARNING] Copy failed for {patientID}: {err}")

    def _organizeMultiFolders(self, outDir: str, datasetPath: str, isHierarchical: bool,
                          multiDict: dict, feature_names: List[str]):
        """
        Crea/aggiorna:
        outDir/multi_label/<feature>/class<k>/<patientID>/
        Copia i file originali dentro la cartella paziente.
        """
        from ClassAnnotationLib.ClassAnnotationUtils import findOriginalFile

        base = os.path.join(outDir, "multi_label")
        os.makedirs(base, exist_ok=True)

        allIDs = self.getAllPatientIDs(datasetPath)

        for pid in allIDs:
            feats = multiDict.get(pid, {})
            if not isinstance(feats, dict):
                continue

            try:
                originalPaths = findOriginalFile(datasetPath, pid, isHierarchical)
            except Exception:
                originalPaths = []

            for feature in feature_names:
                raw = feats.get(feature, None)
                if raw is None or str(raw).strip() == "":
                    continue

                try:
                    cls = int(raw)
                except Exception:
                    cls = str(raw).strip().replace(" ", "_").replace("/", "_")

                featureDir = os.path.join(base, feature.replace(" ", "_").replace("/", "_"))
                classDir = os.path.join(featureDir, f"class{cls}" if isinstance(cls, int) else f"class_{cls}")
                patientDir = os.path.join(classDir, pid)

                if os.path.exists(featureDir):
                    for c in os.listdir(featureDir):
                        cand = os.path.join(featureDir, c, pid)
                        if os.path.isdir(cand):
                            shutil.rmtree(cand, ignore_errors=True)

                os.makedirs(patientDir, exist_ok=True)

                for src in originalPaths:
                    if not src or not os.path.exists(src):
                        continue
                    dst = os.path.join(patientDir, os.path.basename(src))
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)

        self._cleanupEmptyDirs(base)


    def _cleanupEmptyDirs(self, rootDir: str):
        """Rimuove ricorsivamente directory vuote."""
        for dirpath, dirnames, filenames in os.walk(rootDir, topdown=False):
            visible_files = [f for f in filenames if not f.startswith(".")]
            visible_dirs = [d for d in dirnames if not d.startswith(".")]

            if len(visible_files) == 0 and len(visible_dirs) == 0:
                try:
                    os.rmdir(dirpath)
                except Exception:
                    pass


    def getPatientFilesForReview(self, datasetPath: str, patientID: str, isHierarchical: bool) -> List[str]:
        """Finds images for a previously classified patient."""
        from ClassAnnotationLib.ClassAnnotationUtils import extract_patient_id_from_name   
        patientFiles = []

        if isHierarchical:
            patientPath = os.path.join(datasetPath, patientID)
            if os.path.exists(patientPath):
                patientFiles = [os.path.join(patientPath, f) for f in os.listdir(patientPath) if f.lower().endswith(tuple(SUPPORTED_FORMATS))]
        else:
            # for file in os.listdir(datasetPath):
            #     if file.startswith(patientID) and file.lower().endswith(tuple(SUPPORTED_FORMATS)):
            #         patientFiles.append(os.path.join(datasetPath, file))
            for file in os.listdir(datasetPath):
                if not file.lower().endswith(tuple(SUPPORTED_FORMATS)):
                    continue

                fullPath = os.path.join(datasetPath, file)
                filePatientID = extract_patient_id_from_name(file)

                if filePatientID == patientID:
                    patientFiles.append(fullPath)

        return patientFiles


    def loadExistingCSV(self, datasetPath: str, outputPath: str) -> Tuple[dict, dict]:
        """Upload the data of the patients classified by the correct CSV according to the mode.
        Also retrieves class names from the CSV if available.
        """

        mode = getattr(self, "mode", STANDARD_MODE)

        if mode == "standard":
            csvFilePath = os.path.join(datasetPath, OUTPUT_FOLDER, "classification_results.csv")
        else:
            csvFilePath = os.path.join(outputPath, OUTPUT_FOLDER, "classification_results.csv")

        classifiedPatients = {}
        classNames = {}

        if os.path.exists(csvFilePath):
            try:
                with open(csvFilePath, mode='r') as file:
                    reader = csv.reader(file)
                    header = next(reader, None)  # skip header

                    for row in reader:
                        if len(row) >= 2:
                            patientID = row[0].strip()
                            rawLabel = row[1].strip()

                            if rawLabel.isdigit():
                                classLabel = int(rawLabel)
                                classifiedPatients[patientID] = classLabel

                                if len(row) >= 3:
                                    className = row[2].strip()
                                    if className:
                                        classNames[classLabel] = className

                            elif rawLabel == "DUPLICATE":
                                classifiedPatients[patientID] = "DUPLICATE"
                            else:
                                classifiedPatients[patientID] = None

            except Exception as e:
                slicer.util.errorDisplay(f"❌ Error while reading CSV: {str(e)}", windowTitle="Error")

        allPatientIDs = self.getAllPatientIDs(datasetPath)
        for patientID in allPatientIDs:
            if patientID not in classifiedPatients:
                classifiedPatients[patientID] = None

        return classifiedPatients, classNames


    def countPatientsPerClassFromCSV(self, datasetPath: str, outputPath: str) -> dict:
        """It counts the number of patients for each class reading from the correct CSV."""
        
        mode = getattr(self, "mode", STANDARD_MODE)
        if mode == STANDARD_MODE:
            csvFilePath = os.path.join(datasetPath, OUTPUT_FOLDER, "classification_results.csv")
        else:
            csvFilePath = os.path.join(outputPath, OUTPUT_FOLDER, "classification_results.csv")

        classCounts = {}

        if not os.path.exists(csvFilePath):
            return classCounts

        try:
            with open(csvFilePath, mode='r') as file:
                reader = csv.reader(file)
                next(reader)  
                    
                for row in reader:
                    if len(row) >= 2 and row[1].isdigit():
                        classLabel = int(row[1])
                        classCounts[classLabel] = classCounts.get(classLabel, 0) + 1 

        except Exception as e:
            slicer.util.errorDisplay(f"❌ Error while reading CSV {str(e)}", windowTitle="Error")

        return classCounts


    def isMultiFeatureUsed(self, datasetPath: str, outputPath: str, feature_name: str) -> bool:
        """Return True if the feature column exists and has at least one non-empty value."""
        csvFilePath = self._multiCsvPath(datasetPath, outputPath)
        if not os.path.exists(csvFilePath):
            return False

        try:
            with open(csvFilePath, mode="r", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or feature_name not in reader.fieldnames:
                    return False

                for row in reader:
                    v = row.get(feature_name, "")
                    if v is not None and str(v).strip() != "":
                        return True
        except Exception as e:
            slicer.util.errorDisplay(f" Error reading multi CSV: {str(e)}", windowTitle="Error")
            return True  

        return False


    def removeMultiFeatureColumn(self, datasetPath: str, outputPath: str, feature_names: List[str]):
        """
        Rewrite the multi-label CSV using the provided feature_names as the new set of columns.
        (feature_names = lista DOPO la rimozione)
        """

        widget = slicer.modules.classannotation.widgetRepresentation().self()
        multiDict = getattr(widget, "multiClassification", {})

        self.saveMultiCSV(datasetPath, outputPath, multiDict, feature_names)

        
    def getAllPatientIDs(self, datasetPath: str) -> List[str]:
        """Retrieves all patient IDs in the dataset, including unclassified ones."""
        from ClassAnnotationLib.ClassAnnotationUtils import extract_patient_id_from_name  
    
        patientIDs = set()

        if self.isHierarchicalDataset(datasetPath):
            patientIDs = {d for d in os.listdir(datasetPath) if os.path.isdir(os.path.join(datasetPath, d)) 
                        and d.lower() != OUTPUT_FOLDER and not d.startswith('.')}

        elif self.isFlatDataset(datasetPath):
            allFiles = [
                f for f in os.listdir(datasetPath)
                if os.path.isfile(os.path.join(datasetPath, f))
                and not f.startswith('.')
                and f != 'classification_results.csv'
                and f.lower().endswith(SUPPORTED_FORMATS)
            ]
            for fileName in allFiles:
                patientID = extract_patient_id_from_name(fileName)
                patientIDs.add(patientID)
        
        return sorted(patientIDs)
    

    def loadHashesFromCSV(self, datasetPath: str, outputPath: str) -> Dict[str, str]:
        import csv
        import os

        mode = getattr(self, "mode", "standard")

        if mode == "standard":
            csvPath = os.path.join(datasetPath, "output", "classification_results.csv")
        else:
            csvPath = os.path.join(outputPath, "output", "classification_results.csv")

        patientHashes = {}

        if not os.path.exists(csvPath):
            return patientHashes

        try:
            with open(csvPath, mode='r') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    patientID = row.get("Patient ID")
                    hashStr = row.get("Hash")

                    if patientID and hashStr and hashStr.strip():
                        patientHashes[patientID.strip()] = hashStr.strip()
        except Exception as e:
            print(f"[ERROR] Failed to read CSV: {str(e)}")

        return patientHashes


    def _multiLabelsJsonPath(self, datasetPath, outputPath):
        return os.path.join(self._baseOutputDir(datasetPath, outputPath), "multi_labels.json")
    

    def loadMultiLabels(self, datasetPath, outputPath):
        p = self._multiLabelsJsonPath(datasetPath, outputPath)
        if not os.path.exists(p):
            return {}
        with open(p, "r") as f:
            return json.load(f)  # dict

    def saveMultiLabels(self, datasetPath, outputPath, labelsDict):
        outDir = self._baseOutputDir(datasetPath, outputPath)
        os.makedirs(outDir, exist_ok=True)
        p = self._multiLabelsJsonPath(datasetPath, outputPath)
        with open(p, "w") as f:
            json.dump(labelsDict, f, indent=2)
