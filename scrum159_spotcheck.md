# SCRUM-159 Spot Check of Extracted Triples

## Scope
Spot-checked extraction outputs from the six manually approved papers.

## Findings

### Valid examples
- GaroCommunity -[IS_A]-> MajorIndigenousCommunityInBangladesh
- GaroCommunity -[HAS_UNIQUE]-> MatrilinealSocialSystem
- MatrilinealSocialSystem -[TRANSMITS_INHERITANCE]-> Maternally
- GaroTribe -[PRACTICES]-> TraditionalFarmingSystem
- GaroIndigenousCommunity -[IS_LOCATED_IN]-> Bangladesh

These examples were consistent with their supporting sentence references.

### Issues identified
1. UNKNOWN -[UNKNOWN]-> UNKNOWN
   - Indicates parsing/extraction failure.
   - Appeared in more than one output file.

2. GaroWomen -[ARE_KNOWN_AS]-> SkilledBeauticians
   - Supporting sentence was unrelated to beauticians.
   - Classified as a hallucinated/incorrect triple.

3. Some triples overgeneralised the supporting text.
   - Example: GaroPopulation -[IS_CLASSIFIED_AS]-> IndigenousPeople
   - Supporting sentence referred broadly to Indigenous people worldwide rather than specifically to the Garo population.

## Result
The extraction pipeline produces many valid and traceable triples, but spot-checking identified malformed, hallucinated, and overgeneralised relationships. These should be filtered or reviewed before loading all extracted results into the final knowledge graph.
