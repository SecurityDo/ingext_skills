# Entity table search patterns (validated on titan)

Single-table queries only; joins to event tables belong to a separate skill.

    <kqlName> | take 10
    <kqlName> | where <Col> contains "text" | project <Col>, <Col2> | take 20
    <kqlName> | where ['Spaced Col'] == "value"
    <kqlName> | summarize Total=count()
    ['ENTITY_Name With Spaces'] | where ['Product name'] contains "E5"

All columns are strings. Entity tables are snapshots: no time filter. Empty tables return zero rows
(titan: ENTITY_Group_Critical_Subnets, ENTITY_AD).
