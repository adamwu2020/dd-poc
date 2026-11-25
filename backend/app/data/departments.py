"""Seed list of departments and their common diseases / presenting symptoms."""

DEPARTMENT_CONDITIONS: dict[str, list[str]] = {
    "Cardiology": [
        "Acute myocardial infarction",
        "Heart failure",
        "Atrial fibrillation",
        "Hypertensive crisis",
        "Infective endocarditis",
        "Aortic stenosis",
        "Chest pain",
        "Palpitations",
        "Syncope",
    ],
    "Emergency Medicine": [
        "Sepsis",
        "Pulmonary embolism",
        "Acute appendicitis",
        "Diabetic ketoacidosis",
        "Anaphylaxis",
        "Acute abdominal pain",
        "Altered mental status",
        "Shortness of breath",
    ],
    "Neurology": [
        "Ischemic stroke",
        "Transient ischemic attack",
        "Migraine",
        "Epilepsy",
        "Bacterial meningitis",
        "Parkinson's disease",
        "Multiple sclerosis",
        "Headache",
        "Dizziness",
    ],
    "Respiratory": [
        "Community-acquired pneumonia",
        "COPD exacerbation",
        "Asthma exacerbation",
        "Pulmonary embolism",
        "Pulmonary tuberculosis",
        "Lung cancer",
        "Chronic cough",
        "Hemoptysis",
    ],
    "Gastroenterology": [
        "Acute pancreatitis",
        "Upper gastrointestinal bleeding",
        "Crohn's disease",
        "Ulcerative colitis",
        "Liver cirrhosis",
        "Acute cholecystitis",
        "Gastroesophageal reflux disease",
        "Abdominal pain",
        "Jaundice",
    ],
    "Endocrinology": [
        "Type 2 diabetes mellitus",
        "Diabetic ketoacidosis",
        "Hyperthyroidism",
        "Hypothyroidism",
        "Adrenal insufficiency",
        "Cushing's syndrome",
        "Fatigue",
        "Unexplained weight loss",
    ],
    "Nephrology": [
        "Acute kidney injury",
        "Chronic kidney disease",
        "Nephrotic syndrome",
        "Hyperkalemia",
        "Urinary tract infection",
        "Edema",
        "Hematuria",
    ],
    "Pediatrics": [
        "Bronchiolitis",
        "Acute otitis media",
        "Kawasaki disease",
        "Gastroenteritis with dehydration",
        "Febrile seizure",
        "Croup",
        "Fever",
        "Rash",
    ],
    "Infectious Disease": [
        "Sepsis",
        "Cellulitis",
        "Urinary tract infection",
        "HIV infection",
        "Infectious mononucleosis",
        "Lyme disease",
        "Fever of unknown origin",
    ],
    "Rheumatology": [
        "Rheumatoid arthritis",
        "Systemic lupus erythematosus",
        "Gout",
        "Giant cell arteritis",
        "Polymyalgia rheumatica",
        "Joint pain",
    ],
}


def find_department(name: str) -> str | None:
    """Case-insensitive lookup of a seeded department name."""
    key = name.strip().lower()
    for dept in DEPARTMENT_CONDITIONS:
        if dept.lower() == key:
            return dept
    return None
