import sys
from pathlib import Path
import pandas as pd

# -----------------------------
# 1. Read CSV from command line
# -----------------------------
if len(sys.argv) < 2:
    print("Usage: python audit.py <input_csv>")
    sys.exit(1)

input_csv = sys.argv[1]
df = pd.read_csv(input_csv)

# Column names
subj_col, pred_col, obj_col = "subject", "predicate", "object"

# -----------------------------
# 2. Define Garo/Mandi keywords
# -----------------------------
keywords = ["garo", "mandi"]
pattern = "|".join(keywords)

# -----------------------------
# 3. Remove irrelevant metadata triples
# -----------------------------
irrelevant_subjects = [
    "Bangladesh", "BangladeshGovernment", "GovernmentOfBangladesh", "GovernmentBangladesh",
    "MinistryOfEducationBangladesh", "NationalEducationPolicy2010", "UNESCO",
    "Participants", "Parents", "Church", "Media", "Researcher", "Study", "Data", "Domains",
    "FamilyDomain", "DifferentDomains", "LanguageMaintenance", "LanguageShift", "Clyne1991",
    "Santals", "BishnupriyaManipuriSpeakers", "SantaliCluster", "EarlyChineseEmpires",
    "NationalCurriculumTextbookBoard", "NCTBInitiative", "NCTB-2010",
    "GovernmentDecision2009", "StateOfficialActivitiesInBangladesh", "LanguagePolicyInBangladesh",
    "EthnicLanguagesInBangladesh", "BangladeshPeople", "EthnicCommunityGroupsMarginalizationInBangladesh",
    "DifferentDomains", "DomainApproach", "Domain", "Research", "ResearchQuestion",
    "TheoreticalFrameworkOfDomainApproach", "LanguageMaintenancePattern",
    "LanguageMaintenanceResearchInThe1980s", "GrandparentsRoleInLanguageMaintenance",
    "StudyResults", "ParticipantsLanguageUseAndPreferencesInsideFamily", "SampleSizeStudy",
    "TableA3", "TableA4", "ParticipantDetailsBasedOnProfessions", "ParticipantDetails",
    "ChristianCommunityMembers", "OtherProfessions", "MaleParticipants", "FemaleParticipants",
    "WorkDomain", "IndigenousDay", "MandiDay", "SampleSizeInterviews"
]

irrelevant_predicates = [
    "IS_STUDIED_BY", "IS_STUDIED", "ARE_STUDIED", "ARE_STUDIED_BY", "IS_A_SOCIOLINGUISTIC_SURVEY",
    "IS_A_DOCTORAL_DISSERTATION", "IS_WRITTEN_BY", "IS_TRUE", "IS_A", "IS_REFERENCED_IN",
    "HAS_VOLUME", "HAS_GRAMMAR_VOLUME_I", "HAS_GRAMMAR_VOLUME_II", "CONTAINS", "HAS_PART",
    "HAS_RELATIONSHIP", "HAVE_A_TRADITION", "ARE_KNOWN_AS", "ARE_SELECTED_FOR_INTERVIEW",
    "ARE_FROM", "HAVE_PROFESSIONS", "WORKS_AT", "TOOK_INITIATIVE", "DECIDED_TO",
    "INITIATED", "HAS_STARTED", "HAS_COMMITTED", "HAS_PUBLISHED", "HAS_RECOMMENDED",
    "RECOMMENDS", "DECIDE", "IGNORING", "CAUSE", "USED", "USED_FOR", "ASKS",
    "DENOTES", "ANALYSED", "VARIES", "VARIES_ACROSS_THE_WORLD", "DEMONSTRATES",
    "PROVES", "ILLUSTRATES", "INVESTIGATES", "TAKE_INITIATIVES", "IS_DISCUSSED_IN",
    "IS_ANALYZED_IN", "IS_LOCATED_IN", "IS_LOCATED", "IS_INFLUENCED_BY", "TYPE", "ROLE"
]

irrelevant_object_markers = [
    "journal", "journalofsocialsciences", "doi", "volume", "issue", "burling",
    "kim et al", "islam, 2008", "khaleque", "sattar & jalil", "das & islam",
    "chowdhury", "ahmed", "brightbill", "cavallaro", "study", "survey", "interviews",
    "tablea3", "tablea4", "participantdetails", "maleparticipants", "femaleparticipants",
    "government", "policy", "education", "book", "article", "dissertation", "doctoral"
]

