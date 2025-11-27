import pydicom
from pydicom.uid import generate_uid

PHI_TAGS = [
    ('PatientName', ''), ('PatientID', ''), ('PatientBirthDate', ''),
    ('PatientSex', ''), ('OtherPatientIDs', ''), ('OtherPatientNames', ''),
    ('PatientAddress', ''), ('PatientTelephoneNumbers', ''),
    ('IssuerOfPatientID', ''), ('PatientMotherBirthName', ''),
    ('PatientBirthTime', ''), ('PatientWeight', ''),
    ('ReferringPhysicianName', ''), ('InstitutionName', ''), ('InstitutionAddress', ''),
    ('AccessionNumber', ''), ('StudyID', ''), ('RequesterName', ''),
    ('RequestingPhysician', ''), ('PerformedStationAETitle', ''),
]

UID_TAGS = ['StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID']


class SimpleDicomDeidentifier:
    """De-identify DICOM **metadata only**; pixel data is left untouched."""

    def __call__(self, in_path: str, out_path: str):
        ds = pydicom.dcmread(in_path, force=True)

        # Remove all private tags
        ds.remove_private_tags()

        # Basic PHI blanking
        for name, value in PHI_TAGS:
            if hasattr(ds, name):
                setattr(ds, name, value)

        # Mark de-identification
        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = "Basic profile; UIDs remapped"

        # Remap UIDs (new, non-reversible)
        for name in UID_TAGS:
            if hasattr(ds, name):
                setattr(ds, name, generate_uid())

        # DO NOT touch PixelData or any pixel format tags
        ds.save_as(out_path)
