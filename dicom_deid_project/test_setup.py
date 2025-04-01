# test_setup.py
from dicom_deidentification import DicomDeidentifier
from text_detection import TextRemoval

# Define the list of recipes based on available files in dicom_deid/deid_options
recipe_files = [
    "basicProfile",
    "cleanDescOpt",
    "cleanGraphOpt",
    "cleanStructContOpt",
    "rtnDevIdOpt",
    "rtnInstIdOpt",
    "rtnLongFullDatesOpt",
    "rtnLongModifDatesOpt",
    "rtnPatCharsOpt",
    "rtnSafePrivOpt",
    "rtnUIDsOpt"
]

# Initialize DicomDeidentifier with the recipe list
deidentifier = DicomDeidentifier(recipe=recipe_files)

# Initialize TextRemover
text_remover = TextRemoval()

print("✅Modules imported successfully!")