# Remove known non-entity metadata/background rows
mask = ~df[subj_col].astype(str).isin(irrelevant_subjects)
df = df[mask]

df = df[~df[pred_col].astype(str).isin(irrelevant_predicates)]

df = df[~df[obj_col].astype(str).str.contains('|'.join(irrelevant_object_markers), case=False, na=False)]

# -----------------------------
# 4. Keep only rows related to Garo/Mandi
# -----------------------------
filtered_df = df[
    df[subj_col].astype(str).str.contains(pattern, case=False)
    | df[pred_col].astype(str).str.contains(pattern, case=False)
    | df[obj_col].astype(str).str.contains(pattern, case=False)
]

# Drop obvious non-core rows with generic social-science metadata even if they mention Garo/Mandi
non_core_subjects = [
    "GaroPopulation", "GaroReligion", "GaroLocation", "GaroDialect", "GaroLanguageName",
    "GaroPreferredName", "MainstreamSocietyForeignersWritersPreferredNameForGaro",
    "StudyLanguage", "NoResearchConductedOnGaroLanguageMaintenanceInBangladesh",
    "ExistingResearchOnGaroFocusesOnVariousTopics", "Burling1963StudiedGaroPeople",
    "EllenBalIsAFamousResearcherOnGaroPeople", "TheyAskIfWeEatFrogsBookByEllenBal",
    "FirstPartOfTheyAskIfWeEatFrogsDescribesEthnicCommunityBasedDiscourses",
    "SecondPartOfTheyAskIfWeEatFrogsDescribesGaroHistoryConstitutionAndBoundaries",
    "ThirdPartOfTheyAskIfWeEatFrogsDescribesGaroSelfPerceptionAndGroupFormation",
    "Islam2008FocusesOnGaroOriginAndHistory", "ResearchQuestion", "LanguageShift",
    "LanguageMaintenancePattern", "TheoreticalFrameworkOfDomainApproach",
    "BanglaLinguisticImpactOnMandi", "GaroEducationSystem", "ShiftFromMandiToBangla",
    "GaroCommunitySchools", "ParticipantsOfThisStudy", "ParticipantsOfStudy",
    "SampleSizeInterviews", "LocationOfPeople", "ReasonForEmphasizingBanglaAndEnglish",
    "GlobalizedWorld", "AwarenessMaintainingMotherTongueGaroCommunity",
    "FutureResearchMandiLanguage", "ParticipantsLanguageUseAndPreferencesInsideFamily"
]
filtered_df = filtered_df[~filtered_df[subj_col].astype(str).isin(non_core_subjects)]

# -----------------------------
# 5. Predicate shortening rules
# -----------------------------
predicate_map = {
    "HAS_A_POPULATION": "population",
    "SPEAKS": "speaks",
    "USES": "uses",
    "LIVES_IN": "lives",
    "BELIEVES_IN": "belief",
    "PRACTICES": "practices",
    "HAS_DOMINANT_LANGUAGE": "dominant_lang",
    "HAS_SECOND_LANGUAGE": "second_lang",
    "HAS_LANGUAGE_SHIFT": "shift",
    "HAS_LANGUAGE_MAINTENANCE": "maintains",
    "HAS_EDUCATION_LEVEL": "education",
    "HAS_RELIGION": "religion",
    "HAS_LOCATION": "location",
    "HAS_DIALECT": "dialect",
    "HAS_LANGUAGE": "language",
    "HAS_CULTURE": "culture",
    "HAS_TRADITION": "tradition",
    "HAS_OCCUPATION": "occupation",
    "HAS_AGE_GROUP": "age_group",
    "HAS_PREFERENCE": "preference",
    "HAS_LANGUAGE_USAGE": "usage",
    "HAS_LANGUAGE_ATTITUDE": "attitude",
}

# Apply shortening
filtered_df[pred_col] = filtered_df[pred_col].astype(str).apply(
    lambda p: predicate_map.get(p, p)  # default: keep original if not mapped
)

# -----------------------------
# 6. Remove duplicate triples
# -----------------------------
clean_df = filtered_df.drop_duplicates()

# -----------------------------
# 7. Save cleaned data
# -----------------------------
output_path = Path(__file__).resolve().parent / "cleaned_garo_mandi_data.csv"
clean_df.to_csv(output_path, index=False)

print(f"Cleaned dataset saved to: {output_path}")
print(clean_df)
