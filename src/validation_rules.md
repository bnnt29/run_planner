End station:
    if at least one connection is valid:
        End valid (green)
    if at least one connection is conditional valid and there are no other valid connections:
        End conditional valid (yellow)
    else:
        End invalid (white)

path:
    has no condition:
        path is traversed at least once :
            valid
        path is never traversed:
            invalid
    has condition:
        path is traversed at least once and condition is always valid:
            valid
        path is traversed at least once and condition is sometimes valid (if station x was traversed x times):
            conditional_valid
        path is traversed at least once and condition is never valid:
            conditional invalid
        path is never traversed:
            invalid


traversal:
    station:
        only traverse following paths if at least one condition is valid
    path:
        only go into following station if the condition is valid (if one is present, else traverse to the following state evrytime)
            