cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(ClassAnnotation)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/lorenaromeo/SlicerClassAnnotation")
set(EXTENSION_CONTRIBUTORS "Lorena Romeo (Magna Graecia University of Catanzaro, Italy), Ciro Benito Raggio (Karlsruhe Institute of Technology, Germany), Maria Francesca Spadea (Karlsruhe Institute of Technology, Germany), Paolo Zaffino (Magna Graecia University of Catanzaro, Italy)")
set(EXTENSION_DESCRIPTION "Extension for supporting clinicians during the manual annotation of medical image datasets.")
set(EXTENSION_CATEGORY "Utilities")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/lorenaromeo/SlicerClassAnnotation/refs/heads/main/ClassAnnotation.png")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/lorenaromeo/SlicerClassAnnotation/refs/heads/main/ClassAnnotation_screenshot.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(ClassAnnotation)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
