classColors = {
            0: "#FF4C4C",  # Red
            1: "#4CAF50",  # Green
            2: "#FF9800",  # Orange
            3: "#FFD700",  # Yellow
            4: "#2196F3",  # Blue
            5: "#9C27B0",  # Purple
            6: "#00BCD4",  # Sky blue
            7: "#8BC34A",  # Light green
            8: "#FF5722",  # Orange red
            9: "#607D8B"   # Bluish gray
        }

def getMainColor(classLabel):
    """Main Color."""
    mainColors = {
        0: "#FF7777",  # Soft red
        1: "#66BB66",  # Balanced green
        2: "#FFBB55",  # Hot orange
        3: "#FFDD55",  # Bright yellow
        4: "#5599FF",  # Light blue
        5: "#B266FF",  # Purple on
        6: "#33CCCC",  # Balanced blue
        7: "#88C766",  # More intense pastel green
        8: "#FF8866",  # Vibrant coral
        9: "#778899"   # Bluish gray
    }
    return mainColors.get(classLabel, "#DDDDDD")


def getLighterColor(classLabel):
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


def getDarkerColor(classLabel):
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


def getClassColor(classLabel):
    """Returns a predefined color for the classes."""
    colors = ["#FF4C4C", "#4CAF50", "#FF9800", "#FFD700", "#2196F3",
              "#9C27B0", "#00BCD4", "#8BC34A", "#FF5722", "#607D8B"]
    return colors[classLabel % len(colors)]


def showDatasetStructureWarning():
    import qt

    """Show a warning with the two supported dataset structures side by side."""

    dialog = qt.QDialog()
    dialog.setWindowTitle("⚠️ Supported Dataset Formats")
    dialog.setModal(True)

    layout = qt.QVBoxLayout()
    dialog.setLayout(layout)

    titleLabel = qt.QLabel(
        "Only the following dataset structures are supported:")
    titleLabel.setStyleSheet("font-weight: bold; font-size: 12pt;")
    layout.addWidget(titleLabel)

    treeLayout = qt.QHBoxLayout()
    layout.addLayout(treeLayout)

    # Hierarchical Tree
    treeHierarchical = qt.QTreeWidget()
    treeHierarchical.setHeaderLabels(["Hierarchical"])
    treeHierarchical.setFixedSize(150, 150)
    treeHierarchical.setSelectionMode(
        qt.QAbstractItemView.NoSelection)  # Rimuove la selezione

    rootHierarchical = qt.QTreeWidgetItem(treeHierarchical, ["CaseID_0001"])
    qt.QTreeWidgetItem(rootHierarchical, ["img.ext"])
    qt.QTreeWidgetItem(rootHierarchical, ["mask.ext"])
    rootHierarchical = qt.QTreeWidgetItem(treeHierarchical, ["CaseID_0002"])
    qt.QTreeWidgetItem(rootHierarchical, ["img.ext"])
    qt.QTreeWidgetItem(rootHierarchical, ["mask.ext"])
    treeHierarchical.expandAll()

    # Flat Tree
    treeFlat = qt.QTreeWidget()
    treeFlat.setHeaderLabels(["Flat"])
    treeFlat.setFixedSize(150, 150)
    treeFlat.setSelectionMode(
        qt.QAbstractItemView.NoSelection)  # Rimuove la selezione

    qt.QTreeWidgetItem(treeFlat, ["img01.ext"])
    qt.QTreeWidgetItem(treeFlat, ["img01_mask.ext"])
    qt.QTreeWidgetItem(treeFlat, ["img02.ext"])
    qt.QTreeWidgetItem(treeFlat, ["img02_mask.ext"])
    treeFlat.expandAll()

    treeLayout.addWidget(treeHierarchical)
    treeLayout.addWidget(treeFlat)

    # OK Button
    buttonOK = qt.QPushButton("OK")
    buttonOK.setFixedWidth(80)
    buttonOK.clicked.connect(lambda: (dialog.accept(), dialog.close()))

    buttonLayout = qt.QHBoxLayout()
    buttonLayout.addStretch()
    buttonLayout.addWidget(buttonOK)
    buttonLayout.addStretch()
    layout.addLayout(buttonLayout)

    dialog.exec_()
